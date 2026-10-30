"""Catch undefined application names when the optional pyflakes tool is available."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class UndefinedNamesTests(unittest.TestCase):
    def test_ideaforge_has_no_undefined_names(self):
        if importlib.util.find_spec("pyflakes") is None:
            self.skipTest("pyflakes is not importable; undefined-name lint not run")
        result = subprocess.run([sys.executable, "-m", "pyflakes", str(ROOT / "ideaforge")],
                                capture_output=True, text=True, timeout=30)
        self.assertIn(result.returncode, (0, 1), "pyflakes could not run")
        undefined = [line for line in (result.stdout + result.stderr).splitlines()
                     if "undefined name" in line]
        self.assertFalse(undefined, "undefined name: " + "; ".join(undefined)[:300])


if __name__ == "__main__":
    unittest.main()
