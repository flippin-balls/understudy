"""End-to-end CLI behaviour, including the refusals."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy      # noqa: E402
from test_rom import RomFixture                 # noqa: E402


def run(*args, cwd):
    return subprocess.run([sys.executable, "-m", "tms52xx.cli", *args],
                          cwd=cwd, capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})


class TestCli(RomFixture):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rom_path = self.dir / "speech.bin"
        self.rom_path.write_bytes(self.rom)
        original().to_json(self.dir / "src.json")
        understudy().to_json(self.dir / "dst.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _convert(self, *extra):
        return run("convert", str(self.rom_path), "-o", str(self.dir / "out.bin"),
                   "--source-tables", str(self.dir / "src.json"),
                   "--target-tables", str(self.dir / "dst.json"),
                   "--table-offset", "0", "--phrases", "2", *extra,
                   cwd=self.dir)

    def test_inspect_writes_nothing(self):
        before = sorted(p.name for p in self.dir.iterdir())
        result = run("inspect", str(self.rom_path), "--table-offset", "0",
                     "--phrases", "2", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 phrases", result.stdout)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_dry_run_writes_nothing(self):
        result = self._convert("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry run", result.stdout)
        self.assertFalse((self.dir / "out.bin").exists())

    def test_convert_writes_rom_and_manifest(self):
        result = self._convert()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.dir / "out.bin"
        self.assertTrue(out.exists())
        self.assertEqual(len(out.read_bytes()), len(self.rom))
        manifest = json.loads((self.dir / "out.bin.manifest.json").read_text())
        self.assertEqual(manifest["input"]["bytes"], len(self.rom))
        self.assertEqual(len(manifest["phrases"]), 2)
        self.assertIn("changed_ranges", manifest)

    def test_input_is_never_modified(self):
        self._convert()
        self.assertEqual(self.rom_path.read_bytes(), self.rom)

    def test_refuses_to_overwrite_without_force(self):
        self._convert()
        again = self._convert()
        self.assertEqual(again.returncode, 2)
        self.assertIn("refusing to overwrite", again.stderr)

    def test_force_allows_overwrite(self):
        self._convert()
        self.assertEqual(self._convert("--force").returncode, 0)

    def test_bad_layout_fails_loudly(self):
        result = run("convert", str(self.rom_path), "-o", str(self.dir / "x.bin"),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "dst.json"),
                     "--table-offset", "0", "--phrases", "99", cwd=self.dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.dir / "x.bin").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
