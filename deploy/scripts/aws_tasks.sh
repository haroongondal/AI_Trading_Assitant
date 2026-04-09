#!/usr/bin/env bash
# AWS CLI helper for the two-instance deploy (API + Ollama).
# Loads backend/deploy/.env if present (AWS_ACCESS_KEY_ID, etc.).
# Reads region and Name tags from config/aws-backend.json and config/aws-ollama.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_CFG="$DEPLOY_DIR/config/aws-backend.json"
OLLAMA_CFG="$DEPLOY_DIR/config/aws-ollama.json"

if [[ -f "$DEPLOY_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$DEPLOY_DIR/.env"
  set +a
fi

require_aws() {
  command -v aws >/dev/null 2>&1 || {
    echo "error: aws CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" >&2
    exit 1
  }
}

require_python() {
  command -v python3 >/dev/null 2>&1 || {
    echo "error: python3 required to read JSON config" >&2
    exit 1
  }
}

json_get() {
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else ''))" "$@"
}

load_config() {
  require_python
  if [[ ! -f "$BACKEND_CFG" ]]; then
    echo "error: missing $BACKEND_CFG" >&2
    exit 1
  fi
  REGION="$(json_get "$BACKEND_CFG" region)"
  BACKEND_NAME="$(json_get "$BACKEND_CFG" instance_name)"
  BACKEND_SG_NAME="$(json_get "$BACKEND_CFG" security_group_name)"
  if [[ -z "${BACKEND_SG_NAME:-}" || "$BACKEND_SG_NAME" == "None" ]]; then
    BACKEND_SG_NAME="ai-trading-backend-sg"
  fi
  if [[ -f "$OLLAMA_CFG" ]]; then
    OLLAMA_NAME="$(json_get "$OLLAMA_CFG" instance_name)"
  else
    OLLAMA_NAME="ai-trading-ollama"
  fi
  if [[ -z "${REGION:-}" || "$REGION" == "None" ]]; then
    echo "error: could not read region from $BACKEND_CFG" >&2
    exit 1
  fi
  export AWS_DEFAULT_REGION="$REGION"
}

# Query: one line per instance matching Name tag (non-terminated).
describe_by_name() {
  local name="$1"
  aws ec2 describe-instances \
    --region "$REGION" \
    --filters \
      "Name=tag:Name,Values=$name" \
      "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name,Priv:PrivateIpAddress,Pub:PublicIpAddress,Sg:SecurityGroups[0].GroupId}' \
    --output json
}

print_status() {
  require_aws
  load_config
  echo "Region: $REGION"
  echo ""
  echo "=== Backend ($BACKEND_NAME) ==="
  describe_by_name "$BACKEND_NAME" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
if not rows:
    print('  (no instance found)')
else:
    for r in rows:
        print(f\"  InstanceId:   {r['Id']}\")
        print(f\"  State:        {r['State']}\")
        print(f\"  Private IP:   {r.get('Priv') or 'n/a'}\")
        print(f\"  Public IP:    {r.get('Pub') or 'n/a'}\")
        print(f\"  Primary SG:   {r.get('Sg') or 'n/a'}\")
        print('')
"
  echo "=== Ollama ($OLLAMA_NAME) ==="
  describe_by_name "$OLLAMA_NAME" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
if not rows:
    print('  (no instance found)')
else:
    for r in rows:
        print(f\"  InstanceId:   {r['Id']}\")
        print(f\"  State:        {r['State']}\")
        print(f\"  Private IP:   {r.get('Priv') or 'n/a'}\")
        print(f\"  Public IP:    {r.get('Pub') or 'n/a'}\")
        print(f\"  Primary SG:   {r.get('Sg') or 'n/a'}\")
        print('')
"
  OLLAMA_PRIV=$(describe_by_name "$OLLAMA_NAME" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
for r in rows:
    if r.get('State')=='running' and r.get('Priv'):
        print(r['Priv'])
        break
" || true)
  if [[ -n "${OLLAMA_PRIV:-}" ]]; then
    echo "=== Suggested backend .env (Ollama in same VPC) ==="
    echo "OLLAMA_BASE_URL=http://${OLLAMA_PRIV}:11434"
    echo ""
  fi
}

print_ssm_commands() {
  require_aws
  load_config
  BID=$(describe_by_name "$BACKEND_NAME" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r[0]['Id'] if r else '')")
  OID=$(describe_by_name "$OLLAMA_NAME" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r[0]['Id'] if r else '')")
  echo "Run these on your computer (Session Manager plugin required):"
  echo ""
  if [[ -n "$BID" ]]; then
    echo "  # API backend"
    echo "  aws ssm start-session --region \"$REGION\" --target \"$BID\""
  else
    echo "  # API backend: (no instance found for tag Name=$BACKEND_NAME)"
  fi
  echo ""
  if [[ -n "$OID" ]]; then
    echo "  # Ollama host"
    echo "  aws ssm start-session --region \"$REGION\" --target \"$OID\""
  else
    echo "  # Ollama host: (no instance found for tag Name=$OLLAMA_NAME)"
  fi
  echo ""
}

backend_sg() {
  require_aws
  load_config
  aws ec2 describe-security-groups \
    --region "$REGION" \
    --filters "Name=group-name,Values=$BACKEND_SG_NAME" \
    --query 'SecurityGroups[0].GroupId' \
    --output text 2>/dev/null | grep -E '^sg-' || {
    echo "error: security group $BACKEND_SG_NAME not found in $REGION" >&2
    exit 1
  }
}

ssm_ping() {
  require_aws
  load_config
  for name in "$BACKEND_NAME" "$OLLAMA_NAME"; do
    iid=$(describe_by_name "$name" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r[0]['Id'] if r else '')")
    if [[ -z "$iid" ]]; then
      echo "$name: no instance"
      continue
    fi
    ping=$(aws ssm describe-instance-information \
      --region "$REGION" \
      --filters "Key=InstanceIds,Values=$iid" \
      --query 'InstanceInformationList[0].PingStatus' \
      --output text 2>/dev/null || echo "Unknown")
    echo "$name ($iid): SSM PingStatus=$ping"
  done
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  status          Show both instances (IDs, state, IPs, primary SG) and OLLAMA_BASE_URL hint.
  ssm             Print ready-to-run aws ssm start-session commands.
  ssm-ping        Show SSM agent reachability (Online / etc.).
  backend-sg      Print API security group id from config (for aws-ollama.json).
  help            This message.

Config: $BACKEND_CFG, optional $OLLAMA_CFG
Credentials: export AWS_* or source $DEPLOY_DIR/.env
EOF
}

cmd="${1:-status}"
case "$cmd" in
  status|"") print_status ;;
  ssm) print_ssm_commands ;;
  ssm-ping) ssm_ping ;;
  backend-sg) backend_sg ;;
  help|-h|--help) usage ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
