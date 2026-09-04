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

from app import DashboardHandler, build_snapshot, is_enabled, parse_status


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixture_status.txt"


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


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        cls.server.status_path = FIXTURE
        cls.server.network_path = ROOT / "tests" / "fixture_network.json"
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

    def test_health_endpoint(self):
        with urllib.request.urlopen(f"{self.base}/healthz") as response:
            self.assertEqual(response.read(), b"ok\n")

    def test_network_endpoint(self):
        with urllib.request.urlopen(f"{self.base}/api/network") as response:
            payload = json.load(response)
        self.assertEqual(payload["schema"], "octra-public-validator-network-v1")
        self.assertGreaterEqual(payload["summary"]["active_validators"], 1)

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
