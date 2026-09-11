import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import build_storage_snapshot
from storage_collector import record_sample


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixture_storage_history.json"


class StorageRunwayTests(unittest.TestCase):
    def test_forecasts_runway_from_six_hours_or_more_of_growth(self):
        snapshot = build_storage_snapshot(
            FIXTURE,
            now=datetime(2026, 9, 10, 0, 2, tzinfo=timezone.utc),
            stale_after_seconds=900,
        )
        self.assertEqual(snapshot["schema"], "octra-storage-runway-v1")
        self.assertEqual(snapshot["state"], "healthy")
        self.assertTrue(snapshot["forecast_available"])
        self.assertAlmostEqual(snapshot["growth_gib_per_day"], 24.0, places=1)
        self.assertGreater(snapshot["days_to_reserve"], 30)
        self.assertEqual(snapshot["evidence"]["span_hours"], 24.0)

    def test_sparse_history_fails_closed_without_a_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps({
                "schema": "octra-storage-history-v1",
                "samples": [
                    {"observed_at": "2026-09-10T00:00:00Z", "used_bytes": 100, "free_bytes": 900},
                    {"observed_at": "2026-09-10T01:00:00Z", "used_bytes": 200, "free_bytes": 800},
                ],
            }), encoding="utf-8")
            snapshot = build_storage_snapshot(
                path,
                now=datetime(2026, 9, 10, 1, 1, tzinfo=timezone.utc),
                stale_after_seconds=900,
            )
        self.assertEqual(snapshot["state"], "insufficient_data")
        self.assertFalse(snapshot["forecast_available"])
        self.assertIsNone(snapshot["days_to_reserve"])

    def test_non_growth_is_reported_as_stable_not_infinite_runway(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps({
                "schema": "octra-storage-history-v1",
                "samples": [
                    {"observed_at": "2026-09-09T00:00:00Z", "used_bytes": 500, "free_bytes": 500},
                    {"observed_at": "2026-09-09T08:00:00Z", "used_bytes": 490, "free_bytes": 510},
                    {"observed_at": "2026-09-09T16:00:00Z", "used_bytes": 480, "free_bytes": 520},
                    {"observed_at": "2026-09-10T00:00:00Z", "used_bytes": 470, "free_bytes": 530},
                ],
            }), encoding="utf-8")
            snapshot = build_storage_snapshot(
                path,
                now=datetime(2026, 9, 10, 0, 1, tzinfo=timezone.utc),
                stale_after_seconds=900,
            )
        self.assertEqual(snapshot["state"], "stable")
        self.assertFalse(snapshot["forecast_available"])
        self.assertEqual(snapshot["growth_bytes_per_second"], 0)

    def test_stale_history_is_explicitly_degraded(self):
        snapshot = build_storage_snapshot(
            FIXTURE,
            now=datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc),
            stale_after_seconds=900,
        )
        self.assertEqual(snapshot["state"], "stale")
        self.assertFalse(snapshot["forecast_available"])


class StorageCollectorTests(unittest.TestCase):
    def test_collector_appends_allowlisted_sample_and_caps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "storage-history.json"
            status.write_text(
                "disk_used = 10.0 GiB\n"
                "disk_free = 90.0 GiB\n"
                "private_key = never\n"
                "node = private-host\n",
                encoding="utf-8",
            )
            for index in range(5):
                record_sample(status, history, observed_at=1_700_000_000 + index, max_samples=3)
            payload = json.loads(history.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "octra-storage-history-v1")
        self.assertEqual(len(payload["samples"]), 3)
        self.assertEqual(payload["samples"][-1]["used_bytes"], 10 * 1024**3)
        serialized = json.dumps(payload)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("private-host", serialized)

    def test_collector_rejects_incomplete_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "storage-history.json"
            status.write_text("disk_used = 10 GiB\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                record_sample(status, history, observed_at=1_700_000_000)
            self.assertFalse(history.exists())

    def test_collector_replaces_corrupt_history_with_a_safe_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "storage-history.json"
            status.write_text("disk_used = 1 TiB\ndisk_free = 512 GiB\n", encoding="utf-8")
            history.write_text("not json", encoding="utf-8")
            record_sample(status, history, observed_at=1_700_000_000)
            payload = json.loads(history.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["samples"]), 1)
        self.assertEqual(payload["samples"][0]["used_bytes"], 1024**4)


if __name__ == "__main__":
    unittest.main()
