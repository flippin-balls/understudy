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


class TestCodexFindings(GameFixture):
    """Cases a review found reported confidently when they should not be.

    All three share a shape: inspect is deliberately more permissive than
    convert-set, because a broken layout is exactly what someone runs it to
    diagnose. That is only defensible while the report SAYS the layout is
    broken; otherwise a wrong table and a right one print the same thing.
    """

    def _rewrite(self, mutate):
        """Apply `mutate(image)` and push the result back into the devices."""
        profile = Profile(copy.deepcopy(self.raw), "<t>")
        image = bytearray(profile.assemble(self.dumps))
        mutate(image, profile)
        for device in profile.devices:
            lo = device.cpu_address - profile.window_base
            data = bytes(image[lo:lo + device.size])
            (self.roms / ("%s.bin" % device.socket)).write_bytes(data)
            self.dumps[device.socket] = data
        for entry in self.raw["devices"]:
            entry["sha256"] = sha256(self.dumps[entry["socket"]])
        synthetic_game.write_profile(Path(self.env), self.raw)

    def test_a_profile_that_cannot_authenticate_is_refused(self):
        """Without hashes a profile applies its layout to any correct-sized
        bytes, and inspect would report the result with full confidence."""
        for entry in self.raw["devices"]:
            entry.pop("sha256", None)
        synthetic_game.write_profile(Path(self.env), self.raw)
        code, _out, err = self.inspect()
        self.assertEqual(code, 2)
        self.assertIn("cannot verify what it is given", err)

    def test_a_phrase_outside_the_speech_devices_is_named(self):
        """Unpopulated space reads as 0xFF, which parses as a stop frame -- so
        such a phrase looks perfectly valid and converts to nothing."""
        def mutate(image, profile):
            image[profile.table_offset:profile.table_offset + 2] = \
                (profile.window_base).to_bytes(2, "big")
        self._rewrite(mutate)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("OUTSIDE SPEECH DEVICES", out)
        self.assertIn("convert-set would REFUSE", out)

    def test_a_silent_claim_that_is_false_is_not_repeated_as_fact(self):
        """`silent_phrases` is the profile's assertion. Conversion holds it to
        that and refuses otherwise, so inspect must not print it as a finding."""
        self.raw["layout"]["silent_phrases"] = [0]
        synthetic_game.write_profile(Path(self.env), self.raw)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("DECLARED SILENT BUT IS NOT", out)
        self.assertIn("convert-set would REFUSE", out)

    def test_a_good_set_says_conversion_would_be_accepted(self):
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("convert-set would accept", out)

    def test_the_suggested_command_reproduces_the_run(self):
        """Rebuilt from the positional list alone it dropped --game and printed
        a bare "." for a --socket run, aiming convert-set at the cwd."""
        sockets = []
        for entry in self.raw["devices"]:
            sockets += ["--socket", "%s=%s"
                        % (entry["socket"],
                           self.roms / ("%s.bin" % entry["socket"]))]
        code, out, err = run(["inspect", "--game", self.raw["profile_id"],
                              *sockets])
        self.assertEqual(code, 0, err)
        line = [l for l in out.splitlines() if "convert-set" in l][-1]
        self.assertIn("--game %s" % self.raw["profile_id"], line)
        for entry in self.raw["devices"]:
            self.assertIn("--socket", line)
            self.assertIn(entry["socket"], line)
        self.assertNotRegex(line, r"convert-set\s+\.\s*$")

    def test_a_path_with_spaces_is_quoted(self):
        spaced = Path(self.tmp.name) / "with space"
        spaced.mkdir()
        for entry in self.raw["devices"]:
            name = "%s.bin" % entry["socket"]
            (spaced / name).write_bytes((self.roms / name).read_bytes())
        code, out, err = run(["inspect", "--game", self.raw["profile_id"],
                              str(spaced)])
        self.assertEqual(code, 0, err)
        line = [l for l in out.splitlines() if "convert-set" in l][-1]
        # Asserted through the same helper the CLI uses: quoting style is
        # platform-specific -- POSIX single quotes, Windows double quotes -- and
        # hard-coding either makes this a test of the platform, not the code.
        self.assertIn(cli.shell_quote(str(spaced)), line)
        self.assertNotIn(" %s " % spaced, line)


class TestVerdictIsAskedNotPredicted(GameFixture):
    """The accept/refuse line must come from conversion, not from a guess.

    It began as a hand-rolled prediction of three refusal conditions, and a
    review showed it wrong in both directions -- approving sets conversion
    refuses, and refusing a profile that legitimately declares an unterminated
    phrase. These pin the cases that exposed it.
    """

    def _refresh(self, dumps):
        for socket, data in dumps.items():
            (self.roms / ("%s.bin" % socket)).write_bytes(data)
            self.dumps[socket] = data
        for entry in self.raw["devices"]:
            entry["sha256"] = sha256(self.dumps[entry["socket"]])
        synthetic_game.write_profile(Path(self.env), self.raw)

    def test_a_pointer_into_padding_is_reported_as_refused(self):
        """Leading-silence padding: the old prediction called this acceptable."""
        dumps = dict(self.dumps)
        u5 = bytearray(dumps["U5"])
        pad_at = 0x0900
        for i in range(pad_at, pad_at + 32):
            u5[i] = 0x00
        table_at = 0xFC00 - 0xF000
        u5[table_at:table_at + 2] = (0xF000 + pad_at).to_bytes(2, "big")
        dumps["U5"] = bytes(u5)
        self._refresh(dumps)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("convert-set would REFUSE", out)

    def test_a_declared_unterminated_phrase_is_reported_as_accepted(self):
        """A profile may legitimately declare one; m_mpac does. The prediction
        called that a refusal, because it only looked for a stop frame."""
        dumps, raw = synthetic_game.build(terminate=False)
        raw = copy.deepcopy(raw)
        raw["profile_id"] = self.raw["profile_id"]
        # Only the phrases that genuinely lack a stop frame. Declaring all four
        # is refused in the other direction, which the next test covers.
        raw["layout"]["unterminated_phrases"] = [0, 1]
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        self.raw = raw
        self._refresh(dumps)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("NO STOP FRAME", out)
        self.assertIn("convert-set would accept", out)

    def test_the_refusal_quotes_conversion_rather_than_paraphrasing(self):
        """Whatever conversion objects to, the reader sees its own words."""
        def mutate(image, profile):
            image[profile.table_offset:profile.table_offset + 2] = \
                (profile.window_base).to_bytes(2, "big")
        profile = Profile(copy.deepcopy(self.raw), "<t>")
        image = bytearray(profile.assemble(self.dumps))
        mutate(image, profile)
        dumps = {}
        for device in profile.devices:
            lo = device.cpu_address - profile.window_base
            dumps[device.socket] = bytes(image[lo:lo + device.size])
        self._refresh(dumps)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("convert-set would REFUSE", out)
        self.assertIn("speech", out.lower())

    def test_declaring_a_terminated_phrase_unterminated_is_reported_as_refused(self):
        """The check runs both ways, and the prediction only ran one."""
        dumps, raw = synthetic_game.build(terminate=False)
        raw = copy.deepcopy(raw)
        raw["profile_id"] = self.raw["profile_id"]
        raw["layout"]["unterminated_phrases"] = list(
            range(raw["layout"]["phrases"]))
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        self.raw = raw
        self._refresh(dumps)
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("convert-set would REFUSE", out)
        self.assertIn("unterminated_phrases", out)


class TestSourceChipResolution(GameFixture):
    """A profile may name its source chip by alias or in a different case.

    Conversion resolves it; inspect indexed the table dict directly, so a
    profile convert-set accepts crashed inspect with a KeyError.
    """

    def _with_source_chip(self, name):
        self.raw["source_chip"] = name
        synthetic_game.write_profile(Path(self.env), self.raw)

    def test_an_alias_is_accepted(self):
        self._with_source_chip("CD2501E")
        code, out, err = self.inspect()
        self.assertEqual(code, 0, err)
        self.assertIn("profile", out)

    def test_a_differently_cased_name_is_accepted(self):
        self._with_source_chip("TMS5200")
        code, _out, err = self.inspect()
        self.assertEqual(code, 0, err)

    def test_an_unknown_chip_is_a_readable_error_not_a_traceback(self):
        self._with_source_chip("definitely-not-a-chip")
        code, _out, err = self.inspect()
        self.assertEqual(code, 2)
        self.assertIn("unknown chip", err)
        self.assertNotIn("Traceback", err)

    def test_the_verdict_names_the_target_it_describes(self):
        """It reports the DEFAULT conversion; a C-family target can differ."""
        code, out, _err = self.inspect()
        self.assertEqual(code, 0)
        self.assertIn("tms5220", out)
        self.assertIn("default target", out)


class TestTableAddress(GameFixture):
    """Where the table sits is a window position, not a pointer-decoding rule.

    `base_address` is subtracted from each pointer; `window_base` is where the
    assembled image starts. They are equal in every bundled profile, so using
    the wrong one printed the right answer everywhere until a profile stored
    window-relative pointers.
    """

    def test_the_table_address_is_right_when_the_bases_differ(self):
        profile = Profile(copy.deepcopy(self.raw), "<t>")
        image = bytearray(profile.assemble(self.dumps))
        # Re-store every pointer window-relative, and say so with base_address 0.
        at = profile.table_offset
        for _ in range(profile.phrases):
            value = int.from_bytes(image[at:at + 2], "big")
            image[at:at + 2] = (value - profile.window_base).to_bytes(2, "big")
            at += 2
        for device in profile.devices:
            lo = device.cpu_address - profile.window_base
            data = bytes(image[lo:lo + device.size])
            (self.roms / ("%s.bin" % device.socket)).write_bytes(data)
            self.dumps[device.socket] = data
        self.raw["layout"]["base_address"] = 0
        for entry in self.raw["devices"]:
            entry["sha256"] = sha256(self.dumps[entry["socket"]])
        synthetic_game.write_profile(Path(self.env), self.raw)

        code, out, err = self.inspect()
        self.assertEqual(code, 0, err)
        want = self.raw["memory"]["window_base"] + self.raw["layout"]["table_offset"]
        self.assertIn("table     $%04X" % want, out)
        # And the bug it replaced would have printed the raw offset.
        self.assertNotIn("table     $%04X" % self.raw["layout"]["table_offset"],
                         out)
