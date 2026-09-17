import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_frontend_requests_only_public_network_data(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn("/api/network", script)
        for endpoint in ("/api/snapshot", "/api/transition", "/api/storage", "/api/reliability", "/api/memory", "/api/peers"):
            self.assertNotIn(endpoint, script)


if __name__ == "__main__":
    unittest.main()
