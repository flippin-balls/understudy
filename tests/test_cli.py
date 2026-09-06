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

    def test_refuses_to_write_over_the_input_rom_even_with_force(self):
        """--force means "replace the file you named", not "destroy the source".

        A speech ROM may be the only dump anyone has of that board. There is no
        conversion that requires writing over its own input, so this refusal
        sits ahead of --force rather than under it.
        """
        for args in ((), ("--force",)):
            result = run("convert", str(self.rom_path),
                         "-o", str(self.rom_path),
                         "--source-tables", str(self.dir / "src.json"),
                         "--target-tables", str(self.dir / "dst.json"),
                         "--table-offset", "0", "--phrases", "2", *args,
                         cwd=self.dir)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("is the input ROM", result.stderr)
            self.assertEqual(self.rom_path.read_bytes(), self.rom)

    def test_refuses_when_the_manifest_would_land_on_the_input(self):
        """The manifest path is derived, so it can collide without being typed."""
        rom_path = self.dir / "speech.bin.manifest.json"
        rom_path.write_bytes(self.rom)
        result = run("convert", str(rom_path), "-o", str(self.dir / "speech.bin"),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "dst.json"),
                     "--table-offset", "0", "--phrases", "2", "--force",
                     cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("is the input ROM", result.stderr)
        self.assertEqual(rom_path.read_bytes(), self.rom)

    def test_leaves_no_temporary_files_behind(self):
        self.assertEqual(self._convert().returncode, 0)
        strays = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(strays, [])

    def test_refuses_to_overwrite_an_existing_manifest_without_force(self):
        (self.dir / "out.bin.manifest.json").write_text("{}")
        result = self._convert()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual((self.dir / "out.bin.manifest.json").read_text(), "{}")

    def test_inspect_reports_the_final_byte_verdicts(self):
        result = run("inspect", str(self.rom_path), "--table-offset", "0",
                     "--phrases", "2", "--source-tables",
                     str(self.dir / "src.json"), cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("final byte", result.stdout)
        self.assertTrue(any(v in result.stdout
                            for v in ("required", "spare")), result.stdout)

    def test_bad_layout_fails_loudly(self):
        result = run("convert", str(self.rom_path), "-o", str(self.dir / "x.bin"),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "dst.json"),
                     "--table-offset", "0", "--phrases", "99", cwd=self.dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.dir / "x.bin").exists())


class TestFinalByteConvention(unittest.TestCase):
    """--truncate-last-byte is per phrase, and interacts with the stop-frame check.

    The ROM here has one phrase padded with a spare byte after its stop frame
    and one whose stop frame reaches into its final byte, which is the mixture
    real ROM sets are documented to contain.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = original()
        src.to_json(self.dir / "src.json")
        understudy().to_json(self.dir / "dst.json")

        from test_rom import stream
        body = [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])]
        spare = stream(src, body) + b"\x00"      # a byte past the stop frame
        required = stream(src, body)              # stop frame reaches the last byte
        rom = bytearray(6)
        starts = [6, 6 + len(spare)]
        for i, value in enumerate(starts + [6 + len(spare) + len(required)]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom += spare + required
        self.rom = bytes(rom)
        self.rom_path = self.dir / "speech.bin"
        self.rom_path.write_bytes(self.rom)

    def tearDown(self):
        self.tmp.cleanup()

    def _convert(self, *extra):
        return run("convert", str(self.rom_path), "-o", str(self.dir / "out.bin"),
                   "--source-tables", str(self.dir / "src.json"),
                   "--target-tables", str(self.dir / "dst.json"),
                   "--table-offset", "0", "--phrases", "2", *extra,
                   cwd=self.dir)

    def test_inspect_separates_the_two_verdicts(self):
        result = run("inspect", str(self.rom_path), "--table-offset", "0",
                     "--phrases", "2", "--source-tables",
                     str(self.dir / "src.json"), cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("spare", result.stdout)
        self.assertIn("required", result.stdout)

    def test_truncating_a_spare_phrase_works(self):
        result = self._convert("--truncate-last-byte", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.dir / "out.bin.manifest.json").read_text())
        self.assertEqual(manifest["layout"]["truncate_last_byte"], [0])
        self.assertTrue(manifest["phrases"][0]["last_byte_truncated"])
        self.assertFalse(manifest["phrases"][1]["last_byte_truncated"])
        # The spare byte is left exactly as found.
        out = (self.dir / "out.bin").read_bytes()
        end = manifest["phrases"][0]["end"]
        self.assertEqual(out[end - 1], self.rom[end - 1])

    def test_truncating_a_required_phrase_is_caught(self):
        """Dropping a needed final byte removes the terminator, and is refused.

        This is the two guards composing: --truncate-last-byte decides which
        bytes are part of the stream, and the stop-frame check then notices that
        the stream no longer terminates. Neither alone would catch it.
        """
        result = self._convert("--truncate-last-byte", "1")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("do not end in a stop frame", result.stderr)
        self.assertFalse((self.dir / "out.bin").exists())

    def test_the_bare_flag_is_caught_for_the_same_reason(self):
        result = self._convert("--truncate-last-byte")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertFalse((self.dir / "out.bin").exists())

    def test_rejects_nonsense_indexes(self):
        for value in ("banana", "1,,x", "-1"):
            result = self._convert("--truncate-last-byte", value)
            self.assertEqual(result.returncode, 2,
                             "%r: %s" % (value, result.stdout))
            self.assertFalse((self.dir / "out.bin").exists())

    def test_rejects_an_unknown_phrase_index(self):
        result = self._convert("--truncate-last-byte", "99")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no such phrase index", result.stderr)
        self.assertFalse((self.dir / "out.bin").exists())


class TestUnterminatedPhrases(unittest.TestCase):
    """A phrase with no stop frame is a layout error, and must not be written.

    The usual cause is a wrong --table-offset/--phrases/--base-address, which
    aims the converter at code or data and rewrites it as though it were speech.
    That produces a file of the right length that looks converted and is not, so
    the tool refuses rather than printing a line the user may not read.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src, dst = original(), understudy()
        src.to_json(self.dir / "src.json")
        dst.to_json(self.dir / "dst.json")

        from test_rom import stream
        # Two voiced frames and NO stop frame: the stream simply runs out.
        body = stream(src, [(7, 0, 40, list(range(10))),
                            (8, 0, 41, list(range(10)))])
        rom = bytearray(4)
        for i, value in enumerate([4, 4 + len(body)]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom += body
        self.rom = bytes(rom)
        self.rom_path = self.dir / "speech.bin"
        self.rom_path.write_bytes(self.rom)

    def tearDown(self):
        self.tmp.cleanup()

    def _convert(self, *extra):
        return run("convert", str(self.rom_path), "-o", str(self.dir / "out.bin"),
                   "--source-tables", str(self.dir / "src.json"),
                   "--target-tables", str(self.dir / "dst.json"),
                   "--table-offset", "0", "--phrases", "1", *extra,
                   cwd=self.dir)

    def test_refuses_and_writes_nothing(self):
        result = self._convert()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("do not end in a stop frame", result.stderr)
        self.assertFalse((self.dir / "out.bin").exists())
        self.assertFalse((self.dir / "out.bin.manifest.json").exists())

    def test_dry_run_also_refuses(self):
        """The refusal is about the layout, so --dry-run must not bypass it."""
        result = self._convert("--dry-run")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_the_override_exists_and_works(self):
        result = self._convert("--allow-unterminated")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = (self.dir / "out.bin").read_bytes()
        self.assertEqual(len(out), len(self.rom))
        self.assertNotEqual(out, self.rom)
        manifest = json.loads((self.dir / "out.bin.manifest.json").read_text())
        self.assertFalse(manifest["phrases"][0]["stopped_cleanly"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
