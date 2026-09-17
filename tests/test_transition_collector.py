import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TransitionCollectorTests(unittest.TestCase):
    def test_collector_is_atomic_allowlisted_and_never_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            controls = base / "node" / "controls"
            controls.mkdir(parents=True)
            upgrade = controls / "upgrade.sh"
            upgrade.write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = \"--root\" ] || exit 90\n"
                "[ \"$2\" = \"$EXPECTED_ROOT\" ] || exit 91\n"
                "printf '%s\\n' 'sequence = 12 action = upgrade public_commit = abc source_commit = def expires_at = 2026-09-11T03:41:59Z'\n"
                "printf '%s\\n' 'binary_match = True source_match = False runtime_match = False rpc = ready lag = 0 voting = True'\n"
                "printf '%s\\n' 'validator_member = True validator_scheduled = True release_published = True upgrade_available = True'\n"
                "printf '%s\\n' 'status = pass gate = upgrade_diagnostic config = /secret/path pid = 12345 private_key = never'\n"
                "exit 1\n",
                encoding="utf-8",
            )
            upgrade.chmod(0o755)
            output = base / "runtime" / "upgrade.txt"
            env = os.environ | {
                "OCTRA_NODE_DIR": str(base / "node"),
                "OCTRA_UPGRADE_PATH": str(output),
                "EXPECTED_ROOT": str(base / "node"),
            }
            subprocess.run(["sh", str(ROOT / "transition_collector.sh")], check=True, env=env)
            published = output.read_text(encoding="utf-8")

        self.assertIn("sequence = 12", published)
        self.assertIn("upgrade_available = True", published)
        self.assertNotIn("config", published)
        self.assertNotIn("/secret/path", published)
        self.assertNotIn("pid", published)
        self.assertNotIn("private_key", published)


if __name__ == "__main__":
    unittest.main()
