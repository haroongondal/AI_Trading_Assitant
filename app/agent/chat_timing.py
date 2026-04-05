"""UTC timestamp helper used by scheduler logs."""
from datetime import datetime, timezone


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
