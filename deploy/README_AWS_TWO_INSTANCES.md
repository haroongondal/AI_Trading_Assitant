# AWS: connect, configure, and link API + Ollama EC2

This runbook assumes you already ran:

- `provision_aws_backend.py` → API host (FastAPI)
- `provision_aws_ollama.py` → Ollama host

Both instances use **IAM roles with `AmazonSSMManagedInstanceCore`** and **no
inbound SSH** by default. Connect with **AWS Systems Manager Session Manager**.

For the full architecture story, see
[../docs/AWS_ZERO_COST_DEPLOYMENT.md](../docs/AWS_ZERO_COST_DEPLOYMENT.md).

---

## Prerequisites (on your laptop)

1. [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
   installed and configured (same credentials as `backend/deploy/.env`:
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`).
2. [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
   for the AWS CLI — required to open a shell on the instances (SSH is not
   opened by the provision scripts).

---

## AWS CLI automation (run on your computer)

From `backend/deploy/`, the script reads `config/aws-backend.json` and
`config/aws-ollama.json`, loads `.env` if present, and runs `aws` commands for
you.

```bash
cd backend/deploy
chmod +x scripts/aws_tasks.sh   # once

./scripts/aws_tasks.sh status     # IDs, state, IPs, primary SGs, suggested OLLAMA_BASE_URL line
./scripts/aws_tasks.sh ssm        # prints exact aws ssm start-session commands (you run them manually)
./scripts/aws_tasks.sh ssm-ping   # SSM agent Online / not
./scripts/aws_tasks.sh backend-sg # API security group id (for aws-ollama.json)
./scripts/aws_tasks.sh help

# Or start a session directly (uses .env for keys; region from .env or config/aws-backend.json):
chmod +x scripts/ssm_session.sh   # once
./scripts/ssm_session.sh i-0123456789abcdef0
```

**Manual step:** run `./scripts/ssm_session.sh <instance-id>` (get IDs from
`./scripts/aws_tasks.sh status`) or copy the `aws ssm start-session ...` lines
from `./scripts/aws_tasks.sh ssm`. Use two terminal tabs for backend and Ollama.
Everything below this section runs **inside** those sessions on the instances.

If `start-session` fails, fix **SSM** first (instance running, IAM role with
`AmazonSSMManagedInstanceCore`, endpoint reachability).

---

## Configure the Ollama instance

Run these **on the Ollama instance** (inside the SSM session).

### 1. Install or repair Ollama (systemd)

If `systemctl start ollama` says **Unit ollama.service not found**, the Ollama
Linux installer never completed on this VM (common if user-data failed or you
created the instance without it). On Ubuntu/Debian, run:

```bash
curl -fsSL https://ollama.com/install.sh | sudo sh
sudo systemctl enable --now ollama
```

Then confirm:

```bash
sudo systemctl status ollama
curl -sS http://127.0.0.1:11434/api/tags | head
```

`which ollama` should show `/usr/local/bin/ollama` after a successful install.

### 2. Expose Ollama to backend instance (VPC-only)

By default, Ollama can bind to loopback only (`127.0.0.1`). If that happens,
local curl works on the Ollama host but backend-to-Ollama requests hang/time
out.

Set Ollama to listen on all interfaces, then restart:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
cat <<'EOF' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl status ollama
```

Verify listener on the Ollama host:

```bash
sudo ss -lntp | grep 11434
```

You should see `0.0.0.0:11434` (or `*:11434`), not only `127.0.0.1:11434`.

### 3. Pull models (required for this app)

```bash
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

Optional smaller/fallback chat model:

```bash
ollama pull phi3:mini
```

### 4. Quick test

```bash
ollama run qwen2.5:3b "Reply with one word: OK"
```

**Note:** On `t3.micro`, pulls and inference can be slow or run out of memory.
If needed, stop other services and use a smaller model, or resize the instance
when your account allows non-free-tier types.

---

## Configure the API backend instance

Run these **on the backend instance** (inside the SSM session).

### 1. Install packages (if not already done)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential nginx certbot python3-certbot-nginx
```

### 2. App tree and virtualenv

Adjust `YOUR_BACKEND_REPO_URL` (or copy the `backend` folder with
`scp`/`rsync`).

```bash
sudo mkdir -p /opt/ai-trading-assistant
sudo chown -R "$USER:$USER" /opt/ai-trading-assistant
cd /opt/ai-trading-assistant
git clone YOUR_BACKEND_REPO_URL backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
mkdir -p data
```

### 3. Point the backend at Ollama (same VPC)

Copy env template and edit:

```bash
cd /opt/ai-trading-assistant/backend
cp .env.example .env
nano .env   # or vim
```

Set at least:

```env
OLLAMA_BASE_URL=http://OLLAMA_PRIVATE_IP:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Replace `OLLAMA_PRIVATE_IP` with the private IP from the CLI section above
(example: `172.31.91.7`).

Keep `DATABASE_URL` and `CHROMA_PERSIST_DIR` as in `.env.example` unless you use
a different layout.

Set `CORS_ORIGINS` and `FRONTEND_URL` to match your Vercel app if you use the
browser frontend.

### 4. Prove the backend can reach Ollama

Still on the **backend** instance:

```bash
curl -sS "http://OLLAMA_PRIVATE_IP:11434/api/tags"
```

You should see JSON listing models. If this times out:

- Confirm both instances are in the **same VPC** (or routable subnets).
- Confirm `provision_aws_ollama.py` used the correct `backend_security_group_id`
  (the API instance’s `sg-...`).
- Security group on Ollama must allow **TCP 11434** from that backend SG (the
  script sets this when configured correctly).

### 5. Start the API (Uvicorn) — **required for port 8000**

Nginx proxies to `127.0.0.1:8000`, but **nothing listens there until Uvicorn is
running**. If `curl http://127.0.0.1:8000/health` says _Connection refused_, the
app process is not started (or failed on boot).

**Order:** get venv + `.env` right (steps 2–3) → **start Uvicorn** (this step) →
only then configure Nginx (step 6).

#### 5a. One-off test (foreground)

Use this to see import errors or missing env vars immediately (stop with
Ctrl+C):

```bash
cd /opt/ai-trading-assistant/backend
source .venv/bin/activate
export PYTHONUNBUFFERED=1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From a **second** SSM session on the same instance:

```bash
curl -sS http://127.0.0.1:8000/health
```

You should see `{"status":"ok"}`. If the foreground server prints a traceback,
fix that before systemd.

**Alternative (no `activate`, same as Makefile `make start` but bound to
localhost):**

```bash
cd /opt/ai-trading-assistant/backend
PYTHONUNBUFFERED=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

(`make start` uses `--host 0.0.0.0`, which also works behind Nginx; for systemd
below we keep `127.0.0.1` so the app is not exposed except via Nginx.)

#### 5b. Production: systemd unit

Create `/etc/systemd/system/ai-trading-backend.service`:

```ini
[Unit]
Description=AI Trading Assistant FastAPI Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/ai-trading-assistant/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/ai-trading-assistant/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

If your login user is not `ubuntu`, change `User=` to match (`whoami`). The unit
must run as a user that can read `/opt/ai-trading-assistant/backend` and `.env`.
The app loads `.env` from `WorkingDirectory` (Pydantic settings); you do not
need `EnvironmentFile` in systemd unless you prefer duplicating env there.

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-trading-backend
sudo systemctl start ai-trading-backend
sudo systemctl status ai-trading-backend
curl -sS http://127.0.0.1:8000/health
```

**If `curl` still fails or the service is `failed`:**

```bash
sudo journalctl -u ai-trading-backend -n 80 --no-pager
test -x /opt/ai-trading-assistant/backend/.venv/bin/uvicorn && echo "uvicorn ok" || echo "missing venv or pip install"
```

Typical issues: wrong `User=`, venv path differs, `pip install -e .` not run,
bad `.env` (service exits on startup).

### 6. Nginx + TLS (public API)

Do this **after** `curl http://127.0.0.1:8000/health` succeeds locally.

Use your real hostname instead of `api-example.dynu.net` (or your FreeDNS/Afraid
domain).

Free DDNS options that work here:

- Dynu (example host: `api-example.dynu.net`)
- FreeDNS / Afraid.org (example host: `api-example.mooo.com`)

Whichever provider you use, point the hostname A record to the API instance
public IP before running Certbot.

```bash
sudo nano /etc/nginx/sites-available/ai-trading-backend
```

Minimal HTTP server block (same as main deployment guide):

```nginx
server {
    listen 80;
    server_name api-example.dynu.net;
    client_max_body_size 10m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
    }
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/ai-trading-backend /etc/nginx/sites-enabled/ai-trading-backend
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api-example.dynu.net
```

---

## Optional: auto-update Dynu DNS from backend instance

Use this if your backend EC2 public IP may change and you want Dynu to follow it
automatically.

Run these on the **backend instance**:

```bash
sudo cp /opt/ai-trading-assistant/backend/deploy/templates/dynu-ddns-update.sh /usr/local/bin/dynu-ddns-update.sh
sudo chmod +x /usr/local/bin/dynu-ddns-update.sh

sudo cp /opt/ai-trading-assistant/backend/deploy/templates/dynu-ddns.service /etc/systemd/system/dynu-ddns.service
sudo cp /opt/ai-trading-assistant/backend/deploy/templates/dynu-ddns.timer /etc/systemd/system/dynu-ddns.timer
```

Create Dynu config (uses [REST API v2](https://www.dynu.com/support/api) with an
**API key** from Dynu Control Panel → **API Credentials**):

```bash
sudo tee /etc/default/dynu-ddns >/dev/null <<'EOF'
DYNU_API_KEY=YOUR_DYNU_API_KEY
# Match the DNS hostname name exactly as shown under Dynamic DNS in Dynu (or set DYNU_DNS_ID instead).
DYNU_HOSTNAME=api-example.dynu.net
# Optional: numeric id from Dynu; if set, DYNU_HOSTNAME lookup is skipped.
# DYNU_DNS_ID=12345678
# Optional: "imds" (default, AWS metadata) or "external" (ipify).
DYNU_IP_SOURCE=imds
EOF
sudo chmod 600 /etc/default/dynu-ddns
```

**Alternative — [IP Update Protocol](https://www.dynu.com/DynamicDNS/IP-Update-Protocol) (GET only):**

Dynu documents this as the long-standing way to push a new IPv4: **`GET https://api.dynu.com/nic/update`** with query parameters `hostname`, `password`, and optionally `myip`. It avoids REST **`POST /v2/dns/{id}`**, which some environments see as HTTP **505**. The template script supports it when **`DYNU_NIC_PASSWORD`** is set (then **`DYNU_API_KEY` is not required**).

- **`DYNU_NIC_PASSWORD`**: the **IP update / DDNS password** for that hostname in the Dynu control panel (you may use the plain password or an MD5/SHA-256 hash of it, per [Dynu’s IP Update Protocol](https://www.dynu.com/DynamicDNS/IP-Update-Protocol)).
- **`DYNU_HOSTNAME`**: must match the FQDN (no trailing spaces on the line in `/etc/default/dynu-ddns`).

Example:

```bash
sudo tee /etc/default/dynu-ddns >/dev/null <<'EOF'
DYNU_HOSTNAME=api-example.dynu.net
DYNU_NIC_PASSWORD=your_ip_update_password_or_md5_hash
DYNU_IP_SOURCE=imds
EOF
sudo chmod 600 /etc/default/dynu-ddns
```

Success log line: `dynu nic/update ok: script_rev=... hostname=... ipv4=... response=good ...` (or `nochg` if the IP was already correct).

Enable and test:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dynu-ddns.timer
sudo systemctl start dynu-ddns.service
sudo journalctl -u dynu-ddns.service -n 50 --no-pager
```

Expected log line (REST mode): `dynu v2 update ok: script_rev=... dns_id=... ipv4=...` plus JSON from Dynu
(pretty-printed when possible).

**If you see `missing required env var: DYNU_API_KEY`:**

- The unit reads **`/etc/default/dynu-ddns`** via `EnvironmentFile`. Each line
  must be `KEY=value` — **do not** use `export` (systemd does not apply those
  the same way as a shell).
- Replace `YOUR_DYNU_API_KEY` with the real key from Dynu → **API Credentials**;
  save the file, then:

```bash
sudo systemctl daemon-reload
sudo systemctl start dynu-ddns.service
```

- Confirm the line is really in the file (not commented, no typo):

```bash
sudo grep -E '^DYNU_API_KEY=' /etc/default/dynu-ddns
sudo systemctl show dynu-ddns.service -p EnvironmentFiles --no-pager
```

**If you see `unexpected /dns response (not a list)`:**

Dynu’s API returns JSON like `{"statusCode": 200, "domains": [...]}` rather than
a bare array. Your server is still running an **old** copy of the script. Copy
the latest template to the instance and retry:

```bash
sudo cp /opt/ai-trading-assistant/backend/deploy/templates/dynu-ddns-update.sh /usr/local/bin/dynu-ddns-update.sh
sudo chmod +x /usr/local/bin/dynu-ddns-update.sh
sudo systemctl start dynu-ddns.service
```

**If you see `curl: (22) ... error: 505`:**

1. Deploy the latest `dynu-ddns-update.sh` from this repo (successful runs log **`script_rev=`**; current template is rev **5**). It uses **HTTP/1.1**, **`--no-alpn`** when `curl` supports it, and **retries with HTTP/1.0** when the error looks like HTTP 505.
2. Set **`DYNU_DNS_ID`** so the job skips **`GET /v2/dns`** (list) and only runs **`POST /v2/dns/{id}`** (your manual test showed **`GET /v2/dns/{id}`** can work while list/POST misbehave).
3. If POST still fails, switch to **[IP Update Protocol](https://www.dynu.com/DynamicDNS/IP-Update-Protocol)**: set **`DYNU_NIC_PASSWORD`** + **`DYNU_HOSTNAME`** and remove reliance on REST (see example above).

**Timer vs one-shot service:** `systemctl stop dynu-ddns.service` does not stop
**`dynu-ddns.timer`**. To pause scheduled runs while testing, use
`sudo systemctl stop dynu-ddns.timer` (and `start` again when done).

---

## End-to-end checks

On the **backend** instance (or from your laptop against the public API URL):

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/health
```

`api/health` should report `database` and `ollama` as **ok** when
`OLLAMA_BASE_URL` is correct and Ollama is up.

From your laptop (if you have HTTPS + DNS):

```bash
curl -sS https://YOUR_API_HOST/health
curl -sS https://YOUR_API_HOST/api/health
```

---

## Quick reference: networking

| From         | To              | Port   | Purpose                          |
| ------------ | --------------- | ------ | -------------------------------- |
| Internet     | API instance    | 80/443 | Nginx → FastAPI                  |
| API instance | Ollama instance | 11434  | Ollama HTTP API                  |
| Internet     | Ollama instance | 11434  | Should stay closed in production |

The provision script is meant to allow **11434 only from the backend security
group** (not the world).

---

## Logs

**Backend**

```bash
sudo journalctl -u ai-trading-backend -n 100 --no-pager
sudo tail -n 50 /var/log/nginx/error.log
```

**Ollama**

```bash
sudo journalctl -u ollama -n 100 --no-pager
```
