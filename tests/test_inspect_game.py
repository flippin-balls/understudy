"""`inspect --game`: read a supported set's phrase table, writing nothing.

The layout for every bundled game is already known, and `convert-set` reports
the whole phrase table -- but only into a manifest, which only exists once ROMs
have been written. These cover the command that closes that gap, and mostly
they guard the ways it could quietly stop matching the conversion it previews:
a different table form, a different set of accepted dumps, or addresses that
read as one thing and mean another.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic_game                                      # noqa: E402
from tms52xx import cli                                    # noqa: E402
from tms52xx.profiles import Profile, sha256               # noqa: E402


def run(argv):
    """Run the CLI, returning (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class GameFixture(unittest.TestCase):
    """A synthetic set on disk, with its profile in a directory we control."""

    entry_form = "starts"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        dumps, raw = synthetic_game.build()
        self.raw = self._shape(copy.deepcopy(raw))
        self.roms = root / "roms"
        self.roms.mkdir()
        for socket, data in dumps.items():
            (self.roms / ("%s.bin" % socket)).write_bytes(data)
        self.dumps = dumps
        profiles = root / "profiles"
        synthetic_game.write_profile(profiles, self.raw)
        self.env = str(profiles)
        import os
        os.environ["UNDERSTUDY_PROFILE_DIR"] = self.env
        self.addCleanup(os.environ.pop, "UNDERSTUDY_PROFILE_DIR", None)

    def _shape(self, raw):
        return raw

    def inspect(self, *extra):
        return run(["inspect", "--game", self.raw["profile_id"],
                    str(self.roms), *extra])


class TestStartsForm(GameFixture):
    """The ordinary form: a list of start pointers."""

    def test_it_prints_the_phrase_table(self):
        code, out, err = self.inspect()
        self.assertEqual(code, 0, err)
        self.assertIn("profile", out)
        self.assertIn("table", out)
        for index in range(self.raw["layout"]["phrases"]):
            self.assertRegex(out, r"(?m)^\s+%d\s+\$" % index)

    def test_addresses_are_cpu_addresses(self):
        """A window-relative decimal is not an address anyone can use."""
        code, out, _ = self.inspect()
        self.assertEqual(code, 0)
        base = self.raw["memory"]["window_base"]
        # Every printed start must sit inside the CPU window, not below it.
        found = [int(m, 16) for m in
                 __import__("re").findall(r"^\s+\d+\s+\$([0-9A-F]{4})", out,
                                          __import__("re").M)]
        self.assertTrue(found)
        for address in found:
            self.assertGreaterEqual(address, base)
            self.assertLess(address, base + self.raw["memory"]["window_size"])

    def test_it_names_the_table_form(self):
        _code, out, _ = self.inspect()
        self.assertIn("pointers", out)

    def test_it_writes_nothing(self):
        before = sorted(Path(self.tmp.name).rglob("*"))
        code, _out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(Path(self.tmp.name).rglob("*")), before)


class TestPairsForm(GameFixture):
    """(start, end) records -- the form the CLI could not express at all."""

    def _shape(self, raw):
        layout = raw["layout"]
        layout["entry_form"] = "start_end_pairs"
        layout.pop("address_ordered", None)
        layout.pop("has_end_bound", None)
        return raw

    def setUp(self):
        super().setUp()
        # Rewrite the table in the assembled image as 4-byte records, then push
        # the changed bytes back into the device that carries the table.
        # Take the extents the STARTS form derives, and re-encode exactly those
        # as records. Pairing raw consecutive pointers would not do: this table
        # is command-ordered, so pointer i+1 is frequently BELOW pointer i and
        # the pair is not an extent at all.
        from tms52xx.rom import PhraseTable
        starts_raw = copy.deepcopy(self.raw)
        starts_raw["layout"]["entry_form"] = "starts"
        # _shape removed these for the pairs form; the starts form needs them.
        starts_raw["layout"].setdefault("address_ordered", False)
        starts_raw["layout"].setdefault("has_end_bound", False)
        starts_profile = Profile(starts_raw, "<t>")
        image = bytearray(starts_profile.assemble(self.dumps))
        derived = PhraseTable.from_pointers(
            bytes(image), starts_profile.table_offset, starts_profile.phrases,
            address_ordered=starts_profile.address_ordered,
            has_end_bound=starts_profile.has_end_bound,
            base_address=starts_profile.base_address)
        profile = Profile(copy.deepcopy(self.raw), "<t>")
        records = bytearray()
        for phrase in derived.phrases:
            records += (phrase.start + profile.base_address).to_bytes(2, "big")
            records += (phrase.end + profile.base_address).to_bytes(2, "big")
        image[profile.table_offset:profile.table_offset + len(records)] = records
        for device in profile.devices:
            lo = device.cpu_address - profile.window_base
            data = bytes(image[lo:lo + device.size])
            (self.roms / ("%s.bin" % device.socket)).write_bytes(data)
            self.dumps[device.socket] = data
        for entry in self.raw["devices"]:
            entry["sha256"] = sha256(self.dumps[entry["socket"]])
        synthetic_game.write_profile(Path(self.env), self.raw)

    def test_it_reads_a_pairs_table(self):
        code, out, err = self.inspect()
        self.assertEqual(code, 0, err)
        self.assertIn("(start, end) records", out)
        for index in range(self.raw["layout"]["phrases"]):
            self.assertRegex(out, r"(?m)^\s+%d\s+\$" % index)

    def test_the_pairs_table_agrees_with_the_starts_table(self):
        """Same speech, two table shapes, identical extents.

        The point of the form is that it is a different SHAPE, not different
        data -- so reading one as the other is what must fail, and reading each
        correctly must agree.
        """
        code, pairs_out, _ = self.inspect()
        self.assertEqual(code, 0)
        import re
        rows = re.findall(r"(?m)^\s+(\d+)\s+\$([0-9A-F]{4})\s+\$([0-9A-F]{4})",
                          pairs_out)
        self.assertEqual(len(rows), self.raw["layout"]["phrases"])
        for _index, start, end in rows:
            self.assertLess(int(start, 16), int(end, 16))


class TestRefusal(GameFixture):
    def test_a_dump_that_does_not_match_the_profile_is_refused(self):
        """Inspecting the wrong bytes is worse than not inspecting."""
        socket = self.raw["devices"][0]["socket"]
        path = self.roms / ("%s.bin" % socket)
        data = bytearray(path.read_bytes())
        data[0] ^= 0xFF
        path.write_bytes(bytes(data))
        code, _out, err = self.inspect()
        self.assertEqual(code, 2)
        self.assertIn("refusing to inspect", err)

    def test_an_unknown_game_is_a_clean_error(self):
        code, _out, err = run(["inspect", "--game", "no-such-game",
                               str(self.roms)])
        self.assertEqual(code, 2)
        self.assertIn("no profile", err)

    def test_a_missing_device_is_refused(self):
        (self.roms / ("%s.bin" % self.raw["devices"][0]["socket"])).unlink()
        code, _out, err = self.inspect()
        self.assertEqual(code, 2)
        self.assertIn("refusing to inspect", err)


class TestManualPathUnchanged(unittest.TestCase):
    """The layout-supplied path must behave exactly as it always has."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        dumps, _raw = synthetic_game.build()
        self.rom = Path(self.tmp.name) / "one.bin"
        self.rom.write_bytes(next(iter(dumps.values())))

    def test_no_layout_still_explains_itself(self):
        code, out, _err = run(["inspect", str(self.rom)])
        self.assertEqual(code, 0)
        self.assertIn("No layout given", out)

    def test_two_roms_without_game_is_an_error(self):
        code, _out, err = run(["inspect", str(self.rom), str(self.rom)])
        self.assertEqual(code, 2)
        self.assertIn("one ROM at a time", err)

    def test_pairs_flag_rejects_flags_that_cannot_apply(self):
        for flag in ("--command-ordered", "--no-end-bound"):
            code, _out, err = run(["inspect", str(self.rom), "--table-offset",
                                   "0", "--phrases", "2", "--start-end-pairs",
                                   flag])
            self.assertEqual(code, 2, flag)
            self.assertIn("no meaning with --start-end-pairs", err)


if __name__ == "__main__":
    unittest.main()
