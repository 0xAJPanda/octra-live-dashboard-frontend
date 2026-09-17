#!/usr/bin/env python3
"""Record bounded, restart-aware aggregate validator peer observations."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "octra-validator-peer-history-v1"
LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
FIELDS = {"p2p_connected", "consensus_peers", "restarts"}


def _integer(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _status(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE.fullmatch(line.strip())
        if match and match.group(1) in FIELDS:
            value = _integer(match.group(2))
            if value is not None:
                values[match.group(1)] = value
    return values


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
    if set(values) != FIELDS:
        raise ValueError("status is missing valid aggregate peer counts or restart count")
    timestamp = datetime.fromtimestamp(observed_at, timezone.utc) if observed_at is not None else datetime.now(timezone.utc)
    sample = {"observed_at": timestamp.isoformat(), **values}
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
