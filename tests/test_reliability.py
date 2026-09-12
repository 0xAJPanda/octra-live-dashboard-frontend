import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import build_reliability_snapshot
from reliability_collector import record_sample


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixture_reliability_history.json"


class ReliabilitySnapshotTests(unittest.TestCase):
    def test_healthy_evidence_reports_observed_continuity_without_claiming_uptime(self):
        snapshot = build_reliability_snapshot(
            FIXTURE,
            stale_after_seconds=7200,
            sample_interval_seconds=3600,
            now=datetime(2026, 9, 10, 6, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot["schema"], "octra-validator-reliability-v1")
        self.assertEqual(snapshot["state"], "healthy")
        self.assertEqual(snapshot["observed_health_pct"], 100.0)
        self.assertEqual(snapshot["voting_observed_pct"], 100.0)
        self.assertEqual(snapshot["coverage_pct"], 100.0)
        self.assertEqual(snapshot["current_healthy_streak_minutes"], 360)
        self.assertEqual(snapshot["restart_delta"], 0)
        self.assertIn("observation", snapshot["limitations"].lower())
        self.assertNotIn("uptime_pct", snapshot)

    def test_unhealthy_samples_and_restarts_are_visible(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["samples"][3].update({"healthy": False, "rpc_ready": False})
        payload["samples"][4]["restarts"] = 1
        payload["samples"][5]["restarts"] = 1
        payload["samples"][6]["restarts"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = build_reliability_snapshot(
                path,
                stale_after_seconds=7200,
                sample_interval_seconds=3600,
                now=datetime(2026, 9, 10, 6, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["state"], "degraded")
        self.assertAlmostEqual(snapshot["observed_health_pct"], 85.71, places=2)
        self.assertEqual(snapshot["longest_observed_unhealthy_minutes"], 60)
        self.assertEqual(snapshot["current_healthy_streak_minutes"], 120)
        self.assertEqual(snapshot["restart_delta"], 1)

    def test_sparse_or_stale_evidence_fails_closed(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["samples"] = payload["samples"][::2]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            sparse = build_reliability_snapshot(
                path,
                stale_after_seconds=7200,
                sample_interval_seconds=3600,
                now=datetime(2026, 9, 10, 6, 1, tzinfo=timezone.utc),
            )
            stale = build_reliability_snapshot(
                path,
                stale_after_seconds=60,
                sample_interval_seconds=3600,
                now=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(sparse["state"], "degraded")
        self.assertLess(sparse["coverage_pct"], 90)
        self.assertEqual(stale["state"], "stale")

    def test_current_unhealthy_sample_is_degraded_even_before_evidence_window_fills(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["samples"] = payload["samples"][:2]
        payload["samples"][-1].update({"healthy": False, "voting": False, "active": False})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = build_reliability_snapshot(
                path,
                stale_after_seconds=7200,
                sample_interval_seconds=3600,
                now=datetime(2026, 9, 10, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["state"], "degraded")
        self.assertIn("current", snapshot["message"].lower())


class ReliabilityCollectorTests(unittest.TestCase):
    def test_deployment_interval_and_collector_wiring_match_retention_contract(self):
        collector = (ROOT / "collector.sh").read_text(encoding="utf-8")
        timer = (ROOT / "deploy" / "octra-dashboard-collector.timer").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('python3 "$SCRIPT_DIR/reliability_collector.py"', collector)
        self.assertIn("OnUnitActiveSec=60s", timer)
        self.assertIn("reliability_collector.py", dockerfile)

    def test_collector_records_only_coarse_health_evidence_and_caps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "reliability-history.json"
            status.write_text(
                "process = online\n"
                "rpc = ready\n"
                "state_sync = verified\n"
                "voting = enabled\n"
                "validator_active = true\n"
                "epoch = 1500000\n"
                "restarts = 2\n"
                "address = octSecretAdjacentPublicIdentity\n"
                "private_key = never\n",
                encoding="utf-8",
            )
            for index in range(5):
                record_sample(status, history, observed_at=1_700_000_000 + index * 60, max_samples=3)
            payload = json.loads(history.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "octra-validator-reliability-history-v1")
        self.assertEqual(len(payload["samples"]), 3)
        self.assertTrue(payload["samples"][-1]["healthy"])
        self.assertEqual(payload["samples"][-1]["restarts"], 2)
        serialized = json.dumps(payload)
        self.assertNotIn("address", serialized)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("never", serialized)

    def test_collector_records_failed_health_without_rejecting_the_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "history.json"
            status.write_text(
                "process = offline\nrpc = unavailable\nstate_sync = verified\n"
                "voting = disabled\nvalidator_active = false\nepoch = 1\nrestarts = 4\n",
                encoding="utf-8",
            )
            record_sample(status, history, observed_at=1_700_000_000)
            sample = json.loads(history.read_text(encoding="utf-8"))["samples"][0]
        self.assertFalse(sample["healthy"])
        self.assertFalse(sample["online"])
        self.assertFalse(sample["rpc_ready"])
        self.assertFalse(sample["voting"])


if __name__ == "__main__":
    unittest.main()
