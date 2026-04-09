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
    curl -fsS "${API_BASE}/dns" \
      -H "accept: application/json" \
      -H "API-Key: ${DYNU_API_KEY}"
  )"
  echo "$raw" | python3 -c "
import json, sys
want = sys.argv[1].strip().lower()
data = json.load(sys.stdin)
if not isinstance(data, list):
    raw = json.dumps(data)[:200]
    sys.stderr.write(f'error: unexpected /dns response (not a list): {raw!r}\n')
    sys.exit(1)
for row in data:
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
  curl -fsS -X POST "${API_BASE}/dns/${DNS_ID}" \
    -H "accept: application/json" \
    -H "Content-Type: application/json" \
    -H "API-Key: ${DYNU_API_KEY}" \
    -d "$BODY"
)"

echo "dynu v2 update ok: dns_id=${DNS_ID} ipv4=${PUBLIC_IP}"
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
