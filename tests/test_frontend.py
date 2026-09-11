import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendFormattingTests(unittest.TestCase):
    def test_byte_formatter_displays_terabyte_values_at_the_correct_scale(self):
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        function = re.search(r"function bytes\(value\) \{.*?\n\}", script, re.DOTALL)
        self.assertIsNotNone(function)
        result = subprocess.run(
            ["node", "-e", f"{function.group(0)}; process.stdout.write(bytes(1047972020224));"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "1.0 TB")


if __name__ == "__main__":
    unittest.main()
