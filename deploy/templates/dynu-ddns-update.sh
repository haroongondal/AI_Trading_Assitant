#!/usr/bin/env bash
# Update Dynu DDNS IPv4 for this host.
#
# Credentials (see https://www.dynu.com/Support/API and
# https://www.dynu.com/DynamicDNS/IP-Update-Protocol):
#   - REST API v2: DYNU_API_KEY + optional DYNU_DNS_ID / DYNU_HOSTNAME
#   - IP Update Protocol: DYNU_NIC_PASSWORD + DYNU_HOSTNAME (GET nic/update)
#
# If BOTH API key and DYNU_NIC_PASSWORD are set, the script tries REST first and
# falls back to nic/update when REST fails (e.g. HTTP 505 from POST on some EC2/curl paths).
# Set DYNU_SKIP_REST=1 to use only nic/update when both are present (no REST attempt).
#
# Env (e.g. /etc/default/dynu-ddns — systemd EnvironmentFile: KEY=value only, no "export"):
#   DYNU_API_KEY         REST mode; optional if DYNU_NIC_PASSWORD is set (fallback path)
#   DYNU_NIC_PASSWORD    IP update password (or MD5/SHA-256 per Dynu); optional if API key set
#   DYNU_HOSTNAME        required for nic/update; for REST if DYNU_DNS_ID unset
#   DYNU_DNS_ID          optional; numeric id skips GET /dns list
#   DYNU_IP_SOURCE       optional: imds (default) | external
#   DYNU_API_BASE        optional; default https://api.dynu.com/v2 (REST only)
#   DYNU_SKIP_REST       optional: 1|yes|true — with both creds, use nic only
#
# Bump when behavior changes (check journal for "script_rev=" after a successful run).
SCRIPT_REV=6

set -euo pipefail

_dynu_trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

_dynu_truthy() {
  case "$(_dynu_trim "${1:-}")" in
    1|yes|true|TRUE|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "error: missing required env var: $name" >&2
    if [[ "$name" == "DYNU_API_KEY" ]]; then
      echo "hint: edit /etc/default/dynu-ddns as root. Use exactly: DYNU_API_KEY=your_key (no spaces around =)." >&2
      echo "hint: or set DYNU_NIC_PASSWORD + DYNU_HOSTNAME for IP Update Protocol (GET nic/update)." >&2
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

# Optional: disable TLS ALPN when curl supports it (helps avoid HTTP 505 from some edges).
DYNU_CURL_NO_ALPN=()
if curl --help all 2>/dev/null | grep -qF -- '--no-alpn'; then
  DYNU_CURL_NO_ALPN=(--no-alpn)
fi

# Force IPv4 to api.dynu.com (dual-stack instances sometimes hit a broken path / 505).
DYNU_CURL_V4=()
if curl --help all 2>/dev/null | grep -qF -- '-4, --ipv4'; then
  DYNU_CURL_V4=(-4)
fi

# Dynu REST / nic: prefer HTTP/1.1; retry with HTTP/1.0 if server returns 505.
_run_dynu_curl() {
  local tmp err
  tmp="$(mktemp)"
  err="$(mktemp)"
  cleanup() { rm -f "$tmp" "$err"; }
  trap cleanup RETURN
  if curl -fsS "${DYNU_CURL_V4[@]}" --http1.1 "${DYNU_CURL_NO_ALPN[@]}" "$@" >"$tmp" 2>"$err"; then
    cat "$tmp"
    return 0
  fi
  if grep -qE '505|HTTP Version' "$err" 2>/dev/null; then
    if curl -fsS "${DYNU_CURL_V4[@]}" --http1.0 "${DYNU_CURL_NO_ALPN[@]}" "$@" >"$tmp" 2>"$err"; then
      cat "$tmp"
      return 0
    fi
  fi
  cat "$err" >&2
  return 1
}

# IP Update Protocol — GET only (same host as REST; see Dynu docs).
_run_nic_update() {
  local tmp err
  tmp="$(mktemp)"
  err="$(mktemp)"
  cleanup() { rm -f "$tmp" "$err"; }
  trap cleanup RETURN
  if curl -fsS "${DYNU_CURL_V4[@]}" --http1.1 "${DYNU_CURL_NO_ALPN[@]}" -G "https://api.dynu.com/nic/update" \
      --data-urlencode "hostname=${DYNU_HOSTNAME}" \
      --data-urlencode "myip=${PUBLIC_IP}" \
      --data-urlencode "password=${DYNU_NIC_PASSWORD}" \
      >"$tmp" 2>"$err"; then
    cat "$tmp"
    return 0
  fi
  if grep -qE '505|HTTP Version' "$err" 2>/dev/null; then
    if curl -fsS "${DYNU_CURL_V4[@]}" --http1.0 "${DYNU_CURL_NO_ALPN[@]}" -G "https://api.dynu.com/nic/update" \
        --data-urlencode "hostname=${DYNU_HOSTNAME}" \
        --data-urlencode "myip=${PUBLIC_IP}" \
        --data-urlencode "password=${DYNU_NIC_PASSWORD}" \
        >"$tmp" 2>"$err"; then
      cat "$tmp"
      return 0
    fi
  fi
  cat "$err" >&2
  return 1
}

DYNU_API_KEY="$(_dynu_trim "${DYNU_API_KEY:-}")"
DYNU_HOSTNAME="$(_dynu_trim "${DYNU_HOSTNAME:-}")"
DYNU_DNS_ID="$(_dynu_trim "${DYNU_DNS_ID:-}")"
DYNU_NIC_PASSWORD="$(_dynu_trim "${DYNU_NIC_PASSWORD:-}")"

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

update_via_nic() {
  require "DYNU_HOSTNAME"
  local RESP
  RESP="$(_run_nic_update)" || {
    echo "error: nic/update HTTP request failed" >&2
    return 1
  }
  read -r code _ <<<"$RESP"
  case "$code" in
    good|nochg)
      echo "dynu nic/update ok: script_rev=${SCRIPT_REV} hostname=${DYNU_HOSTNAME} ipv4=${PUBLIC_IP} response=${RESP}"
      return 0
      ;;
    *)
      echo "error: nic/update returned: ${RESP}" >&2
      echo "hint: DYNU_NIC_PASSWORD must be the IP-update password for this hostname in Dynu (plain or MD5 per Dynu docs)." >&2
      return 1
      ;;
  esac
}

# Argument: REST API base URL (e.g. https://api.dynu.com/v2). Uses DYNU_DNS_ID, DYNU_HOSTNAME, DYNU_API_KEY.
_dynu_resolve_dns_id() {
  local API_BASE="$1"
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
  )" || {
    echo "error: GET ${API_BASE}/dns failed (HTTP 505 is common for the list endpoint)." >&2
    echo "hint: set DYNU_DNS_ID=<numeric id> in /etc/default/dynu-ddns (from Dynu control panel)." >&2
    echo "hint: or set DYNU_NIC_PASSWORD + DYNU_HOSTNAME (IP Update Protocol fallback)." >&2
    return 1
  }
  echo "$raw" | python3 -c "
import json, sys
want = sys.argv[1].strip().lower()
data = json.load(sys.stdin)
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

update_via_rest() {
  require "DYNU_API_KEY"

  local API_BASE
  API_BASE="${DYNU_API_BASE:-https://api.dynu.com/v2}"
  API_BASE="$(_dynu_trim "$API_BASE")"
  API_BASE="${API_BASE%/}"
  if [[ "$API_BASE" != https://* ]]; then
    echo "error: DYNU_API_BASE must start with https:// (got: ${API_BASE})" >&2
    return 1
  fi

  local DNS_ID RESP BODY
  DNS_ID="$(_dynu_resolve_dns_id "$API_BASE")" || return 1

  export PUBLIC_IP
  BODY="$(python3 -c "import json, os; print(json.dumps({'ipv4Address': os.environ['PUBLIC_IP'], 'ipv4': True}))")"

  RESP="$(
    _run_dynu_curl -X POST "${API_BASE}/dns/${DNS_ID}" \
      -H "Expect:" \
      -H "accept: application/json" \
      -H "Content-Type: application/json" \
      -H "API-Key: ${DYNU_API_KEY}" \
      -d "$BODY"
  )" || {
    echo "error: POST ${API_BASE}/dns/${DNS_ID} failed." >&2
    echo "hint: set DYNU_DNS_ID if not already; add DYNU_NIC_PASSWORD + DYNU_HOSTNAME for automatic nic/update fallback." >&2
    return 1
  }

  echo "dynu v2 update ok: script_rev=${SCRIPT_REV} dns_id=${DNS_ID} ipv4=${PUBLIC_IP}"
  echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
  return 0
}

has_api=0
has_nic=0
[[ -n "$DYNU_API_KEY" ]] && has_api=1
[[ -n "$DYNU_NIC_PASSWORD" ]] && has_nic=1

if (( ! has_api && ! has_nic )); then
  echo "error: set DYNU_API_KEY and/or DYNU_NIC_PASSWORD in /etc/default/dynu-ddns" >&2
  exit 1
fi

# NIC-only: no API key, or user asked to skip REST while both are set
if (( has_nic )) && { (( ! has_api )) || _dynu_truthy "${DYNU_SKIP_REST:-}"; }; then
  update_via_nic || exit 1
  exit 0
fi

# REST (required here: has_api), with optional NIC fallback
if (( has_api )); then
  if update_via_rest; then
    exit 0
  fi
  if (( has_nic )); then
    echo "dynu: REST update failed; trying IP Update Protocol (nic/update)." >&2
    update_via_nic || exit 1
    exit 0
  fi
  exit 1
fi
