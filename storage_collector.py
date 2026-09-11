#!/usr/bin/env python3
"""Append sanitized Octra disk capacity samples to a bounded JSON history."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "octra-storage-history-v1"
SIZE = re.compile(r"^disk_(used|free)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KiB|MiB|GiB|TiB)\s*$", re.I)
UNITS = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}


def read_capacity(status_path: Path) -> tuple[int, int]:
    capacity: dict[str, int] = {}
    for line in status_path.read_text(encoding="utf-8").splitlines():
        match = SIZE.fullmatch(line.strip())
        if match:
            capacity[match.group(1).lower()] = round(float(match.group(2)) * UNITS[match.group(3).lower()])
    if set(capacity) != {"used", "free"} or capacity["used"] < 0 or capacity["free"] < 0:
        raise ValueError("complete non-negative disk capacity is required")
    return capacity["used"], capacity["free"]


def _load_samples(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return []
    return payload.get("samples", []) if isinstance(payload.get("samples"), list) else []


def record_sample(
    status_path: Path,
    history_path: Path,
    *,
    observed_at: float | None = None,
    max_samples: int = 20_160,
) -> None:
    used, free = read_capacity(status_path)
    timestamp = time.time() if observed_at is None else observed_at
    sample = {
        "observed_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
        "used_bytes": used,
        "free_bytes": free,
    }
    samples = [item for item in _load_samples(history_path) if isinstance(item, dict)]
    samples.append(sample)
    payload = {"schema": SCHEMA, "samples": samples[-max(1, max_samples):]}

    history_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".storage-history.", dir=history_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(payload, temporary, separators=(",", ":"))
            temporary.write("\n")
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, history_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--history-file", type=Path, required=True)
    parser.add_argument("--max-samples", type=int, default=20_160)
    args = parser.parse_args()
    record_sample(args.status_file, args.history_file, max_samples=args.max_samples)


if __name__ == "__main__":
    main()
