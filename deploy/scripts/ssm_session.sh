#!/usr/bin/env bash
# Start AWS Systems Manager Session Manager shell using credentials and region from backend/deploy/.env.
# Requires: AWS CLI + Session Manager plugin.
#
# Usage:
#   ./scripts/ssm_session.sh <instance-id>
# Env (from .env): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, optional AWS_SESSION_TOKEN,
#                  AWS_REGION or AWS_DEFAULT_REGION (if unset, uses region from config/aws-backend.json)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  echo "Usage: ${0##*/} <instance-id>" >&2
  echo "Loads AWS keys and region from $DEPLOY_DIR/.env" >&2
  echo "Set AWS_REGION or AWS_DEFAULT_REGION in .env, or region in config/aws-backend.json." >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

INSTANCE_ID="$1"

if [[ -f "$DEPLOY_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$DEPLOY_DIR/.env"
  set +a
fi

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  echo "error: set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in $DEPLOY_DIR/.env" >&2
  exit 1
fi

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$REGION" ]]; then
  BACKEND_CFG="$DEPLOY_DIR/config/aws-backend.json"
  if [[ -f "$BACKEND_CFG" ]] && command -v python3 >/dev/null 2>&1; then
    REGION="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('region') or '')" "$BACKEND_CFG")" || true
  fi
fi
if [[ -z "$REGION" || "$REGION" == "None" ]]; then
  echo "error: set AWS_REGION or AWS_DEFAULT_REGION in $DEPLOY_DIR/.env, or region in config/aws-backend.json" >&2
  exit 1
fi

command -v aws >/dev/null 2>&1 || {
  echo "error: aws CLI not found" >&2
  exit 1
}

command -v session-manager-plugin >/dev/null 2>&1 || {
  echo "error: Session Manager plugin not installed (required for aws ssm start-session)." >&2
  echo "  Ubuntu x86_64: curl -fsSL https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb -o /tmp/smp.deb && sudo dpkg -i /tmp/smp.deb" >&2
  echo "  Docs: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html" >&2
  exit 1
}

exec aws ssm start-session --region "$REGION" --target "$INSTANCE_ID"
