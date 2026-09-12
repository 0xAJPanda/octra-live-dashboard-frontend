import json
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import DashboardHandler, build_snapshot, build_transition_snapshot, is_enabled, parse_status


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixture_status.txt"
UPGRADE_FIXTURE = ROOT / "tests" / "fixture_upgrade.txt"
STORAGE_FIXTURE = ROOT / "tests" / "fixture_storage_history.json"
RELIABILITY_FIXTURE = ROOT / "tests" / "fixture_reliability_history.json"


class SnapshotTests(unittest.TestCase):
    def test_parser_allows_public_fields_only(self):
        parsed = parse_status("address = octPublic\nprivate_key = never\nnode = internal-host\n")
        self.assertEqual(parsed, {"address": "octPublic"})

    def test_enabled_status_string_is_true(self):
        self.assertTrue(is_enabled("enabled"))
        self.assertFalse(is_enabled("disabled"))

    def test_active_validator_snapshot(self):
        snapshot = build_snapshot(FIXTURE, stale_after_seconds=31_536_000)
        self.assertTrue(snapshot["online"])
        self.assertTrue(snapshot["validator"]["active"])
        self.assertEqual(snapshot["enrollment"]["bond"], 1000000)
        self.assertEqual(snapshot["peers"]["consensus_peers"], 33)
        self.assertAlmostEqual(snapshot["host"]["memory_used_pct"], 44.44, places=2)

    def test_stale_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status.txt"
            status.write_text("process = online\nrpc = ready\n", encoding="utf-8")
            old = time.time() - 600
            status.touch()
            import os
            os.utime(status, (old, old))
            snapshot = build_snapshot(status, stale_after_seconds=180)
        self.assertFalse(snapshot["online"])
        self.assertIn("telemetry is stale", snapshot["health"]["warnings"])

    def test_transition_snapshot_fails_closed_when_upgrade_is_required(self):
        transition = build_transition_snapshot(UPGRADE_FIXTURE, stale_after_seconds=31_536_000)
        self.assertEqual(transition["state"], "upgrade_required")
        self.assertFalse(transition["ready"])
        self.assertFalse(transition["cutover_authorized"])
        self.assertEqual(transition["release"]["sequence"], 12)
        self.assertEqual(transition["runtime"]["lag"], 0)
        self.assertIn("signed upgrade has not been fully applied", transition["blockers"])
        serialized = json.dumps(transition)
        self.assertNotIn("/opt/octra", serialized)
        self.assertNotIn("data_dir", serialized)
        self.assertNotIn("935422", serialized)

    def test_transition_snapshot_is_ready_only_when_every_upgrade_gate_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            upgrade = Path(directory) / "upgrade.txt"
            upgrade.write_text(
                "\n".join([
                    "sequence = 12",
                    "action = none",
                    "release_published = True",
                    "upgrade_available = False",
                    "binary_match = True",
                    "source_match = True",
                    "runtime_match = True",
                    "rpc = ready",
                    "lag = 0",
                    "voting = True",
                    "validator_member = True",
                    "validator_scheduled = True",
                    "status = pass",
                    "gate = upgrade_diagnostic",
                ]),
                encoding="utf-8",
            )
            transition = build_transition_snapshot(upgrade, stale_after_seconds=180)
        self.assertTrue(transition["ready"])
        self.assertEqual(transition["state"], "upgrade_current")
        self.assertEqual(transition["blockers"], [])
        self.assertFalse(transition["cutover_authorized"])

    def test_stale_transition_telemetry_is_a_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            upgrade = Path(directory) / "upgrade.txt"
            upgrade.write_text("action = none\nupgrade_available = False\n", encoding="utf-8")
            old = time.time() - 600
            import os
            os.utime(upgrade, (old, old))
            transition = build_transition_snapshot(upgrade, stale_after_seconds=180)
        self.assertFalse(transition["ready"])
        self.assertIn("upgrade telemetry is stale", transition["blockers"])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        cls.server.status_path = FIXTURE
        cls.server.upgrade_path = UPGRADE_FIXTURE
        cls.server.network_path = ROOT / "tests" / "fixture_network.json"
        cls.server.storage_history_path = STORAGE_FIXTURE
        cls.server.reliability_history_path = RELIABILITY_FIXTURE
        cls.server.reliability_interval_seconds = 3600
        cls.server.stale_after_seconds = 31_536_000
        cls.server.project_dir = ROOT
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_snapshot_endpoint_and_security_headers(self):
        with urllib.request.urlopen(f"{self.base}/api/snapshot") as response:
            payload = json.load(response)
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["Strict-Transport-Security"], "max-age=31536000")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(payload["status"]["validator"], "oct8mvdkX3babyBsrzHYUB1cSU9a79RTbHXi7nJNfHJnUmk")
        self.assertNotIn("node", payload["status"])

    def test_static_assets_accept_cache_buster(self):
        with urllib.request.urlopen(f"{self.base}/static/script.js?v=1") as response:
            self.assertIn(b"api/snapshot", response.read())

    def test_javascript_dom_ids_exist(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script_ids = set(re.findall(r"\$\('([^']+)'\)", script))
        html_ids = set(re.findall(r'id="([^"]+)"', html))
        self.assertEqual(script_ids - html_ids, set())

    def test_network_explorer_is_rendered_from_the_public_network_api(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/network", script)
        self.assertIn('id="network-validator-rows"', html)
        self.assertIn('id="network-remote-uptime-note"', html)

    def test_transition_panel_is_rendered_from_the_read_only_api(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/transition", script)
        self.assertIn('id="transition-state"', html)
        self.assertIn('id="transition-blockers"', html)

    def test_storage_runway_panel_is_rendered_from_the_read_only_api(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/storage", script)
        self.assertIn('id="storage-state"', html)
        self.assertIn('id="storage-runway"', html)

    def test_reliability_panel_is_rendered_from_the_read_only_api(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/reliability", script)
        self.assertIn('id="reliability-state"', html)
        self.assertIn('id="reliability-coverage"', html)

    def test_health_endpoint(self):
        with urllib.request.urlopen(f"{self.base}/healthz") as response:
            self.assertEqual(response.read(), b"ok\n")

    def test_network_endpoint(self):
        with urllib.request.urlopen(f"{self.base}/api/network") as response:
            payload = json.load(response)
        self.assertEqual(payload["schema"], "octra-public-validator-network-v1")
        self.assertGreaterEqual(payload["summary"]["active_validators"], 1)

    def test_transition_endpoint_is_read_only_and_fail_closed(self):
        with urllib.request.urlopen(f"{self.base}/api/transition") as response:
            payload = json.load(response)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(payload["state"], "upgrade_required")
        self.assertFalse(payload["cutover_authorized"])

    def test_storage_endpoint_returns_only_derived_capacity_data(self):
        with urllib.request.urlopen(f"{self.base}/api/storage") as response:
            payload = json.load(response)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(payload["schema"], "octra-storage-runway-v1")
        self.assertIn(payload["state"], {"healthy", "watch", "warning", "critical"})
        serialized = json.dumps(payload)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("path", serialized)

    def test_reliability_endpoint_returns_only_derived_observation_metrics(self):
        with urllib.request.urlopen(f"{self.base}/api/reliability") as response:
            payload = json.load(response)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(payload["schema"], "octra-validator-reliability-v1")
        self.assertEqual(payload["state"], "healthy")
        serialized = json.dumps(payload)
        self.assertNotIn('"samples": [', serialized)
        self.assertNotIn("address", serialized)

    def test_validator_detail_api_returns_only_the_requested_public_record(self):
        address = "oct8mvdkX3babyBsrzHYUB1cSU9a79RTbHXi7nJNfHJnUmk"
        with urllib.request.urlopen(f"{self.base}/api/validators/{address}") as response:
            payload = json.load(response)
        self.assertEqual(payload["validator"]["address"], address)
        self.assertNotIn("private_key", payload["validator"])
        self.assertIn("limitations", payload)

    def test_validator_detail_route_serves_the_single_page_app(self):
        address = "oct8mvdkX3babyBsrzHYUB1cSU9a79RTbHXi7nJNfHJnUmk"
        with urllib.request.urlopen(f"{self.base}/validator/{address}") as response:
            html = response.read()
        self.assertIn(b"Validator network", html)
        self.assertIn(b'href="/static/style.css', html)
        self.assertIn(b'src="/static/script.js', html)
        self.assertIn(b'src="/static/logo.svg', html)

    def test_invalid_validator_detail_is_not_routed_or_looked_up(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{self.base}/api/validators/not-a-validator")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
