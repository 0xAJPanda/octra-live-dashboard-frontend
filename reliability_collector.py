#!/usr/bin/env python3
"""Record bounded, coarse local validator reliability observations."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "octra-validator-reliability-history-v1"
LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
FIELDS = {"process", "rpc", "state_sync", "voting", "validator_active", "epoch", "restarts"}


def _status(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE.fullmatch(line.strip())
        if match and match.group(1) in FIELDS:
            values[match.group(1)] = match.group(2)
    return values


def _integer(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _history(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA or not isinstance(payload.get("samples"), list):
        return []
    return [item for item in payload["samples"] if isinstance(item, dict)]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_sample(
    status_path: Path,
    history_path: Path,
    *,
    observed_at: float | None = None,
    max_samples: int = 10_080,
) -> None:
    values = _status(status_path)
    epoch = _integer(values.get("epoch"))
    restarts = _integer(values.get("restarts"))
    if epoch is None or restarts is None:
        raise ValueError("status is missing non-negative epoch or restart count")

    online = values.get("process") == "online"
    rpc_ready = values.get("rpc") == "ready"
    synced = values.get("state_sync") == "verified"
    voting = values.get("voting", "").lower() in {"true", "enabled"}
    active = values.get("validator_active", "").lower() == "true"
    timestamp = datetime.fromtimestamp(observed_at, timezone.utc) if observed_at is not None else datetime.now(timezone.utc)
    sample = {
        "observed_at": timestamp.isoformat(),
        "healthy": online and rpc_ready and synced and voting and active,
        "online": online,
        "rpc_ready": rpc_ready,
        "voting": voting,
        "active": active,
        "epoch": epoch,
        "restarts": restarts,
    }
    samples = (_history(history_path) + [sample])[-max(1, max_samples):]
    _atomic_json(history_path, {"schema": SCHEMA, "samples": samples})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--history-file", type=Path, required=True)
    parser.add_argument("--max-samples", type=int, default=10_080)
    args = parser.parse_args()
    record_sample(args.status_file, args.history_file, max_samples=args.max_samples)


if __name__ == "__main__":
    main()
