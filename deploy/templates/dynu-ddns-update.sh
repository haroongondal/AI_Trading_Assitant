#!/usr/bin/env bash
# Update Dynu DDNS IPv4 via REST API v2 (https://api.dynu.com/v2/).
# Auth: header API-Key (create in Dynu Control Panel → API Credentials).
#
# Env (e.g. /etc/default/dynu-ddns — systemd EnvironmentFile: KEY=value only, no "export"):
#   DYNU_API_KEY       required
#   DYNU_DNS_ID        optional numeric id (skips hostname lookup)
#   DYNU_HOSTNAME      required if DYNU_DNS_ID unset; must match DNS service name in Dynu
#   DYNU_IP_SOURCE     optional: imds (default) | external
#   DYNU_API_BASE      optional; default https://api.dynu.com/v2
#
# Bump when behavior changes (check journal for "script_rev=" after a successful run).
SCRIPT_REV=4

set -euo pipefail

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "error: missing required env var: $name" >&2
    if [[ "$name" == "DYNU_API_KEY" ]]; then
      echo "hint: edit /etc/default/dynu-ddns as root. Use exactly: DYNU_API_KEY=your_key (no spaces around =)." >&2
      echo "hint: systemd ignores 'export' in EnvironmentFile — do not prefix lines with export." >&2
      echo "hint: confirm line exists: sudo grep -E '^DYNU_API_KEY=' /etc/default/dynu-ddns" >&2
    fi
    exit 1
  fi
}

get_imdsv2_token() {
  curl -fsS -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"
}

get_public_ip_from_imds() {
  local token
  token="$(get_imdsv2_token)" || return 1
  curl -fsS -H "X-aws-ec2-metadata-token: $token" \
    "http://169.254.169.254/latest/meta-data/public-ipv4"
}

get_public_ip_external() {
  curl -fsS "https://api.ipify.org"
}

require "DYNU_API_KEY"

API_BASE="${DYNU_API_BASE:-https://api.dynu.com/v2}"
API_BASE="${API_BASE%/}"
if [[ "$API_BASE" != https://* ]]; then
  echo "error: DYNU_API_BASE must start with https:// (got: ${API_BASE})" >&2
  exit 1
fi

# Optional: disable TLS ALPN when curl supports it (helps avoid HTTP 505 from some edges).
DYNU_CURL_NO_ALPN=()
if curl --help all 2>/dev/null | grep -qF -- '--no-alpn'; then
  DYNU_CURL_NO_ALPN=(--no-alpn)
fi

# Dynu API via curl: prefer HTTP/1.1; retry with HTTP/1.0 if server returns 505.
_run_dynu_curl() {
  local tmp err
  tmp="$(mktemp)"
  err="$(mktemp)"
  cleanup() { rm -f "$tmp" "$err"; }
  trap cleanup RETURN
  if curl -fsS --http1.1 "${DYNU_CURL_NO_ALPN[@]}" "$@" >"$tmp" 2>"$err"; then
    cat "$tmp"
    return 0
  fi
  if grep -qE '505|HTTP Version' "$err" 2>/dev/null; then
    if curl -fsS --http1.0 "${DYNU_CURL_NO_ALPN[@]}" "$@" >"$tmp" 2>"$err"; then
      cat "$tmp"
      return 0
    fi
  fi
  cat "$err" >&2
  return 1
}

IP_SOURCE="${DYNU_IP_SOURCE:-imds}"
PUBLIC_IP=""

if [[ "$IP_SOURCE" == "imds" ]]; then
  PUBLIC_IP="$(get_public_ip_from_imds || true)"
  if [[ -z "$PUBLIC_IP" ]]; then
    PUBLIC_IP="$(get_public_ip_external || true)"
  fi
else
  PUBLIC_IP="$(get_public_ip_external || true)"
fi

if [[ -z "$PUBLIC_IP" ]]; then
  echo "error: could not determine public IPv4" >&2
  exit 1
fi

resolve_dns_id() {
  if [[ -n "${DYNU_DNS_ID:-}" ]]; then
    echo "$DYNU_DNS_ID"
    return 0
  fi
  require "DYNU_HOSTNAME"
  local raw
  raw="$(
    _run_dynu_curl "${API_BASE}/dns" \
      -H "accept: application/json" \
      -H "API-Key: ${DYNU_API_KEY}"
  )"
  echo "$raw" | python3 -c "
import json, sys
want = sys.argv[1].strip().lower()
data = json.load(sys.stdin)
# Dynu v2 may return a bare list of domains or {\"statusCode\": 200, \"domains\": [...]}.
if isinstance(data, dict):
    sc = data.get('statusCode')
    if sc is not None and int(sc) != 200:
        sys.stderr.write(f'error: GET /dns statusCode={sc!r}\n')
        sys.exit(1)
    rows = data.get('domains') or data.get('Domains') or []
elif isinstance(data, list):
    rows = data
else:
    raw = json.dumps(data)[:200]
    sys.stderr.write(f'error: unexpected /dns JSON shape: {raw!r}\n')
    sys.exit(1)
if not isinstance(rows, list):
    sys.stderr.write('error: /dns domains field is not a list\n')
    sys.exit(1)
for row in rows:
    name = (row.get('name') or row.get('Name') or '').strip().lower()
    if name == want:
        rid = row.get('id') if 'id' in row else row.get('Id')
        if rid is not None:
            print(int(rid))
            sys.exit(0)
sys.stderr.write(
    f'error: no DNS service matching hostname {want!r} in GET /dns; '
    'set DYNU_DNS_ID from Dynu control panel or fix DYNU_HOSTNAME\n'
)
sys.exit(1)
" "$DYNU_HOSTNAME"
}

DNS_ID="$(resolve_dns_id)"

export PUBLIC_IP
BODY="$(python3 -c "import json, os; print(json.dumps({'ipv4Address': os.environ['PUBLIC_IP'], 'ipv4': True}))")"

RESP="$(
  _run_dynu_curl -X POST "${API_BASE}/dns/${DNS_ID}" \
    -H "accept: application/json" \
    -H "Content-Type: application/json" \
    -H "API-Key: ${DYNU_API_KEY}" \
    -d "$BODY"
)"

echo "dynu v2 update ok: script_rev=${SCRIPT_REV} dns_id=${DNS_ID} ipv4=${PUBLIC_IP}"
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
