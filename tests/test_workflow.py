"""The short path, and every way it is made to stop rather than guess.

`convert_set` writes device images a technician will burn. The failure that
matters is not a crash: it is a run that finishes, looks right, and produces a
ROM that is subtly wrong. Each test here drives one of those situations.
"""
import copy
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

from synthetic_game import build, write_profile               # noqa: E402
from tms52xx import chips                                     # noqa: E402
from tms52xx.profiles import Profile, sha256                  # noqa: E402
from tms52xx.workflow import (ConversionRefused,              # noqa: E402
                              MANIFEST_SCHEMA_VERSION, convert_set)


def run(*args, cwd, extra_env=None):
    """Invoke the CLI as a subprocess, portably.

    The environment is inherited rather than replaced: setting PATH to a
    POSIX-only value cannot work on Windows, and Windows is a first-class
    target here because that is where most EPROM programmer software runs.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.pop("UNDERSTUDY_PROFILE_DIR", None)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-m", "tms52xx.cli", *args],
                          cwd=str(cwd), capture_output=True, text=True, env=env)


class WorkflowFixture(unittest.TestCase):
    def setUp(self):
        self.dumps, self.raw = build()
        self.profile = Profile(copy.deepcopy(self.raw), "<synth>")
        self.target = chips.resolve("tms5220")

    def convert(self, dumps=None, profile=None, **kwargs):
        return convert_set(dumps or dict(self.dumps),
                           profile or self.profile, self.target, **kwargs)


class TestHappyPath(WorkflowFixture):
    def test_it_converts_and_reports(self):
        result = self.convert()
        self.assertEqual(result.stats["phrases"], 4)
        self.assertGreater(result.stats["frames"], 0)
        self.assertEqual(result.stats["frame_kinds_preserved"],
                         result.stats["frames"])
        self.assertEqual(len(result.outputs), 2)

    def test_output_devices_keep_their_original_size(self):
        result = self.convert()
        for entry in result.outputs:
            device = self.profile.device_for(entry["socket"])
            self.assertEqual(entry["bytes"], device.size, entry["socket"])

    def test_changed_bytes_reconcile_across_devices(self):
        result = self.convert()
        total = sum(e["changed_bytes"] for e in result.outputs)
        self.assertEqual(total, result.stats["bytes_changed"])
        self.assertGreater(total, 0)

    def test_the_input_dumps_are_not_mutated(self):
        before = {k: bytes(v) for k, v in self.dumps.items()}
        self.convert()
        self.assertEqual(self.dumps, before)

    def test_the_mirrored_device_is_taken_from_the_half_that_changed(self):
        result = self.convert()
        u4 = next(e for e in result.outputs if e["socket"] == "U4")
        self.assertTrue(u4["changed"])
        self.assertTrue(u4["taken_from_mirror"])

    def test_conversion_only_ever_touches_phrase_extents(self):
        """The invariant the workflow's stray-byte backstop relies on."""
        from tms52xx.rom import PhraseTable
        result = self.convert()
        table = PhraseTable.from_pointers(
            result.before, self.profile.table_offset, self.profile.phrases,
            address_ordered=self.profile.address_ordered,
            has_end_bound=self.profile.has_end_bound,
            base_address=self.profile.base_address)
        inside = set()
        for phrase in table.phrases:
            inside.update(range(phrase.start, phrase.end))
        changed = {i for i, (a, b) in enumerate(zip(result.before, result.after))
                   if a != b}
        self.assertTrue(changed)
        self.assertTrue(changed <= inside,
                        "%d byte(s) changed outside every phrase extent"
                        % len(changed - inside))

    def test_nothing_outside_the_phrases_moved(self):
        result = self.convert()
        # The pointer table must survive untouched.
        at = self.profile.table_offset
        self.assertEqual(result.before[at:at + 2 * self.profile.phrases],
                         result.after[at:at + 2 * self.profile.phrases])


class TestRefusals(WorkflowFixture):
    """Each of these would otherwise produce a plausible, wrong ROM."""

    def test_a_missing_socket_is_refused(self):
        with self.assertRaises(ConversionRefused) as caught:
            self.convert({"U5": self.dumps["U5"]})
        self.assertIn("U4", str(caught.exception))

    def test_an_unknown_socket_is_refused(self):
        dumps = dict(self.dumps)
        dumps["U9"] = b"\x00" * 16
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps)
        self.assertIn("U9", str(caught.exception))

    def test_a_dump_that_does_not_match_the_profile_hash_is_refused(self):
        """A different revision must not be converted with this layout."""
        corrupt = bytearray(self.dumps["U5"])
        corrupt[5] ^= 0xFF
        dumps = dict(self.dumps, U5=bytes(corrupt))
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps)
        self.assertIn("does not match", str(caught.exception))

    def test_a_phrase_with_no_stop_frame_is_refused(self):
        """The layout parses, the phrases do not terminate: stop, do not write."""
        dumps, raw = build(terminate=False)
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<x>"), self.target)
        self.assertIn("stop frame", str(caught.exception))

    def test_the_override_exists_for_that_case(self):
        dumps, raw = build(terminate=False)
        result = convert_set(dumps, Profile(raw, "<x>"), self.target,
                             allow_unterminated=True)
        self.assertIn("allow_unterminated", result.overrides)


class TestDoubleConversion(WorkflowFixture):
    """Converting an already-converted set is caught, on both paths.

    A TMS52xx stream has nowhere to record that it has been converted, so the
    file itself cannot say. The profile hash does: converted output no longer
    matches the profile it came from, so both identification and an explicit
    --game are refused. This is protection the manual `convert` path does not
    have, and it is a reason to prefer `convert-set` where a profile exists.
    """

    def test_converted_output_no_longer_identifies_as_the_profile(self):
        result = self.convert()
        converted = {e["socket"]: e["data"] for e in result.outputs}
        files = {"a.bin": converted["U4"], "b.bin": converted["U5"]}
        import tempfile
        from tms52xx import profiles as profile_mod
        with tempfile.TemporaryDirectory() as tmp:
            from synthetic_game import write_profile
            write_profile(tmp, self.raw)
            self.assertEqual(
                [m for m in profile_mod.identify(files, tmp) if m.complete], [])

    def test_forcing_the_profile_onto_converted_output_is_refused(self):
        result = self.convert()
        converted = {e["socket"]: e["data"] for e in result.outputs}
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(converted, self.profile, self.target)
        self.assertIn("does not match", str(caught.exception))


class TestBackstops(WorkflowFixture):
    """Two checks that cannot fire today, and the properties that keep it so.

    `patch_rom` writes only inside phrase extents, and a well-formed profile's
    devices span every window a pointer can reach. Both checks stay because the
    consequence of either becoming reachable is a burned ROM with non-speech
    bytes rewritten, or a byte count that does not describe what was written.
    """

    def test_every_changed_byte_lies_inside_some_device_window(self):
        result = self.convert()
        covered = set()
        for device in self.profile.devices:
            at = device.cpu_address - self.profile.window_base
            span = device.size * (2 if device.mirrored else 1)
            covered.update(range(at, at + span))
        changed = {i for i, (a, b) in enumerate(zip(result.before, result.after))
                   if a != b}
        self.assertTrue(changed)
        self.assertTrue(changed <= covered,
                        "%d changed byte(s) lie outside every device"
                        % len(changed - covered))

    def test_the_per_device_totals_add_up_to_the_image_total(self):
        result = self.convert()
        self.assertEqual(sum(e["changed_bytes"] for e in result.outputs),
                         result.stats["bytes_changed"])


class TestManifest(WorkflowFixture):
    def setUp(self):
        super().setUp()
        self.manifest = self.convert().manifest

    def test_it_is_versioned(self):
        self.assertEqual(self.manifest["schema_version"],
                         MANIFEST_SCHEMA_VERSION)
        self.assertTrue(self.manifest["understudy_version"])

    def test_it_records_everything_a_bug_report_would_need(self):
        for key in ("profile", "chips", "tables", "layout", "inputs",
                    "outputs", "image", "summary", "phrases", "warnings"):
            self.assertIn(key, self.manifest, key)
        self.assertEqual(self.manifest["profile"]["id"], "synthgame")
        self.assertEqual(self.manifest["chips"]["target"], "tms5220")

    def test_it_identifies_the_tables_by_hash_not_just_name(self):
        for side in ("source", "target"):
            identity = self.manifest["tables"][side]
            self.assertEqual(len(identity["sha256"]), 64)
            self.assertTrue(identity["bundled"])
            self.assertEqual(identity["provenance"]["license"], "BSD-3-Clause")

    def test_input_and_output_hashes_describe_the_real_bytes(self):
        result = self.convert()
        for entry in result.manifest["inputs"]:
            self.assertEqual(entry["sha256"],
                             sha256(self.dumps[entry["socket"]]))
        for entry, out in zip(result.manifest["outputs"], result.outputs):
            self.assertEqual(entry["sha256"], sha256(out["data"]))

    def test_manifest_rows_reconcile_with_the_summary(self):
        rows = [r for r in self.manifest["phrases"] if r["alias_of"] is None]
        self.assertEqual(sum(r["changed_bytes"] for r in rows),
                         self.manifest["summary"]["bytes_changed"])

    def test_it_carries_no_rom_contents(self):
        text = json.dumps(self.manifest)
        self.assertNotIn("data", self.manifest["outputs"][0])
        # A manifest is facts about bytes, never the bytes.
        self.assertLess(len(text), 200_000)

    def test_a_pre_silicon_profile_warns(self):
        self.assertTrue(any("real board" in w
                            for w in self.manifest["warnings"]))


class TestCommandLine(unittest.TestCase):
    """The commands a technician actually types."""

    def setUp(self):
        self.dumps, self.raw = build()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.u4 = self.dir / "u4.bin"
        self.u5 = self.dir / "u5.bin"
        self.u4.write_bytes(self.dumps["U4"])
        self.u5.write_bytes(self.dumps["U5"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_chips_lists_the_5220_family(self):
        result = run("chips", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("tms5200", "tms5220", "tms5220c", "tsp5220c"):
            self.assertIn(name, result.stdout)

    def test_profiles_lists_embryon(self):
        result = run("profiles", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("embryon", result.stdout)

    def test_identify_on_unknown_dumps_points_at_the_manual_path(self):
        result = run("identify", str(self.u4), str(self.u5), cwd=self.dir)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("No bundled profile recognises", result.stdout)
        self.assertIn("understudy inspect", result.stdout)

    def test_identify_reports_hashes_for_a_bug_report(self):
        result = run("identify", str(self.u4), cwd=self.dir)
        self.assertIn("sha256", result.stdout)

    def test_convert_set_without_a_profile_refuses(self):
        result = run("convert-set", str(self.u4), str(self.u5),
                     "-o", str(self.dir / "out"), cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("could not identify", result.stderr)
        self.assertFalse((self.dir / "out").exists())

    def test_convert_set_rejects_a_source_part_as_target(self):
        result = run("convert-set", str(self.u4), "--game", "embryon",
                     "--target", "tms5200", "-o", str(self.dir / "out"),
                     cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not a replacement part", result.stderr)

    def test_convert_set_rejects_an_unknown_chip(self):
        result = run("convert-set", str(self.u4), "--game", "embryon",
                     "--target", "tms5110", "-o", str(self.dir / "out"),
                     cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("unknown chip", result.stderr)

    def test_each_output_is_named_after_its_own_socket_s_input(self):
        """Run the real command and check which input each output is named for.

        Naming by "the first file supplied" still produces two distinct files,
        because the socket is in the name -- so nothing is overwritten. What it
        produces is a file called `u4_U5_...` holding U5's converted contents,
        which is exactly the sort of thing that gets burned into the wrong chip.
        """
        write_profile(self.dir / "profiles", self.raw)
        out = self.dir / "out"
        result = run("convert-set", str(self.u4), str(self.u5),
                     "--game", "synthgame", "--target", "tms5220",
                     "-o", str(out), cwd=self.dir,
                     extra_env={"UNDERSTUDY_PROFILE_DIR":
                                str(self.dir / "profiles")})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        written = sorted(p.name for p in out.iterdir() if p.suffix == ".bin")
        self.assertEqual(len(written), 2, written)
        # u4.bin went into socket U4, so its output must carry both.
        self.assertTrue(any(n.startswith("u4_U4_") for n in written), written)
        self.assertTrue(any(n.startswith("u5_U5_") for n in written), written)

    def test_two_sockets_holding_identical_bytes_map_to_different_files(self):
        """Naming outputs by content would give both the same filename.

        Two devices in a set can legitimately hold identical bytes. If the
        output name were looked up by comparing contents, both sockets would be
        named after the same input file and one would silently overwrite the
        other -- leaving the technician one converted device and one copy of it.
        """
        same = self.dumps["U4"]
        raw = copy.deepcopy(self.raw)
        raw["profile_id"] = "twins"
        for device in raw["devices"]:
            device["size"] = len(same)
            device["sha256"] = sha256(same)
            device["mirrored"] = False
        raw["devices"][0]["cpu_address"] = 0xE000
        raw["devices"][1]["cpu_address"] = 0xE800

        profile_dir = self.dir / "profiles"
        write_profile(profile_dir, raw)
        a, b = self.dir / "a.bin", self.dir / "b.bin"
        a.write_bytes(same)
        b.write_bytes(same)

        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = None
            dumps = [str(a), str(b)]

        profile = Profile(raw, "<twins>")
        dumps, sources = _sockets_from_args(Args(), profile)
        self.assertEqual(sorted(dumps), ["U4", "U5"])
        self.assertNotEqual(sources["U4"], sources["U5"],
                            "both sockets were mapped to the same file")

    def test_the_same_file_given_twice_is_refused(self):
        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = None
            dumps = [str(self.u4), str(self.u4)]

        with self.assertRaises(ValueError) as caught:
            _sockets_from_args(Args(), Profile(self.raw, "<x>"))
        self.assertIn("twice", str(caught.exception))

    def test_an_ambiguous_size_match_is_refused_not_guessed(self):
        """Two same-sized files and no hash to tell them apart: stop."""
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device.pop("sha256", None)
            device["size"] = 0x800
            device["mirrored"] = False
        raw["devices"][0]["cpu_address"] = 0xE000
        raw["devices"][1]["cpu_address"] = 0xE800
        a, b = self.dir / "a.bin", self.dir / "b.bin"
        a.write_bytes(b"\x01" * 0x800)
        b.write_bytes(b"\x02" * 0x800)

        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = None
            dumps = [str(a), str(b)]

        with self.assertRaises(ValueError) as caught:
            _sockets_from_args(Args(), Profile(raw, "<x>"))
        self.assertIn("--socket", str(caught.exception))

    def test_an_explicit_socket_can_resolve_that(self):
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device.pop("sha256", None)
        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = ["U4=%s" % self.u4, "U5=%s" % self.u5]
            dumps = []

        dumps, sources = _sockets_from_args(Args(), Profile(raw, "<x>"))
        self.assertEqual(sorted(dumps), ["U4", "U5"])
        self.assertEqual(Path(sources["U4"]).name, "u4.bin")

    def test_a_socket_named_twice_is_refused(self):
        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = ["U4=%s" % self.u4, "U4=%s" % self.u5]
            dumps = []

        with self.assertRaises(ValueError) as caught:
            _sockets_from_args(Args(), Profile(self.raw, "<x>"))
        self.assertIn("twice", str(caught.exception))

    def test_output_paths_are_compared_case_insensitively_where_that_matters(self):
        """On Windows `out.bin` and `OUT.BIN` are one file.

        Comparing Path objects would call them different and let the input be
        overwritten on the platform most EPROM software runs on.
        """
        from tms52xx.cli import _same_file
        import os
        # Case folding is only observable on a case-insensitive platform, so
        # assert the normalisation that is observable everywhere: the same file
        # reached by two different spellings of its path.
        self.assertTrue(_same_file(Path("speech.bin"),
                                   Path("sub/../speech.bin")))
        self.assertTrue(_same_file(Path("./speech.bin"), Path("speech.bin")))
        self.assertFalse(_same_file(Path("speech.bin"), Path("other.bin")))
        # And where the platform IS case-insensitive, spelling must not matter.
        self.assertEqual(_same_file(Path("speech.bin"), Path("SPEECH.BIN")),
                         os.path.normcase("a") == os.path.normcase("A"))

    def test_an_unknown_game_names_the_known_ones(self):
        result = run("convert-set", str(self.u4), "--game", "nosuchgame",
                     "-o", str(self.dir / "out"), cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("embryon", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
