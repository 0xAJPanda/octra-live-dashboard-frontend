import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import build_memory_snapshot
from memory_collector import record_sample


ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2
GIB = 1024**3


def write_history(path: Path, samples: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema": "octra-validator-memory-history-v1", "samples": samples}),
        encoding="utf-8",
    )


def sample(minute: int, rss_gib: float, available_gib: float, *, restarts: int = 1) -> dict:
    return {
        "observed_at": f"2026-09-16T0{minute // 60}:{minute % 60:02d}:00+00:00",
        "rss_bytes": round(rss_gib * GIB),
        "host_total_bytes": 32 * GIB,
        "host_available_bytes": round(available_gib * GIB),
        "restarts": restarts,
    }


class MemorySnapshotTests(unittest.TestCase):
    def test_sustained_growth_forecasts_time_to_protected_host_reserve(self):
        samples = [sample(index * 10, 4 + index * 0.25, 20 - index * 0.25) for index in range(7)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            write_history(path, samples)
            snapshot = build_memory_snapshot(
                path,
                stale_after_seconds=900,
                sample_interval_seconds=600,
                now=datetime(2026, 9, 16, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["schema"], "octra-validator-memory-v1")
        self.assertEqual(snapshot["state"], "warning")
        self.assertTrue(snapshot["forecast_available"])
        self.assertAlmostEqual(snapshot["growth_mib_per_hour"], 1536.0, places=1)
        self.assertAlmostEqual(snapshot["hours_to_reserve"], 9.13, places=1)
        self.assertEqual(snapshot["evidence"]["samples"], 7)
        self.assertNotIn('"samples": [', json.dumps(snapshot))

    def test_restart_boundary_prevents_pre_restart_drop_from_hiding_new_growth(self):
        samples = [
            sample(0, 11.0, 12.0, restarts=0),
            sample(10, 11.2, 11.8, restarts=0),
            sample(20, 4.0, 20.0, restarts=1),
            sample(30, 4.2, 19.8, restarts=1),
            sample(40, 4.4, 19.6, restarts=1),
            sample(50, 4.6, 19.4, restarts=1),
            sample(60, 4.8, 19.2, restarts=1),
            sample(70, 5.0, 19.0, restarts=1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            write_history(path, samples)
            snapshot = build_memory_snapshot(
                path,
                stale_after_seconds=900,
                sample_interval_seconds=600,
                now=datetime(2026, 9, 16, 1, 11, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["evidence"]["samples"], 6)
        self.assertEqual(snapshot["evidence"]["restart_generation"], 1)
        self.assertGreater(snapshot["growth_mib_per_hour"], 1000)
        self.assertIn("restart", snapshot["message"].lower())

    def test_flat_growth_is_healthy_without_inventing_a_deadline(self):
        samples = [sample(index * 10, 4.0 + index * 0.001, 20.0) for index in range(7)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            write_history(path, samples)
            snapshot = build_memory_snapshot(
                path,
                stale_after_seconds=900,
                sample_interval_seconds=600,
                now=datetime(2026, 9, 16, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["state"], "healthy")
        self.assertFalse(snapshot["forecast_available"])
        self.assertEqual(snapshot["growth_mib_per_hour"], 0.0)
        self.assertIsNone(snapshot["hours_to_reserve"])

    def test_sparse_and_stale_evidence_fail_closed(self):
        samples = [sample(0, 4.0, 20.0), sample(30, 5.0, 19.0)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            write_history(path, samples)
            sparse = build_memory_snapshot(
                path,
                stale_after_seconds=3600,
                sample_interval_seconds=600,
                now=datetime(2026, 9, 16, 0, 31, tzinfo=timezone.utc),
            )
            stale = build_memory_snapshot(
                path,
                stale_after_seconds=60,
                sample_interval_seconds=600,
                now=datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(sparse["state"], "collecting")
        self.assertEqual(stale["state"], "stale")


class MemoryCollectorTests(unittest.TestCase):
    def test_collector_stores_only_memory_evidence_and_caps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "memory-history.json"
            status.write_text(
                "rss = 4096.0 MiB\n"
                f"dashboard_memory_total_bytes = {32 * GIB}\n"
                f"dashboard_memory_available_bytes = {20 * GIB}\n"
                "restarts = 2\n"
                "address = octSecretAdjacentPublicIdentity\n"
                "private_key = never\n",
                encoding="utf-8",
            )
            for index in range(5):
                record_sample(status, history, observed_at=1_700_000_000 + index * 60, max_samples=3)
            payload = json.loads(history.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "octra-validator-memory-history-v1")
        self.assertEqual(len(payload["samples"]), 3)
        self.assertEqual(payload["samples"][-1]["rss_bytes"], 4096 * MIB)
        serialized = json.dumps(payload)
        self.assertNotIn("address", serialized)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("never", serialized)

    def test_memory_data_is_not_wired_into_the_public_deployment(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertNotIn("--memory-history-file", compose)
        self.assertNotIn('id="memory-trend-state"', html)
        self.assertNotIn("/api/memory", script)


if __name__ == "__main__":
    unittest.main()
