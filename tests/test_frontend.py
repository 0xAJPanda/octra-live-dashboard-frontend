import unittest
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_frontend_requests_only_public_network_data(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn("/api/network", script)
        for endpoint in ("/api/snapshot", "/api/transition", "/api/storage", "/api/reliability", "/api/memory", "/api/peers"):
            self.assertNotIn(endpoint, script)

    def test_frontend_is_valid_browser_javascript(self):
        """Catch syntax and runtime-API typos before the dashboard ships."""
        script = ROOT / "static" / "script.js"
        self.assertNotIn(".removeprefix(", script.read_text(encoding="utf-8"))
        subprocess.run(["node", "--check", str(script)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
