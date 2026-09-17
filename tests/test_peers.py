import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import build_peer_snapshot
from peer_collector import record_sample


def write_history(path: Path, rows: list[tuple[int, int, int, int]], *, start: datetime) -> None:
    samples = [
        {
            "observed_at": (start + timedelta(minutes=offset)).isoformat(),
            "p2p_connected": p2p,
            "consensus_peers": consensus,
            "restarts": restarts,
        }
        for offset, p2p, consensus, restarts in rows
    ]
    path.write_text(
        json.dumps({"schema": "octra-validator-peer-history-v1", "samples": samples}),
        encoding="utf-8",
    )


class PeerSnapshotTests(unittest.TestCase):
    def test_stable_peer_counts_are_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            start = datetime(2026, 9, 17, tzinfo=timezone.utc)
            rows = [(minute, 38 + minute % 3, 31 + minute % 2, 0) for minute in range(0, 61, 5)]
            write_history(path, rows, start=start)
            snapshot = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=61),
            )

        self.assertEqual(snapshot["schema"], "octra-validator-peer-stability-v1")
        self.assertEqual(snapshot["state"], "healthy")
        self.assertEqual(snapshot["current"]["p2p_connected"], 38)
        self.assertEqual(snapshot["current"]["consensus_peers"], 31)
        self.assertEqual(snapshot["zero_peer_observations"], 0)
        self.assertGreaterEqual(snapshot["floor"]["consensus_peers"], 31)

    def test_current_isolation_is_critical_even_before_full_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            start = datetime(2026, 9, 17, tzinfo=timezone.utc)
            rows = [(0, 34, 28, 0), (5, 0, 0, 0)]
            write_history(path, rows, start=start)
            snapshot = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=6),
            )

        self.assertEqual(snapshot["state"], "critical")
        self.assertIn("currently isolated", snapshot["message"])

    def test_transient_zero_after_restart_is_reported_as_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            start = datetime(2026, 9, 17, tzinfo=timezone.utc)
            counts = [(34, 28), (0, 0), (8, 6), (21, 17), (31, 26), (36, 30), (38, 31)]
            rows = [(index * 5, p2p, consensus, 1) for index, (p2p, consensus) in enumerate(counts)]
            write_history(path, rows, start=start)
            snapshot = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=31),
            )

        self.assertEqual(snapshot["state"], "warning")
        self.assertEqual(snapshot["zero_peer_observations"], 1)
        self.assertIn("recovered", snapshot["message"])

    def test_restart_generation_discards_old_disconnects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            start = datetime(2026, 9, 17, tzinfo=timezone.utc)
            old = [(0, 0, 0, 0), (5, 0, 0, 0)]
            current = [(10 + minute, 35, 29, 1) for minute in range(0, 31, 5)]
            write_history(path, old + current, start=start)
            snapshot = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=41),
            )

        self.assertEqual(snapshot["state"], "healthy")
        self.assertEqual(snapshot["zero_peer_observations"], 0)
        self.assertEqual(snapshot["evidence"]["restart_generation"], 1)

    def test_stale_or_sparse_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            start = datetime(2026, 9, 17, tzinfo=timezone.utc)
            write_history(path, [(0, 30, 25, 0), (30, 31, 26, 0)], start=start)
            sparse = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=31),
            )
            stale = build_peer_snapshot(
                path,
                stale_after_seconds=300,
                sample_interval_seconds=300,
                now=start + timedelta(minutes=40),
            )

        self.assertEqual(sparse["state"], "collecting")
        self.assertLess(sparse["evidence"]["coverage_pct"], 80)
        self.assertEqual(stale["state"], "stale")


class PeerCollectorTests(unittest.TestCase):
    def test_collector_stores_only_aggregate_peer_evidence_and_caps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = base / "status.txt"
            history = base / "peer-history.json"
            status.write_text(
                "p2p_connected = 38\n"
                "consensus_peers = 31\n"
                "restarts = 2\n"
                "address = octSecretPublicIdentity\n"
                "private_key = never\n",
                encoding="utf-8",
            )
            record_sample(status, history, observed_at=1_800_000_000, max_samples=2)
            record_sample(status, history, observed_at=1_800_000_060, max_samples=2)
            record_sample(status, history, observed_at=1_800_000_120, max_samples=2)
            payload = json.loads(history.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "octra-validator-peer-history-v1")
        self.assertEqual(len(payload["samples"]), 2)
        self.assertEqual(
            set(payload["samples"][0]),
            {"observed_at", "p2p_connected", "consensus_peers", "restarts"},
        )
        self.assertNotIn("address", json.dumps(payload))
        self.assertNotIn("private_key", json.dumps(payload))

    def test_project_wires_peer_history_into_collector_container_and_ui(self):
        root = Path(__file__).resolve().parents[1]
        collector = (root / "collector.sh").read_text(encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        compose = (root / "compose.yaml").read_text(encoding="utf-8")
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('python3 "$SCRIPT_DIR/peer_collector.py"', collector)
        self.assertIn("peer_collector.py", dockerfile)
        self.assertIn("--peer-history-file", compose)
        self.assertIn('id="peer-stability-state"', html)
        self.assertIn("/api/peers", script)


if __name__ == "__main__":
    unittest.main()
