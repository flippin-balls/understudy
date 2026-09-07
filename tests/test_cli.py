"""End-to-end CLI behaviour, including the refusals."""
import hashlib
import json
import os
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
    """Invoke the CLI as a subprocess, portably.

    The environment is inherited rather than replaced. An earlier version set
    PATH to a POSIX-only value, which cannot work on Windows -- and Windows is
    a first-class target here, because that is where most EPROM programmer
    software runs.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run([sys.executable, "-m", "tms52xx.cli", *args],
                          cwd=str(cwd), capture_output=True, text=True, env=env)


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
        """The manifest must describe the file that was actually written.

        Sizes and phrase counts alone would hold for a tool that copied its
        input and invented the rest, so every recorded quantity is reconciled
        against the two files here.
        """
        result = self._convert()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.dir / "out.bin"
        after = out.read_bytes()
        self.assertEqual(len(after), len(self.rom))
        self.assertNotEqual(after, self.rom)

        manifest = json.loads((self.dir / "out.bin.manifest.json").read_text())
        self.assertEqual(manifest["input"]["bytes"], len(self.rom))
        self.assertEqual(len(manifest["phrases"]), 2)

        # Hashes name the exact bytes on disk, including the table files.
        digest = lambda data: hashlib.sha256(data).hexdigest()   # noqa: E731
        self.assertEqual(manifest["input"]["sha256"], digest(self.rom))
        self.assertEqual(manifest["output"]["sha256"], digest(after))
        self.assertEqual(manifest["tables"]["source_sha256"],
                         digest((self.dir / "src.json").read_bytes()))
        self.assertEqual(manifest["tables"]["target_sha256"],
                         digest((self.dir / "dst.json").read_bytes()))

        # changed_ranges must be exactly the bytes that differ, and the summary
        # must count exactly that many.
        differing = [i for i, (a, b) in enumerate(zip(self.rom, after)) if a != b]
        from_ranges = [i for lo, hi in manifest["changed_ranges"]
                       for i in range(lo, hi)]
        self.assertEqual(from_ranges, differing)
        self.assertEqual(manifest["summary"]["bytes_changed"], len(differing))

        # Every phrase's extent and per-phrase byte count must match too.
        for entry in manifest["phrases"]:
            span = range(entry["start"], entry["end"])
            changed = sum(1 for i in span if self.rom[i] != after[i])
            self.assertEqual(entry["changed_bytes"], changed,
                             "phrase %d" % entry["index"])

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

    def test_a_temporary_file_cannot_land_on_the_input(self):
        """Converting `x.tmp` into `x` must not destroy `x.tmp`.

        A temporary file named `<output>.tmp` is a path a user can legitimately
        hold, and opening it with O_TRUNC would destroy the input ROM part-way
        through the run. Temporary names come from mkstemp instead, so they are
        unpredictable and created exclusively.
        """
        for suffix in (".tmp", ".manifest.json.tmp"):
            source = self.dir / ("target.bin%s" % suffix)
            source.write_bytes(self.rom)
            result = run("convert", str(source),
                         "-o", str(self.dir / "target.bin"),
                         "--source-tables", str(self.dir / "src.json"),
                         "--target-tables", str(self.dir / "dst.json"),
                         "--table-offset", "0", "--phrases", "2", "--force",
                         cwd=self.dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(source.exists(),
                            "input %s was destroyed by the temporary file"
                            % source.name)
            self.assertEqual(source.read_bytes(), self.rom)
            source.unlink()
            (self.dir / "target.bin").unlink()
            (self.dir / "target.bin.manifest.json").unlink()

    def test_an_output_symlink_pointing_at_the_input_is_refused(self):
        link = self.dir / "link.bin"
        link.symlink_to(self.rom_path)
        result = run("convert", str(self.rom_path), "-o", str(link),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "dst.json"),
                     "--table-offset", "0", "--phrases", "2", "--force",
                     cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("is the input ROM", result.stderr)
        self.assertEqual(self.rom_path.read_bytes(), self.rom)

    def test_leaves_no_temporary_files_behind(self):
        self.assertEqual(self._convert().returncode, 0)
        strays = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(strays, [])

    def test_refuses_to_overwrite_an_existing_manifest_without_force(self):
        (self.dir / "out.bin.manifest.json").write_text("{}")
        result = self._convert()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual((self.dir / "out.bin.manifest.json").read_text(), "{}")

    def test_inspect_reports_a_verdict_on_every_phrase_row(self):
        """Parse the rows. The legend always prints both words regardless."""
        result = run("inspect", str(self.rom_path), "--table-offset", "0",
                     "--phrases", "2", "--source-tables",
                     str(self.dir / "src.json"), cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)

        rows = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 5 and parts[0].isdigit() and parts[1].startswith("0x"):
                rows[int(parts[0])] = parts[4]
        self.assertEqual(sorted(rows), [0, 1], result.stdout)
        for index, verdict in rows.items():
            self.assertIn(verdict, ("required", "spare"),
                          "phrase %d: %r" % (index, verdict))

        # And the verdicts agree with the library, so the row really is derived
        # rather than printed from a constant.
        sys.path.insert(0, str(ROOT / "src"))
        from tms52xx.rom import PhraseTable, diagnose_last_byte
        table = PhraseTable.from_pointers(self.rom, 0, 2)
        self.assertEqual(rows, diagnose_last_byte(self.rom, table, original()))

    def test_manifest_rows_reconcile_with_the_summary(self):
        """Per-phrase rows must add up to the summary, aliases excluded."""
        result = self._convert()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.dir / "out.bin.manifest.json").read_text())
        rows = manifest["phrases"]
        self.assertTrue(all("alias_of" in row for row in rows))
        physical = [row for row in rows if row["alias_of"] is None]
        self.assertEqual(sum(row["changed_bytes"] for row in physical),
                         manifest["summary"]["bytes_changed"])
        self.assertEqual(sum(row["frames"] for row in physical),
                         manifest["summary"]["frames"])
        self.assertEqual(len(physical), manifest["summary"]["distinct_phrases"])

    def test_identical_tables_are_refused(self):
        """Passing the same file twice is a no-op the user did not intend."""
        result = run("convert", str(self.rom_path), "-o", str(self.dir / "o.bin"),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "src.json"),
                     "--table-offset", "0", "--phrases", "2", cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("identical tables", result.stderr)
        self.assertFalse((self.dir / "o.bin").exists())

    def test_the_conversion_direction_is_printed(self):
        result = self._convert("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("synthetic-original -> synthetic-understudy",
                      result.stdout)

    def test_a_reversed_pair_is_flagged(self):
        """The tool cannot know which chip a ROM came from, but it can say so."""
        result = run("convert", str(self.rom_path), "-o", str(self.dir / "o.bin"),
                     "--source-tables", str(self.dir / "dst.json"),
                     "--target-tables", str(self.dir / "src.json"),
                     "--table-offset", "0", "--phrases", "2", "--dry-run",
                     cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("the wrong way round", result.stdout)

    def test_bad_layout_fails_loudly(self):
        """Loudly means it says what is wrong, not merely that it exited 2."""
        result = run("convert", str(self.rom_path), "-o", str(self.dir / "x.bin"),
                     "--source-tables", str(self.dir / "src.json"),
                     "--target-tables", str(self.dir / "dst.json"),
                     "--table-offset", "0", "--phrases", "99", cwd=self.dir)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.dir / "x.bin").exists())
        self.assertTrue(result.stderr.strip(), "failed with no diagnostic")
        self.assertIn("error:", result.stderr)
        self.assertIn("pointer table", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


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
        """Parse the rows: the legend prints both words no matter what."""
        result = run("inspect", str(self.rom_path), "--table-offset", "0",
                     "--phrases", "2", "--source-tables",
                     str(self.dir / "src.json"), cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 5 and parts[0].isdigit() and parts[1].startswith("0x"):
                rows[int(parts[0])] = parts[4]
        self.assertEqual(rows, {0: "spare", 1: "required"}, result.stdout)

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
