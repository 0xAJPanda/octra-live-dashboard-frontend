#!/usr/bin/env python3
"""Collect strictly public Octra validator-set and participation telemetry."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ADDRESS = re.compile(r"^oct[A-Za-z0-9]{40,80}$")
SCHEMA = "octra-public-validator-network-v1"


def number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def update_history(history: dict[str, Any], active_addresses: list[str], observed_at: str) -> dict[str, Any]:
    validators = history.get("validators") if isinstance(history.get("validators"), dict) else {}
    active = {address for address in active_addresses if ADDRESS.fullmatch(address)}

    for address in set(validators) | active:
        raw = validators.get(address) if isinstance(validators.get(address), dict) else {}
        eligible = number(raw.get("eligible_samples")) + 1
        active_samples = number(raw.get("active_samples")) + (1 if address in active else 0)
        validators[address] = {
            "first_seen": raw.get("first_seen") or observed_at,
            "last_seen": observed_at if address in active else raw.get("last_seen"),
            "eligible_samples": eligible,
            "active_samples": active_samples,
            "continuity_pct": round(active_samples / eligible * 100, 2),
        }

    return {"schema": "octra-validator-history-v1", "validators": validators}


def validator_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, str) or not ADDRESS.fullmatch(address):
            continue
        weight = number(item.get("weight"), -1)
        if weight < 0:
            continue
        rows.append({"address": address, "weight": weight})
    return rows


def build_public_network(
    proof: dict[str, Any],
    peer_state: dict[str, Any],
    history: dict[str, Any],
    local_address: str,
    observed_at: str,
) -> dict[str, Any]:
    active = validator_rows(proof.get("validators"))
    scheduled_raw = proof.get("scheduled") if isinstance(proof.get("scheduled"), dict) else {}
    scheduled = validator_rows(scheduled_raw.get("validators"))
    active_by_address = {item["address"]: item for item in active}
    scheduled_by_address = {item["address"]: item for item in scheduled}
    total_weight = sum(item["weight"] for item in active)

    consensus: dict[str, dict[str, Any]] = {}
    round_peers = peer_state.get("round_peers") if isinstance(peer_state, dict) else []
    if isinstance(round_peers, list):
        for item in round_peers:
            if not isinstance(item, dict):
                continue
            address = item.get("validator_addr")
            if not isinstance(address, str) or not ADDRESS.fullmatch(address):
                continue
            age = item.get("age_sec")
            consensus[address] = {
                "consensus_observed": True,
                "consensus_age_seconds": round(float(age), 2) if isinstance(age, (int, float)) and age >= 0 else None,
            }

    history_rows = history.get("validators") if isinstance(history.get("validators"), dict) else {}
    rows: list[dict[str, Any]] = []
    for address in set(active_by_address) | set(scheduled_by_address):
        active_row = active_by_address.get(address)
        scheduled_row = scheduled_by_address.get(address)
        weight = (active_row or scheduled_row or {}).get("weight", 0)
        history_row = history_rows.get(address) if isinstance(history_rows.get(address), dict) else {}
        seen = consensus.get(address, {})
        rows.append({
            "address": address,
            "weight": weight,
            "weight_share_pct": round(weight / total_weight * 100, 4) if active_row and total_weight else 0.0,
            "active": active_row is not None,
            "scheduled": scheduled_row is not None,
            "is_local": address == local_address,
            "consensus_observed": seen.get("consensus_observed", False),
            "consensus_age_seconds": seen.get("consensus_age_seconds"),
            "continuity_pct": history_row.get("continuity_pct"),
            "first_observed_at": history_row.get("first_seen"),
            "last_observed_at": history_row.get("last_seen"),
        })
    rows.sort(key=lambda item: (not item["is_local"], not item["active"], -item["weight"], item["address"]))

    chain_id = proof.get("chain_id") if isinstance(proof.get("chain_id"), str) else None
    set_hash = proof.get("validator_set_hash")
    return {
        "schema": SCHEMA,
        "observed_at": observed_at,
        "chain_id": chain_id,
        "validator_set_hash": set_hash if isinstance(set_hash, str) and re.fullmatch(r"[0-9a-f]{64}", set_hash) else None,
        "summary": {
            "active_validators": len(active),
            "scheduled_validators": len(scheduled),
            "total_weight": total_weight,
            "consensus_observed": sum(1 for row in rows if row["active"] and row["consensus_observed"]),
        },
        "scheduled": {"activation_epoch": number(scheduled_raw.get("activate_epoch"), 0) or None},
        "validators": rows,
        "limitations": {
            "remote_uptime": "not exposed by the public validator-set RPC",
            "continuity": "local observation of active-set membership, not host uptime",
            "consensus_observed": "recent consensus evidence seen by this node, not an availability guarantee",
        },
    }


def rpc_call(url: str, method: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("RPC URL must be loopback HTTP")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": []}).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("error") is not None or not isinstance(payload.get("result"), dict):
        raise RuntimeError(f"RPC method failed: {method}")
    return payload["result"]


def atomic_json(path: Path, payload: dict[str, Any], mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}


def local_address(status_path: Path) -> str:
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return ""
    for line in lines:
        if line.startswith("address = "):
            candidate = line.partition("=")[2].strip()
            return candidate if ADDRESS.fullmatch(candidate) else ""
    return ""


def resolve_local_address(explicit_address: str, status_path: Path) -> str:
    """Accept only an explicit public address; otherwise read the allowlisted status line."""
    return explicit_address if ADDRESS.fullmatch(explicit_address) else local_address(status_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default="http://127.0.0.1:29080/rpc")
    parser.add_argument("--status-file", type=Path, default=Path("/data/status.txt"))
    parser.add_argument("--local-address", default="")
    parser.add_argument("--network-file", type=Path, required=True)
    parser.add_argument("--history-file", type=Path, required=True)
    args = parser.parse_args()

    observed_at = datetime.now(timezone.utc).isoformat()
    proof = rpc_call(args.rpc_url, "octra_validatorSetProof")
    peers = rpc_call(args.rpc_url, "octra_consensusPeerStates")
    active_addresses = [item["address"] for item in validator_rows(proof.get("validators"))]
    history = update_history(load_json(args.history_file), active_addresses, observed_at)
    public = build_public_network(proof, peers, history, resolve_local_address(args.local_address, args.status_file), observed_at)
    atomic_json(args.history_file, history, 0o600)
    atomic_json(args.network_file, public, 0o644)


if __name__ == "__main__":
    main()
