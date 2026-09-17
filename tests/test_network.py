import json
import tempfile
import time
import unittest
from pathlib import Path

from app import build_network_snapshot
from network_collector import build_public_network, resolve_local_address, update_history


LOCAL = "oct8mvdkX3babyBsrzHYUB1cSU9a79RTbHXi7nJNfHJnUmk"
REMOTE = "oct271U2WMjSWGRZSrKZVuC7YQgFypwP2pwwWPWkXN96Mfm"
SCHEDULED = "octScheduled111111111111111111111111111111111111111"


def proof():
    return {
        "chain_id": "octra-devnet-9871-cluster",
        "validator_set_hash": "a" * 64,
        "weighted": True,
        "total_weight": "3000000",
        "validators": [
            {"address": LOCAL, "pubkey": "must-not-leak", "weight": "2000000"},
            {"address": REMOTE, "pubkey": "must-not-leak", "weight": "1000000"},
        ],
        "scheduled": {
            "activate_epoch": 1500,
            "weighted": True,
            "validators": [
                {"address": LOCAL, "pubkey": "must-not-leak", "weight": "2000000"},
                {"address": SCHEDULED, "pubkey": "must-not-leak", "weight": "1000000"},
            ],
        },
        "config_hash": "must-not-cross-contract",
    }


class NetworkCollectorTests(unittest.TestCase):
    def test_explicit_public_local_address_overrides_status_file_read(self):
        self.assertEqual(resolve_local_address(LOCAL, Path("missing-status.txt")), LOCAL)
        self.assertEqual(resolve_local_address("not-an-octra-address", Path("missing-status.txt")), "")

    def test_history_tracks_set_continuity_without_calling_it_uptime(self):
        history = update_history({}, [LOCAL, REMOTE], "2026-09-01T20:00:00+00:00")
        history = update_history(history, [LOCAL], "2026-09-01T20:00:30+00:00")
        self.assertEqual(history["validators"][LOCAL]["continuity_pct"], 100.0)
        self.assertEqual(history["validators"][REMOTE]["continuity_pct"], 50.0)
        self.assertNotIn("uptime", json.dumps(history).lower())

    def test_public_network_is_allowlisted_and_marks_local_validator(self):
        history = update_history({}, [LOCAL, REMOTE], "2026-09-01T20:00:00+00:00")
        peers = {
            "round_peers": [
                {"validator_addr": LOCAL, "age_sec": 2.5, "epoch_id": 1499, "round": 0, "step": "prevote", "source": "hidden"}
            ],
            "p2p_diagnostics": {"peers": [{"addr": "192.0.2.10:19000"}]},
        }
        public = build_public_network(proof(), peers, history, LOCAL, "2026-09-01T20:00:00+00:00")
        self.assertEqual(public["summary"]["active_validators"], 2)
        self.assertEqual(public["summary"]["scheduled_validators"], 2)
        self.assertEqual(public["summary"]["total_weight"], 3000000)
        self.assertEqual(public["scheduled"]["activation_epoch"], 1500)
        ours = next(item for item in public["validators"] if item["address"] == LOCAL)
        self.assertTrue(ours["is_local"])
        self.assertTrue(ours["consensus_observed"])
        self.assertEqual(ours["weight_share_pct"], 66.6667)
        serialized = json.dumps(public)
        self.assertNotIn("pubkey", serialized)
        self.assertNotIn("192.0.2.10", serialized)
        self.assertNotIn("config_hash", serialized)

    def test_local_public_validator_is_retained_when_absent_from_the_current_set(self):
        history = update_history({}, [REMOTE], "2026-09-01T20:00:00+00:00")
        inactive = "octInactive11111111111111111111111111111111111"
        public = build_public_network(
            {"validators": [{"address": REMOTE, "weight": "1000000"}], "scheduled": {"validators": []}},
            {}, history, inactive, "2026-09-01T20:00:00+00:00",
        )
        ours = next(item for item in public["validators"] if item["address"] == inactive)
        self.assertTrue(ours["is_local"])
        self.assertFalse(ours["active"])
        self.assertFalse(ours["scheduled"])
        self.assertEqual(ours["weight"], 0)


class NetworkApiContractTests(unittest.TestCase):
    def test_api_revalidates_collector_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.json"
            payload = {
                "schema": "octra-public-validator-network-v1",
                "observed_at": "2026-09-01T20:00:00+00:00",
                "chain_id": "octra-devnet-9871-cluster",
                "validator_set_hash": "b" * 64,
                "summary": {"active_validators": 1, "scheduled_validators": 1, "total_weight": 1000000, "consensus_observed": 1},
                "scheduled": {"activation_epoch": 2000},
                "validators": [{
                    "address": LOCAL,
                    "weight": 1000000,
                    "weight_share_pct": 100.0,
                    "active": True,
                    "scheduled": True,
                    "is_local": True,
                    "consensus_observed": True,
                    "consensus_age_seconds": 1.2,
                    "continuity_pct": 100.0,
                    "first_observed_at": "2026-09-01T20:00:00+00:00",
                    "last_observed_at": "2026-09-01T20:00:00+00:00",
                    "private_key": "never",
                }],
                "private": "never",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = build_network_snapshot(path, stale_after_seconds=31_536_000)
        self.assertEqual(snapshot["summary"]["active_validators"], 1)
        self.assertEqual(len(snapshot["validators"]), 1)
        self.assertNotIn("private", snapshot)
        self.assertNotIn("private_key", snapshot["validators"][0])

    def test_stale_network_snapshot_is_marked_degraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.json"
            path.write_text(json.dumps({"schema": "octra-public-validator-network-v1", "validators": []}), encoding="utf-8")
            old = time.time() - 600
            import os
            os.utime(path, (old, old))
            snapshot = build_network_snapshot(path, stale_after_seconds=180)
        self.assertFalse(snapshot["fresh"])


if __name__ == "__main__":
    unittest.main()
