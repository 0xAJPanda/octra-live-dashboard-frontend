#!/usr/bin/env python3
"""Read-only Octra validator dashboard with a deliberately small data surface."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


STATUS_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
INTEGER = re.compile(r"^-?\d+$")
FLOAT = re.compile(r"^-?(?:\d+\.\d*|\d*\.\d+)$")
SIZE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(B|KiB|MiB|GiB|TiB)$", re.I)
PERCENT = re.compile(r"^([0-9]+(?:\.[0-9]+)?)%$")

# Only these fields can cross the host/container boundary into the browser.
PUBLIC_FIELDS = {
    "address",
    "role",
    "process",
    "restarts",
    "rpc",
    "state_sync",
    "epoch",
    "head_epoch",
    "txid_hi",
    "accounts",
    "voting",
    "voting_reason",
    "round",
    "round_step",
    "round_peers",
    "p2p_connected",
    "p2p_known",
    "consensus_peers",
    "peer_max_lag",
    "validator_active",
    "validator_scheduled",
    "validator_activation_epoch",
    "validator_next_set_epoch",
    "validator_enrollment",
    "validator_bond",
    "validator_bonded_epoch",
    "validator_ready_epoch",
    "cpu",
    "rss",
    "disk_used",
    "disk_free",
    "dashboard_memory_total_bytes",
    "dashboard_memory_available_bytes",
    "dashboard_load_1m",
    "dashboard_host_uptime_seconds",
}

NETWORK_SCHEMA = "octra-public-validator-network-v1"
NETWORK_VALIDATOR_FIELDS = {
    "address", "weight", "weight_share_pct", "active", "scheduled", "is_local",
    "consensus_observed", "consensus_age_seconds", "continuity_pct",
    "first_observed_at", "last_observed_at",
}
PUBLIC_VALIDATOR_ADDRESS = re.compile(r"^oct[A-Za-z0-9]{40,80}$")

STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/static/logo.svg": "static/logo.svg",
    "/static/script.js": "static/script.js",
    "/static/style.css": "static/style.css",
}


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value in {"None", "null"}:
        return None
    if INTEGER.fullmatch(value):
        return int(value)
    if FLOAT.fullmatch(value):
        return float(value)
    return value


def parse_status(output: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for line in output.splitlines():
        match = STATUS_LINE.fullmatch(line.strip())
        if match and match.group(1) in PUBLIC_FIELDS:
            parsed[match.group(1)] = parse_scalar(match.group(2))
    return parsed


def parse_size(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = SIZE.fullmatch(value.strip())
    if not match:
        return None
    units = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}
    return round(float(match.group(1)) * units[match.group(2).lower()])


def parse_percent(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = PERCENT.fullmatch(value.strip())
    return float(match.group(1)) if match else None


def ratio_percent(used: int | None, total: int | None) -> float | None:
    if used is None or total in {None, 0}:
        return None
    return round(used / total * 100, 2)


def is_enabled(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "enabled")


def build_snapshot(status_path: Path, stale_after_seconds: int) -> dict[str, Any]:
    modified_at = status_path.stat().st_mtime
    age_seconds = max(0, int(time.time() - modified_at))
    status = parse_status(status_path.read_text(encoding="utf-8"))

    issues: list[str] = []
    warnings: list[str] = []
    if status.get("process") != "online":
        issues.append("validator process is not online")
    if status.get("rpc") != "ready":
        issues.append("validator RPC is not ready")
    if status.get("state_sync") not in {None, "verified"}:
        issues.append("state sync is not verified")
    if age_seconds > stale_after_seconds:
        warnings.append("telemetry is stale")

    epoch = status.get("epoch")
    head_epoch = status.get("head_epoch")
    head_gap = epoch - head_epoch if isinstance(epoch, int) and isinstance(head_epoch, int) else None
    if head_gap is not None and head_gap > 2:
        warnings.append("validator is behind the network head")

    disk_used = parse_size(status.get("disk_used"))
    disk_free = parse_size(status.get("disk_free"))
    disk_total = disk_used + disk_free if disk_used is not None and disk_free is not None else None
    memory_total = status.get("dashboard_memory_total_bytes")
    memory_available = status.get("dashboard_memory_available_bytes")
    memory_used = (
        memory_total - memory_available
        if isinstance(memory_total, int) and isinstance(memory_available, int)
        else None
    )

    active = status.get("validator_active") is True
    scheduled = status.get("validator_scheduled") is True
    healthy = not issues and age_seconds <= stale_after_seconds

    return {
        "online": healthy,
        "observed_at": datetime.fromtimestamp(modified_at, timezone.utc).isoformat(),
        "age_seconds": age_seconds,
        "health": {"issues": issues, "warnings": warnings, "head_gap": head_gap},
        "status": {
            "validator": status.get("address"),
            "role": status.get("role"),
            "process": status.get("process"),
            "rpc": status.get("rpc"),
            "voting": status.get("voting"),
            "voting_reason": status.get("voting_reason"),
            "current_epoch": epoch,
            "head_epoch": head_epoch,
            "total_accounts": status.get("accounts"),
            "txid_hi": status.get("txid_hi"),
            "restarts": status.get("restarts"),
        },
        "validator": {
            "active": active,
            "scheduled": scheduled,
            "activation_epoch": status.get("validator_activation_epoch"),
            "next_set_epoch": status.get("validator_next_set_epoch"),
        },
        "enrollment": {
            "state": status.get("validator_enrollment"),
            "bond": status.get("validator_bond"),
            "bonded_epoch": status.get("validator_bonded_epoch"),
            "ready_epoch": status.get("validator_ready_epoch"),
        },
        "host": {
            "cpu_used_pct": parse_percent(status.get("cpu")),
            "memory_used_pct": ratio_percent(memory_used, memory_total),
            "memory_used_bytes": memory_used,
            "memory_total_bytes": memory_total,
            "validator_rss_bytes": parse_size(status.get("rss")),
            "disk_used_pct": ratio_percent(disk_used, disk_total),
            "disk_used_bytes": disk_used,
            "disk_total_bytes": disk_total,
            "load_1m": status.get("dashboard_load_1m"),
            "uptime_seconds": status.get("dashboard_host_uptime_seconds"),
        },
        "peers": {
            "voting": is_enabled(status.get("voting")),
            "p2p_connected": status.get("p2p_connected"),
            "p2p_known": status.get("p2p_known"),
            "consensus_peers": status.get("consensus_peers"),
            "peer_max_lag": status.get("peer_max_lag"),
            "round_state": {"round": status.get("round"), "step": status.get("round_step")},
            "round_peers_count": status.get("round_peers"),
        },
    }


def build_network_snapshot(network_path: Path, stale_after_seconds: int) -> dict[str, Any]:
    modified_at = network_path.stat().st_mtime
    age_seconds = max(0, int(time.time() - modified_at))
    raw = json.loads(network_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != NETWORK_SCHEMA:
        raise ValueError("unsupported network telemetry schema")

    raw_summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    summary = {
        key: raw_summary.get(key)
        for key in ("active_validators", "scheduled_validators", "total_weight", "consensus_observed")
        if isinstance(raw_summary.get(key), int) and raw_summary.get(key) >= 0
    }
    raw_scheduled = raw.get("scheduled") if isinstance(raw.get("scheduled"), dict) else {}
    activation = raw_scheduled.get("activation_epoch")
    validators: list[dict[str, Any]] = []
    for item in raw.get("validators", [])[:500] if isinstance(raw.get("validators"), list) else []:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, str) or not re.fullmatch(r"oct[A-Za-z0-9]{40,80}", address):
            continue
        validators.append({key: item.get(key) for key in NETWORK_VALIDATOR_FIELDS if key in item})

    return {
        "schema": NETWORK_SCHEMA,
        "fresh": age_seconds <= stale_after_seconds,
        "age_seconds": age_seconds,
        "observed_at": raw.get("observed_at") if isinstance(raw.get("observed_at"), str) else None,
        "chain_id": raw.get("chain_id") if isinstance(raw.get("chain_id"), str) else None,
        "validator_set_hash": raw.get("validator_set_hash") if isinstance(raw.get("validator_set_hash"), str) else None,
        "summary": summary,
        "scheduled": {"activation_epoch": activation if isinstance(activation, int) else None},
        "validators": validators,
        "limitations": {
            "remote_uptime": "not exposed by the public validator-set RPC",
            "continuity": "local observation of active-set membership, not host uptime",
            "consensus_observed": "recent consensus evidence seen by this node, not an availability guarantee",
        },
    }


def build_validator_snapshot(network_path: Path, stale_after_seconds: int, address: str) -> dict[str, Any] | None:
    """Return one already-allowlisted public validator record, never collector internals."""
    if not PUBLIC_VALIDATOR_ADDRESS.fullmatch(address):
        return None
    network = build_network_snapshot(network_path, stale_after_seconds)
    validator = next((item for item in network["validators"] if item.get("address") == address), None)
    if validator is None:
        return None
    return {
        "schema": NETWORK_SCHEMA,
        "fresh": network["fresh"],
        "age_seconds": network["age_seconds"],
        "observed_at": network["observed_at"],
        "chain_id": network["chain_id"],
        "scheduled": network["scheduled"],
        "validator": validator,
        "limitations": network["limitations"],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "OctraDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/snapshot":
            self._serve_snapshot()
            return
        if path == "/api/network":
            self._serve_network()
            return
        if path.startswith("/api/validators/"):
            self._serve_validator(path.removeprefix("/api/validators/"))
            return
        if path == "/healthz":
            self._send(200, b"ok\n", "text/plain; charset=utf-8", no_store=True)
            return
        filename = STATIC_FILES.get(path)
        if filename is None and path.startswith("/validator/") and PUBLIC_VALIDATOR_ADDRESS.fullmatch(path.removeprefix("/validator/")):
            filename = "index.html"
        if filename is None:
            self._send(404, b"not found\n", "text/plain; charset=utf-8", no_store=True)
            return
        file_path = self.server.project_dir / filename
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self._send(200, file_path.read_bytes(), content_type)

    def _serve_snapshot(self) -> None:
        try:
            payload = build_snapshot(self.server.status_path, self.server.stale_after_seconds)
            self._send(200, json.dumps(payload, separators=(",", ":")).encode(), "application/json", no_store=True)
        except (FileNotFoundError, OSError, UnicodeError) as error:
            body = json.dumps({"online": False, "error": type(error).__name__}).encode()
            self._send(503, body, "application/json", no_store=True)

    def _serve_network(self) -> None:
        try:
            payload = build_network_snapshot(self.server.network_path, self.server.stale_after_seconds)
            self._send(200, json.dumps(payload, separators=(",", ":")).encode(), "application/json", no_store=True)
        except (FileNotFoundError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            body = json.dumps({"fresh": False, "error": type(error).__name__}).encode()
            self._send(503, body, "application/json", no_store=True)

    def _serve_validator(self, address: str) -> None:
        try:
            payload = build_validator_snapshot(self.server.network_path, self.server.stale_after_seconds, address)
            if payload is None:
                self._send(404, b'{"error":"not found"}', "application/json", no_store=True)
                return
            self._send(200, json.dumps(payload, separators=(",", ":")).encode(), "application/json", no_store=True)
        except (FileNotFoundError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            body = json.dumps({"fresh": False, "error": type(error).__name__}).encode()
            self._send(503, body, "application/json", no_store=True)

    def _send(self, code: int, body: bytes, content_type: str, *, no_store: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--status-file", type=Path, default=Path("/data/status.txt"))
    parser.add_argument("--network-file", type=Path, default=Path("/data/network.json"))
    parser.add_argument("--stale-after", type=int, default=180)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    server.status_path = args.status_file
    server.network_path = args.network_file
    server.stale_after_seconds = args.stale_after
    server.project_dir = Path(__file__).resolve().parent
    print(f"Octra dashboard listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
