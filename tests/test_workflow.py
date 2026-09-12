"""The short path, and every way it is made to stop rather than guess.

`convert_set` writes device images a technician will burn. The failure that
matters is not a crash: it is a run that finishes, looks right, and produces a
ROM that is subtly wrong. Each test here drives one of those situations.
"""
import copy
import json
import json as _json
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


class TestDestinationPreflight(unittest.TestCase):
    """Nothing is written until every destination is known to be safe.

    The manifest's name is derived from the profile id, so it is a path a user
    can already hold. With --force it was written over an input dump,
    atomically, returning success -- destroying the only copy of a speech ROM.
    """

    def setUp(self):
        self.dumps, self.raw = build()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profiles = self.dir / "profiles"
        write_profile(self.profiles, self.raw)
        self.env = {"UNDERSTUDY_PROFILE_DIR": str(self.profiles)}
        self.u5 = self.dir / "u5.bin"
        self.u5.write_bytes(self.dumps["U5"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_file_read_is_protected_from_being_overwritten(self):
        """Reading a file is what earns it protection, not being selected.

        The guard list was built from the SELECTED sockets, so an input that was
        read and then discarded had none. Handing convert-set a second archive
        whose name matched an output destroyed it: found in review, with a zip
        named like the manifest.
        """
        import zipfile
        good = self.dir / "good.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("u4.bin", self.dumps["U4"])
            z.writestr("u5.bin", self.dumps["U5"])
        decoy = self.dir / "synthgame.manifest.json"      # the manifest's own name
        with zipfile.ZipFile(decoy, "w") as z:
            z.writestr("unrelated.bin", b"\xaa" * 64)
        before = decoy.read_bytes()
        result = run("convert-set", str(good), str(decoy), "-o", str(self.dir),
                     "--force", cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(decoy.read_bytes(), before, "a file this run READ was destroyed")

    def test_identify_suggests_a_command_that_actually_runs(self):
        """identify only has to recognise the SPEECH ROMs; convert-set needs the set.

        `identify a.bin b.bin cpu.bin` succeeds and used to suggest a convert-set
        with cpu.bin still in it, which convert-set then refuses -- the tool
        handing you a command it rejects.
        """
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        stray = self.dir / "cpu.bin"
        stray.write_bytes(b"\x5a" * 373)
        result = run("identify", str(u4), str(self.u5), str(stray),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        suggested = [l for l in result.stdout.splitlines() if "convert-set" in l]
        self.assertTrue(suggested, result.stdout)
        self.assertNotIn("cpu.bin", suggested[-1])

    def test_manual_convert_cannot_overwrite_a_table_it_read(self):
        """`convert`'s own preflight runs BEFORE anything is read.

        So it could only know the paths the user named, and
        `convert rom -o <a bundled coefficient table> --force` replaced a table
        that same run had loaded. The registry check has to run after the reads.
        """
        from tms52xx import chips
        table = Path(chips.__file__).parent / "data" / "tms5220.json"
        before = table.read_bytes()
        rom = self.dir / "speech.bin"
        raw = self.raw
        mem = raw["memory"]
        image = bytearray([mem.get("fill", 0xFF)]) * mem["window_size"]
        for d in raw["devices"]:
            off = d["cpu_address"] - mem["window_base"]
            image[off:off + d["size"]] = self.dumps[d["socket"]]
        rom.write_bytes(bytes(image))
        layout = raw["layout"]
        result = run("convert", str(rom),
                     "--table-offset", str(layout["table_offset"]),
                     "--phrases", str(layout["phrases"]),
                     "--base-address", str(mem["window_base"]),
                     "--no-end-bound", "--command-ordered",
                     "-o", str(table), "--force",
                     cwd=self.dir, extra_env=self.env)
        self.assertIn("file this run reads", result.stderr + result.stdout)
        self.assertEqual(table.read_bytes(), before,
                         "a bundled coefficient table was overwritten")

    def test_every_file_the_run_reads_is_protected_including_bundled_data(self):
        """The guard is sourced from one registry, not assembled per code path.

        Four separate omissions were found this way -- zip members, discarded
        archives, zero-row archives, then the profile directory and the bundled
        coefficient tables. All of those are read during an ordinary run, and any
        of them could be written over by aiming -o at it with --force.
        """
        from tms52xx import reads, chips, profiles
        reads.reset()
        chips.resolve("tms5220").tables()
        profiles.available()
        recorded = {str(p) for p in reads.consumed()}
        self.assertTrue(any(p.endswith("tms5220.json") for p in recorded),
                        "the bundled target table was read but not recorded")
        self.assertTrue(any("profiles" in p for p in recorded),
                        "profile files were read but not recorded")

    def test_enumeration_is_bounded_before_entries_are_examined(self):
        """Bounding accepted rows bounds nothing: skipped entries are the cheap ones to make."""
        crowd = self.dir / "crowd"
        crowd.mkdir()
        for i in range(600):
            (crowd / ("note%d.txt" % i)).write_text("x")
        result = run("identify", str(crowd), cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("files to look at", result.stderr)

    def test_a_non_regular_file_is_refused_rather_than_read(self):
        """A FIFO reports no meaningful size, so it cannot be bounded."""
        import os
        fifo = self.dir / "pipe.bin"
        try:
            os.mkfifo(fifo)
        except (AttributeError, OSError):
            self.skipTest("no FIFO support here")
        result = run("convert-set", str(fifo), "-o", str(self.dir / "out"),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not a regular file", result.stderr)

    def test_an_archive_that_yields_nothing_is_still_protected(self):
        """Protection is earned by being OPENED, not by yielding a usable row.

        The first fix recorded guards per emitted row, so an archive whose members
        were all skipped -- one holding only README.txt -- was opened, read, and
        left unguarded. It was then overwritten by the manifest, exit code 0.
        """
        import zipfile
        good = self.dir / "good.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("u4.bin", self.dumps["U4"])
            z.writestr("u5.bin", self.dumps["U5"])
        decoy = self.dir / "synthgame.manifest.json"
        with zipfile.ZipFile(decoy, "w") as z:
            z.writestr("README.txt", "nothing a scan will accept")
        before = decoy.read_bytes()
        result = run("convert-set", str(good), str(decoy), "-o", str(self.dir),
                     "--force", cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(decoy.read_bytes(), before,
                         "an archive that produced no usable row was destroyed")

    def test_an_oversized_loose_file_is_refused_before_it_is_read(self):
        """Folder files were read fully and measured afterwards."""
        roms = self.dir / "roms"
        roms.mkdir()
        (roms / "u4.bin").write_bytes(self.dumps["U4"])
        (roms / "huge.bin").write_bytes(b"\0" * (9 * 1024 * 1024))
        result = run("identify", str(roms), cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("at most 8 KB", result.stderr)

    def test_an_archive_with_unsupported_compression_is_explained(self):
        """BadZipFile was caught; NotImplementedError was not."""
        import zipfile, struct
        bad = self.dir / "weird.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("u4.bin", self.dumps["U4"])
        raw = bytearray(bad.read_bytes())
        # force an unknown compression method on the local + central headers
        for sig in (b"PK\x03\x04", b"PK\x01\x02"):
            i = raw.find(sig)
            if i >= 0:
                off = 8 if sig == b"PK\x03\x04" else 10
                struct.pack_into("<H", raw, i + off, 99)
        bad.write_bytes(bytes(raw))
        result = run("identify", str(bad), cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_an_oversized_member_is_refused_before_it_is_read(self):
        """A crafted archive must not get to spend the memory first."""
        import zipfile
        bomb = self.dir / "bomb.zip"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big.bin", b"\0" * (16 * 1024 * 1024))
        self.assertLess(bomb.stat().st_size, 100 * 1024, "precondition: small on disk")
        result = run("convert-set", str(bomb), "-o", str(self.dir / "out"),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("at most 8 KB", result.stderr)

    def test_a_duplicate_member_name_is_refused_by_both_commands(self):
        """A name that does not identify one file cannot be matched to a socket."""
        import zipfile
        dup = self.dir / "dup.zip"
        with zipfile.ZipFile(dup, "w") as z:
            z.writestr("U4.bin", b"\x01" * 2048)
            z.writestr("U4.bin", b"\x02" * 2048)
        for command in ("identify", "convert-set"):
            result = run(command, str(dup), cwd=self.dir, extra_env=self.env)
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("more than one input is called", result.stderr, command)

    def test_a_symlink_in_a_scanned_folder_is_not_followed(self):
        """Scanning is a convenience; reading files the user did not offer is not."""
        outside = self.dir / "outside.bin"
        outside.write_bytes(b"\x7f" * 2048)
        roms = self.dir / "roms"
        roms.mkdir()
        (roms / "u4.bin").write_bytes(self.dumps["U4"])
        (roms / "u5.bin").write_bytes(self.dumps["U5"])
        try:
            (roms / "sneaky.bin").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable here")
        result = run("identify", str(roms), cwd=self.dir, extra_env=self.env)
        self.assertNotIn("sneaky.bin", result.stdout + result.stderr)

    def test_pointing_at_a_folder_converts_the_set(self):
        """The command a board repairer actually wants to type.

        Listing every dump is a programmer's habit. Someone with a machine open
        has a folder of files read out of sockets, and should be able to point
        at it.
        """
        roms = self.dir / "roms"
        roms.mkdir()
        (roms / "u4.bin").write_bytes(self.dumps["U4"])
        (roms / "u5.bin").write_bytes(self.dumps["U5"])
        out = self.dir / "out"
        result = run("convert-set", str(roms), "-o", str(out),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(sum(1 for p in out.iterdir() if p.suffix != ".json"), 2)

    def test_a_folder_may_hold_files_that_are_not_speech_roms(self):
        """A real ROM folder holds the CPU ROMs and a README as well.

        A file the user NAMED and which fits no socket is an error. A file
        merely FOUND while expanding a folder is not -- otherwise the easy path
        is the one that fails, which is the opposite of the point.
        """
        roms = self.dir / "roms"
        roms.mkdir()
        (roms / "u4.bin").write_bytes(self.dumps["U4"])
        (roms / "u5.bin").write_bytes(self.dumps["U5"])
        (roms / "README").write_text("notes about this machine")
        (roms / "notes.txt").write_text("more notes")
        (roms / "cpu.bin").write_bytes(b"\xa5" * 373)      # fits no socket
        out = self.dir / "out"
        result = run("convert-set", str(roms), "-o", str(out),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_a_named_file_that_fits_no_socket_is_still_an_error(self):
        """The guard that folder support must not weaken.

        Naming a file is a claim that it belongs in the set. Converting less
        than the user asked for, silently, is worse than refusing.
        """
        stray = self.dir / "stray.bin"
        stray.write_bytes(b"\x5a" * 373)
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        result = run("convert-set", str(u4), str(self.u5), str(stray),
                     "--game", "synthgame", "-o", str(self.dir / "out"),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not part of the", result.stderr)
        self.assertIn("stray.bin", result.stderr)
        # and it must offer the way out, not suggest forcing it into a socket
        self.assertIn("point at the whole folder", result.stderr)
        self.assertNotIn("--socket", result.stderr)

    def test_pointing_at_a_zip_converts_the_set(self):
        """ROM sets arrive as zips far more often than as loose files."""
        import zipfile
        archive = self.dir / "game.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("u4.bin", self.dumps["U4"])
            z.writestr("u5.bin", self.dumps["U5"])
            z.writestr("README", "notes")
        out = self.dir / "out"
        result = run("convert-set", str(archive), "-o", str(out),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        written = sorted(p.name for p in out.iterdir() if p.suffix != ".json")
        self.assertEqual(len(written), 2, written)
        # Outputs are named after the ZIP MEMBER, not the archive, or both
        # devices would be named "game" and collide.
        self.assertTrue(any(n.startswith("u4") for n in written), written)
        self.assertTrue(any(n.startswith("u5") for n in written), written)

    def test_a_zip_is_never_overwritten_by_its_own_output(self):
        """The overwrite guard must follow a member back to its archive.

        A zip member has no path of its own. If the guard were given the member
        name it would protect nothing, and an output could land on the archive
        the run is reading.
        """
        import zipfile
        archive = self.dir / "synthgame.manifest.json"    # the derived name
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("u4.bin", self.dumps["U4"])
            z.writestr("u5.bin", self.dumps["U5"])
        before = archive.read_bytes()
        result = run("convert-set", str(archive), "-o", str(self.dir),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(archive.read_bytes(), before, "the archive was modified")

    def test_the_manifest_cannot_overwrite_an_input_even_with_force(self):
        victim = self.dir / "synthgame.manifest.json"     # the derived name
        victim.write_bytes(self.dumps["U4"])
        before = victim.read_bytes()
        for args in ([], ["--force"]):
            result = run("convert-set", "--game", "synthgame",
                         "--socket", "U4=%s" % victim,
                         "--socket", "U5=%s" % self.u5,
                         "--target", "tms5220", "-o", str(self.dir), *args,
                         cwd=self.dir, extra_env=self.env)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("written over a file this run reads", result.stderr)
            self.assertEqual(victim.read_bytes(), before,
                             "the input dump was modified")

    def test_converting_into_the_directory_holding_the_inputs_is_safe(self):
        """The obvious thing a technician does: `-o .`

        Device output names always gain a socket and target suffix, so they
        cannot collide with the input they came from. The manifest name does
        not, which is what made the collision above reachable. Both inputs must
        survive here, and the new files must be additions.
        """
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        before = {p.name: p.read_bytes()
                  for p in self.dir.iterdir() if p.is_file()}

        result = run("convert-set", str(u4), str(self.u5), "--game", "synthgame",
                     "--target", "tms5220", "-o", str(self.dir),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in before.items():
            self.assertEqual((self.dir / name).read_bytes(), content,
                             "%s was modified" % name)
        added = {p.name for p in self.dir.iterdir() if p.is_file()} - set(before)
        self.assertEqual(len(added), 3, added)     # two devices + manifest

    def test_a_custom_table_is_an_input_too(self):
        """"Input" means every file the run reads, not only the ROM dumps.

        A coefficient table someone wrote is as irreplaceable to them as a ROM
        dump, and an earlier version of this check would replace it.
        """
        import json as _json
        from tms52xx import chips as chips_mod
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        # Name the table exactly what one of the outputs will be called.
        collide = self.dir / "u4_U4_2716_custom.bin"
        chips_mod.resolve("tms5220").tables().to_json(collide)
        before = collide.read_bytes()

        result = run("convert-set", str(u4), str(self.u5), "--game",
                     "synthgame", "--target", "tms5220",
                     "--target-tables", str(collide),
                     "-o", str(self.dir), "--force",
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("this run reads", result.stderr)
        self.assertEqual(collide.read_bytes(), before)

    def test_the_profile_file_is_an_input_too(self):
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        # Convert into the profile directory; the manifest would land on it.
        result = run("convert-set", str(u4), str(self.u5), "--game",
                     "synthgame", "--target", "tms5220",
                     "-o", str(self.profiles), "--force",
                     cwd=self.dir, extra_env=self.env)
        # The profile is synthgame.json, the manifest synthgame.manifest.json,
        # so they do not collide -- but the profile must survive regardless.
        self.assertTrue((self.profiles / "synthgame.json").exists())
        self.assertEqual(
            _json.loads((self.profiles / "synthgame.json").read_text())
            ["profile_id"], "synthgame")

    def test_a_refusal_leaves_no_partial_output_set(self):
        """A half-written set invites burning a mixture of new and stale files."""
        out = self.dir / "out"
        out.mkdir()
        (out / "synthgame.manifest.json").write_text("older manifest")
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])

        result = run("convert-set", str(u4), str(self.u5), "--game", "synthgame",
                     "--target", "tms5220", "-o", str(out),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["synthgame.manifest.json"])
        self.assertEqual((out / "synthgame.manifest.json").read_text(),
                         "older manifest")

    def test_a_clean_run_writes_the_whole_set(self):
        out = self.dir / "out"
        u4 = self.dir / "u4.bin"
        u4.write_bytes(self.dumps["U4"])
        result = run("convert-set", str(u4), str(self.u5), "--game", "synthgame",
                     "--target", "tms5220", "-o", str(out),
                     cwd=self.dir, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(len(names), 3, names)
        self.assertIn("synthgame.manifest.json", names)


class TestProfileMustAuthenticate(WorkflowFixture):
    """A profile that cannot verify its input must not produce burn images."""

    def test_a_profile_without_device_hashes_is_refused(self):
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device.pop("sha256", None)
        profile = Profile(raw, "<x>")
        self.assertFalse(profile.identifiable)
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dict(self.dumps), profile, self.target)
        self.assertIn("cannot verify", str(caught.exception))

    def test_even_with_allow_unterminated(self):
        """--allow-unterminated must not become a way round authentication."""
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device.pop("sha256", None)
        with self.assertRaises(ConversionRefused):
            convert_set(dict(self.dumps), Profile(raw, "<x>"), self.target,
                        allow_unterminated=True)


class TestPhraseCoverage(WorkflowFixture):
    """A phrase must live inside a device the profile says holds speech.

    `assemble` fills windows no device covers with 0xFF, and 0xF is the stop
    frame's energy code -- so a pointer into unpopulated space parses as a
    clean, one-frame phrase that changes nothing. Every other check passes it:
    it terminates, its frame kinds are trivially preserved, and reconciliation
    only counts bytes that changed. The ROM would simply be missing that phrase.
    """

    def test_a_phrase_pointing_into_unpopulated_fill_is_refused(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["mirrored"] = False        # 0xE800 becomes fill
        raw["devices"][0]["holds_speech"] = False
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dict(self.dumps), Profile(raw, "<gap>"), self.target)
        self.assertIn("not inside any device", str(caught.exception))

    def test_one_erased_phrase_inside_a_working_device_is_refused(self):
        """An erased region of a real EPROM reads the same as an unmapped gap.

        A wholly erased device is caught earlier, by the "socket marked as
        holding speech did not change" rule. This is the case that slips past
        it: one phrase erased while others in the same device convert normally.
        """
        # Phrase 0 lives at the start of U5. Erase exactly its bytes.
        from tms52xx.rom import PhraseTable
        table = PhraseTable.from_pointers(
            self.profile.assemble(self.dumps), self.profile.table_offset,
            self.profile.phrases, address_ordered=self.profile.address_ordered,
            has_end_bound=self.profile.has_end_bound,
            base_address=self.profile.base_address)
        target_phrase = next(p for p in table.phrases if p.start >= 0x3000)
        u5_offset = target_phrase.start - 0x3000

        dumps = dict(self.dumps)
        u5 = bytearray(dumps["U5"])
        for i in range(u5_offset, u5_offset + target_phrase.length):
            u5[i] = 0xFF
        dumps["U5"] = bytes(u5)

        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["sha256"] = sha256(dumps["U4"])
        raw["devices"][1]["sha256"] = sha256(dumps["U5"])
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<erased>"), self.target)
        self.assertIn("fill", str(caught.exception))

    def test_the_normal_case_still_converts(self):
        """Guard: the coverage check must not reject a valid mirrored layout."""
        result = self.convert()
        self.assertEqual(result.stats["phrases"], 4)


class TestPaddingPointers(WorkflowFixture):
    """A pointer aimed at padding must not become a phrase.

    Zero bytes parse as silence frames, so such a pointer produces a phrase
    that begins with a run of them and continues into whatever follows -- which
    on the real Embryon set was 6800 code. It terminates, its frame kinds
    survive conversion, and every other check passes it. Converting it stopped
    the board booting in simulation.
    """

    def _with_padding_pointer(self):
        """Aim one pointer at a run of zero bytes inside a speech device."""
        dumps = dict(self.dumps)
        u5 = bytearray(dumps["U5"])
        pad_at = 0x0900                       # unused space, clear of the table
        for i in range(pad_at, pad_at + 32):
            u5[i] = 0x00
        table_at = 0xFC00 - 0xF000
        u5[table_at:table_at + 2] = (0xF000 + pad_at).to_bytes(2, "big")
        dumps["U5"] = bytes(u5)
        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["sha256"] = sha256(dumps["U4"])
        raw["devices"][1]["sha256"] = sha256(dumps["U5"])
        return dumps, raw

    def test_a_pointer_into_padding_is_refused(self):
        dumps, raw = self._with_padding_pointer()
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<pad>"), self.target)
        self.assertIn("silence frames", str(caught.exception))

    def test_the_message_suggests_the_end_bound_reading(self):
        """That was the actual fix on the real set, so say so."""
        dumps, raw = self._with_padding_pointer()
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<pad>"), self.target)
        self.assertIn("end bound", str(caught.exception))

    def test_real_phrases_are_not_affected(self):
        """The threshold has margin: real phrases lead with no silence at all."""
        result = self.convert()
        self.assertEqual(result.stats["phrases"], 4)


class TestPublishIsAllOrNothing(unittest.TestCase):
    """A converted set is only useful complete."""

    def test_a_staging_failure_leaves_nothing_behind(self):
        from tms52xx.cli import _publish
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "existing.bin").write_bytes(b"OLD")
            payloads = [(d / "a.bin", b"A"),
                        (d / "existing.bin", b"NEW"),
                        (d / "missing-dir" / "c.bin", b"C")]
            with self.assertRaises(OSError):
                _publish(payloads)
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             ["existing.bin"])
            self.assertEqual((d / "existing.bin").read_bytes(), b"OLD")

    def test_a_clean_publish_replaces_everything(self):
        from tms52xx.cli import _publish
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "existing.bin").write_bytes(b"OLD")
            _publish([(d / "a.bin", b"A"), (d / "existing.bin", b"NEW")])
            self.assertEqual((d / "a.bin").read_bytes(), b"A")
            self.assertEqual((d / "existing.bin").read_bytes(), b"NEW")
            leftovers = [p.name for p in d.iterdir()
                         if ".part" in p.name or ".replaced" in p.name]
            self.assertEqual(leftovers, [])


class TestCustomTables(WorkflowFixture):
    """A supplied table must not be presented as a named physical part.

    Nothing checks that a table file describes the chip the user named, so a
    file called `..._tsp5220c.bin` and a manifest saying `target: tsp5220c`
    would both assert something unverified about bytes a technician is going to
    burn.
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self.tmp.name) / "mine.json"
        chips.resolve("tms5220").tables().to_json(self.custom)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_manifest_does_not_claim_the_requested_part(self):
        result = self.convert(target_tables=self.custom)
        self.assertEqual(result.manifest["chips"]["target"], "custom")
        self.assertEqual(result.manifest["chips"]["requested_target"],
                         "tms5220")
        self.assertEqual(result.manifest["tables"]["target"]["chip"], "custom")
        self.assertFalse(result.manifest["tables"]["target"]["bundled"])

    def test_the_table_file_is_read_exactly_once(self):
        """Load and hash must see the same bytes.

        Reading the file twice -- once to parse, once to hash -- lets a file
        that changes in between produce a manifest identifying tables that did
        not make the ROM. There is no way to observe that without a concurrent
        write, so the property asserted is the one that prevents it: one read.
        """
        from unittest import mock
        from tms52xx.workflow import _load_tables
        from tms52xx import chips as chips_mod

        real = Path.read_bytes
        seen = []

        def counting(self, *args, **kwargs):
            seen.append(str(self))
            return real(self, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", counting):
            _load_tables(chips_mod.resolve("tms5220"), self.custom)
        self.assertEqual([p for p in seen if p == str(self.custom)],
                         [str(self.custom)],
                         "the table file was read %d times" % len(seen))

    def test_it_records_the_table_s_own_name_and_hash(self):
        result = self.convert(target_tables=self.custom)
        identity = result.manifest["tables"]["target"]
        self.assertEqual(identity["requested_chip"], "tms5220")
        self.assertTrue(identity["table_name"])
        self.assertEqual(len(identity["sha256"]), 64)

    def test_it_warns_and_records_an_override(self):
        result = self.convert(target_tables=self.custom)
        self.assertIn("custom_tables", result.overrides)
        self.assertTrue(any("CUSTOM COEFFICIENT TABLES" in w
                            for w in result.warnings))

    def test_the_output_filename_says_custom(self):
        from tms52xx.workflow import output_name
        device = self.profile.device_for("U4")
        target = chips.resolve("tsp5220c")
        self.assertIn("custom",
                      output_name("u4.bin", device, target, custom_tables=True))
        self.assertNotIn("tsp5220c",
                         output_name("u4.bin", device, target,
                                     custom_tables=True))

    def test_bundled_tables_still_name_the_part(self):
        result = self.convert()
        self.assertEqual(result.manifest["chips"]["target"], "tms5220")
        self.assertEqual(result.manifest["tables"]["target"]["chip"], "tms5220")
        self.assertNotIn("custom_tables", result.overrides)

    def test_the_filename_carries_the_device_type(self):
        """A file named only for the socket invites burning it into the wrong
        device: a Squawk & Talk socket takes a 2716, 2532 or 2732."""
        from tms52xx.workflow import output_name
        device = self.profile.device_for("U4")
        name = output_name("u4.bin", device, chips.resolve("tms5220"))
        self.assertIn(device.socket, name)
        self.assertIn(device.device_type, name)


class TestPublishBackupNaming(unittest.TestCase):
    """The publisher's own temporary names must not collide with user files."""

    def test_a_file_named_like_the_backup_path_is_not_destroyed(self):
        """A derived backup name is a path a user can hold.

        `<dest>.replaced` was unlinked before each replace, which destroyed
        exactly the kind of file the publisher exists to protect. Backup names
        now come from mkstemp.
        """
        from tms52xx.cli import _publish
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "out.bin").write_bytes(b"EXISTING")
            for name in ("out.bin.replaced", "out.bin.backup", "out.bin.part",
                         "out.bin.tmp"):
                victim = d / name
                victim.write_bytes(b"PRECIOUS")
                _publish([(d / "out.bin", b"NEW")])
                self.assertTrue(victim.exists(), name)
                self.assertEqual(victim.read_bytes(), b"PRECIOUS", name)
                victim.unlink()
            self.assertEqual((d / "out.bin").read_bytes(), b"NEW")

    def test_no_temporary_files_survive_a_clean_publish(self):
        from tms52xx.cli import _publish
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.bin").write_bytes(b"OLD")
            _publish([(d / "a.bin", b"NEW"), (d / "b.bin", b"B")])
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             ["a.bin", "b.bin"])


class TestAllDevicesAuthenticated(WorkflowFixture):
    """Every emitted device must be authenticated, speech or not.

    A device carrying no speech is still copied out as a burn image. Unhashed,
    it is accepted on size alone, so a technician could be handed a file named
    for a socket and sized for its device holding whatever was passed in.
    """

    def test_an_unhashed_non_speech_device_is_refused(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"].append({
            "socket": "U2", "type": "2532", "size": 0x1000,
            "cpu_address": 0xC000, "mirrored": False, "holds_speech": False})
        dumps = dict(self.dumps, U2=b"\xFF" * 0x1000)
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<x>"), self.target)
        self.assertIn("U2", str(caught.exception))
        self.assertIn("cannot verify", str(caught.exception))

    def test_hashing_it_makes_the_profile_usable_again(self):
        raw = copy.deepcopy(self.raw)
        blank = b"\xFF" * 0x1000
        raw["devices"].append({
            "socket": "U2", "type": "2532", "size": 0x1000,
            "cpu_address": 0xC000, "mirrored": False, "holds_speech": False,
            "sha256": sha256(blank)})
        result = convert_set(dict(self.dumps, U2=blank), Profile(raw, "<x>"),
                             self.target)
        u2 = next(e for e in result.outputs if e["socket"] == "U2")
        self.assertFalse(u2["changed"])


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

    def test_it_identifies_the_profile_by_content(self):
        """An id and a version say which profile was MEANT; a hash says which
        one actually authorised this conversion, even after an edit."""
        import tempfile
        from synthetic_game import write_profile
        with tempfile.TemporaryDirectory() as tmp:
            path = write_profile(tmp, self.raw)
            from tms52xx import profiles as profile_mod
            loaded = profile_mod.load_file(path)
            result = convert_set(dict(self.dumps), loaded, self.target)
            digest = result.manifest["profile"]["sha256"]
            self.assertEqual(len(digest), 64)
            self.assertEqual(digest, sha256(path.read_bytes()))

    def test_an_in_memory_profile_reports_no_digest_rather_than_a_wrong_one(self):
        self.assertIsNone(self.manifest["profile"]["sha256"])

    def test_the_checked_in_example_matches_the_current_schema(self):
        """A stale example is a manifest that documents a format we no longer
        write, which is worse than no example."""
        example = json.loads(
            (ROOT / "examples" / "embryon.manifest.json").read_text())
        self.assertEqual(example["schema_version"], MANIFEST_SCHEMA_VERSION)
        self.assertEqual(sorted(example), sorted(
            list(self.manifest) + ["note"]))
        for key in ("profile", "chips", "tables", "summary"):
            self.assertEqual(sorted(example[key]), sorted(self.manifest[key]),
                             key)
        self.assertEqual(sorted(example["outputs"][0]),
                         sorted(list(self.manifest["outputs"][0]) + ["path"]))

    def test_it_records_every_revision_the_profile_serves(self):
        """A bug report names one game; the manifest must say which set it was.

        Revisions of a game share sound ROMs, so the driver a technician names
        and the profile that converted it are often different words for the
        same ROMs.
        """
        served = self.manifest["profile"]["applies_to"]
        self.assertTrue(served)
        self.assertIn(self.profile.id, served)
        self.assertEqual(served, self.profile.revisions)

    def test_it_records_how_much_of_each_device_the_layout_reached(self):
        """A layout that finds a corner of the speech still converts and boots.

        One real set was measured converting 1.5% of its speech while behaving
        identically to the original in board simulation; correct layouts across
        the sets checked ran 33-70%. The figure is recorded so a low one is
        visible, and reported rather than gated because the range is too wide
        for a threshold.
        """
        for entry in self.manifest["outputs"]:
            coverage = entry["speech_coverage_percent"]
            self.assertIsNotNone(coverage, entry["socket"])
            self.assertGreater(coverage, 0, entry["socket"])
            self.assertLessEqual(coverage, 100, entry["socket"])

    def test_coverage_never_exceeds_the_device(self):
        """Overlapping or duplicate phrases must not be counted twice.

        Summing extents rather than unioning them produced 171% on a real set,
        which reads as "more than the whole device" and is meaningless.
        """
        a_start = self.profile.phrases and None
        raw = copy.deepcopy(self.raw)
        # Two commands naming one phrase: a legal, documented arrangement.
        rom = bytearray(self.dumps["U5"])
        table_at = 0xFC00 - 0xF000
        first = rom[table_at:table_at + 2]
        rom[table_at + 2:table_at + 4] = first
        dumps = dict(self.dumps, U5=bytes(rom))
        raw["devices"][0]["sha256"] = sha256(dumps["U4"])
        raw["devices"][1]["sha256"] = sha256(dumps["U5"])
        try:
            result = convert_set(dumps, Profile(raw, "<dup>"), self.target)
        except ConversionRefused:
            return          # refused for another reason; the guard still holds
        for entry in result.outputs:
            coverage = entry["speech_coverage_percent"]
            if coverage is not None:
                self.assertLessEqual(coverage, 100.0, entry["socket"])

    def test_a_non_speech_device_reports_no_coverage(self):
        raw = copy.deepcopy(self.raw)
        blank = b"\xFF" * 0x1000
        raw["devices"].append({
            "socket": "U2", "type": "2532", "size": 0x1000,
            "cpu_address": 0xC000, "mirrored": False, "holds_speech": False,
            "sha256": sha256(blank)})
        result = convert_set(dict(self.dumps, U2=blank), Profile(raw, "<x>"),
                             self.target)
        u2 = next(e for e in result.outputs if e["socket"] == "U2")
        self.assertIsNone(u2["speech_coverage_percent"])

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
        # Not "understudy inspect": the tool names the invocation the reader
        # actually used, which here is `python -m tms52xx.cli`.
        self.assertIn("inspect <image> --table-offset", result.stdout)

    def test_identify_reports_hashes_for_a_bug_report(self):
        result = run("identify", str(self.u4), cwd=self.dir)
        self.assertIn("sha256", result.stdout)

    def test_convert_set_without_a_profile_refuses(self):
        result = run("convert-set", str(self.u4), str(self.u5),
                     "-o", str(self.dir / "out"), cwd=self.dir)
        self.assertEqual(result.returncode, 2, result.stdout)
        # The message must name a cause the reader can act on, and hand back a
        # command they can actually run -- it used to suggest `identify` with no
        # files, which is a usage error.
        self.assertIn("does not match any game", result.stderr)
        self.assertIn("identify", result.stderr)
        self.assertIn("--game", result.stderr)
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
        dumps, sources, _guards = _sockets_from_args(Args(), profile)
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

        dumps, sources, _guards = _sockets_from_args(Args(), Profile(raw, "<x>"))
        self.assertEqual(sorted(dumps), ["U4", "U5"])
        self.assertEqual(Path(sources["U4"]).name, "u4.bin")

    def test_a_file_that_fits_no_socket_is_refused(self):
        """Silently dropping a supplied file converts less than was asked for,
        and leaves it out of the manifest -- which is the record of what was
        done to an irreplaceable ROM."""
        extra = self.dir / "extra.bin"
        extra.write_bytes(b"\x7F" * 64)
        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = None
            dumps = [str(self.u4), str(self.u5), str(extra)]

        with self.assertRaises(ValueError) as caught:
            _sockets_from_args(Args(), Profile(self.raw, "<x>"))
        self.assertIn("extra.bin", str(caught.exception))

    def test_mixing_positional_dumps_with_socket_is_refused(self):
        """Positional files were silently ignored whenever --socket appeared."""
        from tms52xx.cli import _sockets_from_args

        class Args:
            socket = ["U4=%s" % self.u4]
            dumps = [str(self.u5)]

        with self.assertRaises(ValueError) as caught:
            _sockets_from_args(Args(), Profile(self.raw, "<x>"))
        self.assertIn("not both", str(caught.exception))

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


class TestPhraseStartMustBeInSpeech(WorkflowFixture):
    """A phrase pointing into a gap converts to nothing and reports success.

    Unmapped space assembles as 0xFF, and 0xF is the stop frame's energy code,
    so such a pointer parses as a clean one-frame phrase. The test is the
    phrase's START rather than its whole extent: an extent is the DECLARED
    bound -- the next pointer, or the table -- and legitimately runs past where
    the speech stops.
    """

    def _table_entry(self, dumps, index, value):
        """Point table entry `index` at `value` (a CPU address)."""
        device = self.profile.device_for("U5")
        at = self.profile.table_offset - (device.cpu_address
                                          - self.profile.window_base)
        data = bytearray(dumps["U5"])
        off = at + 2 * index
        data[off:off + 2] = value.to_bytes(2, "big")
        dumps["U5"] = bytes(data)
        return dumps

    def test_a_phrase_starting_in_unmapped_space_is_refused(self):
        # 0xE900 is inside the window but inside no device: U4 is a 2 KB part
        # answering at 0xE000 and 0xE800, U5 starts at 0xF000.
        dumps = self._table_entry(dict(self.dumps), 0, 0xD400)
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device["sha256"] = sha256(dumps[device["socket"]])
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        self.assertIn("not inside any device", str(caught.exception))

    def test_a_phrase_whose_declared_extent_overruns_its_device_is_allowed(self):
        """The case the extent test used to fail: a bound past the speech.

        The last phrase in a device is bounded by the pointer table, which
        lives in the NEXT device. Nothing is wrong with that, and the bytes
        past the stop frame are never written differently.
        """
        result = self.convert()
        self.assertGreater(result.stats["frames"], 0)


class TestConvertedBytesStayInSpeechDevices(unittest.TestCase):
    """A backstop for a change that lands in NO device at all.

    The per-device reconciliation compares each device against its input, so it
    catches a change in a device the profile says holds no speech. It cannot
    catch one that lands outside every device: those bytes exist only in the
    assembled image, nothing is emitted for them, and the converted set would
    silently be missing the tail of that phrase.

    Reaching it needs a set with a HOLE -- a phrase whose declared extent runs
    off the end of its device into unmapped space -- which the shared fixture,
    whose devices tile their window, cannot express.
    """

    WINDOW, SPEECH, TABLE = 0xC000, 0xC000, 0xF000
    HOLE = 0xC900               # inside the window, inside no device

    def build_holed_set(self):
        from synthetic import original
        from synthetic_game import _phrase
        chip = original()
        body = _phrase(chip, 7, 40, True)

        speech = bytearray(b"\xFF" * 0x800)          # 2 KB at 0xC000
        speech[0:len(body)] = body
        table = bytearray(b"\xFF" * 0x1000)          # 4 KB at 0xF000
        # One phrase, starting in the device and bounded by the table -- so its
        # declared extent crosses the unmapped space between them.
        table[0:2] = self.SPEECH.to_bytes(2, "big")
        table[2:4] = self.TABLE.to_bytes(2, "big")

        dumps = {"U2": bytes(speech), "U5": bytes(table)}
        raw = {
            "schema_version": 1, "profile_id": "holed", "profile_version": 1,
            "title": "Holed", "manufacturer": "Bally", "year": 1981,
            "board": "Squawk & Talk AS-2518-61", "source_chip": "tms5200",
            "status": "draft",
            "memory": {"window_base": self.WINDOW, "window_size": 0x4000,
                       "fill": 255},
            "devices": [
                {"socket": "U2", "label": "speech", "type": "2716",
                 "size": 0x800, "cpu_address": self.SPEECH, "mirrored": False,
                 "holds_speech": True, "sha256": sha256(dumps["U2"])},
                {"socket": "U5", "label": "table", "type": "2532",
                 "size": 0x1000, "cpu_address": self.TABLE, "mirrored": False,
                 "holds_speech": False, "sha256": sha256(dumps["U5"])},
            ],
            "layout": {"table_offset": self.TABLE - self.WINDOW,
                       "base_address": self.WINDOW, "phrases": 1,
                       "address_ordered": True, "has_end_bound": True,
                       "truncate_last_byte": []},
            "evidence": {"layout": "constructed for this test"},
        }
        return dumps, raw

    def test_the_hole_really_is_inside_a_phrase_extent(self):
        """Otherwise the older stray-byte backstop would be what fires."""
        from tms52xx.rom import PhraseTable
        dumps, raw = self.build_holed_set()
        profile = Profile(raw, "<holed>")
        table = PhraseTable.from_pointers(
            profile.assemble(dumps), profile.table_offset, profile.phrases,
            address_ordered=True, has_end_bound=True,
            base_address=profile.base_address)
        offset = self.HOLE - self.WINDOW
        self.assertTrue(any(p.start <= offset < p.end for p in table.phrases))

    def test_a_change_landing_in_no_device_at_all_is_refused(self):
        from tms52xx import workflow
        from tms52xx.rom import patch_rom as real_patch
        dumps, raw = self.build_holed_set()

        def patch(image, table, source, target, **kwargs):
            out, results = real_patch(image, table, source, target, **kwargs)
            data = bytearray(out)
            data[self.HOLE - self.WINDOW] ^= 0xFF
            return bytes(data), results

        workflow.patch_rom = patch
        try:
            with self.assertRaises(ConversionRefused) as caught:
                convert_set(dumps, Profile(raw, "<holed>"),
                            chips.resolve("tms5220"))
        finally:
            workflow.patch_rom = real_patch
        self.assertIn("outside every device", str(caught.exception))

    def test_without_the_tampering_the_same_set_converts(self):
        dumps, raw = self.build_holed_set()
        result = convert_set(dumps, Profile(raw, "<holed>"),
                             chips.resolve("tms5220"))
        self.assertGreater(result.stats["frames"], 0)


class TestSilentPhrasesMustBeDeclaredAndTrue(WorkflowFixture):
    """Silence is refused unless the profile names it, and then it is checked.

    A pointer aimed at padding looks exactly like a deliberately silent phrase,
    so the guard cannot simply allow silence. It can require the profile to say
    which phrases are silent -- and then hold it to the claim, so the field
    cannot be used to switch the guard off.
    """

    #: Table order is c, a, d, b -- so the U4 phrase at the device's own
    #: offset 0 is phrase 1, not phrase 0.
    SILENT = 1

    def silent_set(self):
        """A set whose phrase 1 is a long run of silence and nothing else.

        Replaced in place, keeping its length, so the phrase that follows it in
        the same device is untouched.
        """
        from synthetic import original
        from synthetic_game import _phrase
        dumps, raw = build()
        span = len(_phrase(original(), 7, 40, True))
        data = bytearray(dumps["U4"])
        data[0:span] = b"\x00" * (span - 1) + b"\xFF"
        dumps["U4"] = bytes(data)
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        return dumps, raw

    def test_undeclared_silence_is_refused_and_says_what_to_do(self):
        dumps, raw = self.silent_set()
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        message = str(caught.exception)
        self.assertIn("silence", message)
        self.assertIn("silent_phrases", message)

    def test_declaring_it_allows_the_conversion(self):
        dumps, raw = self.silent_set()
        raw["layout"]["silent_phrases"] = [self.SILENT]
        result = self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        self.assertGreater(result.stats["frames"], 0)

    def test_declaring_a_phrase_that_carries_speech_is_refused(self):
        """The exemption is a claim about the ROM, not a switch."""
        raw = copy.deepcopy(self.raw)
        raw["layout"]["silent_phrases"] = [self.SILENT]
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(profile=Profile(raw, "<x>"))
        self.assertIn("not silence and nothing else",
                      str(caught.exception))

class TestUnterminatedPhrasesMustBeDeclaredAndTrue(WorkflowFixture):
    """A phrase with no stop frame is refused unless the profile names it.

    In a few sets the player supplies the terminator rather than the ROM --
    Mr. and Mrs. Pac-Man has exactly one such phrase. That is indistinguishable,
    from the bytes alone, from a layout aimed at code, so it stays refused by
    default and the profile has to say which phrases it means. The claim is
    then checked both ways.
    """

    def unterminated_set(self):
        """A set built without stop frames, and which of its phrases lack one.

        Not all of them do: a phrase bounded by erased 0xFF picks up a stop
        frame from the fill, which is the same accident that makes a pointer
        into a gap look terminated. The test needs the real list, so it asks.
        """
        dumps, raw = build(terminate=False)
        profile = Profile(copy.deepcopy(raw), "<x>")
        from tms52xx.rom import PhraseTable, diagnose_last_byte
        from tms52xx.workflow import _load_tables
        image = profile.assemble(dumps)
        table = PhraseTable.from_pointers(
            image, profile.table_offset, profile.phrases,
            address_ordered=profile.address_ordered,
            has_end_bound=profile.has_end_bound,
            base_address=profile.base_address)
        src = _load_tables(chips.resolve(profile.source_chip), None)[0]
        verdicts = diagnose_last_byte(image, table, src)
        stuck = sorted(i for i, v in verdicts.items() if v == "no stop")
        self.assertTrue(stuck, "the fixture must have an unterminated phrase")
        return dumps, raw, stuck

    def test_undeclared_it_is_refused_and_says_what_to_do(self):
        dumps, raw, _stuck = self.unterminated_set()
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        message = str(caught.exception)
        self.assertIn("stop frame", message)
        self.assertIn("unterminated_phrases", message)

    def test_declaring_every_phrase_allows_the_conversion(self):
        dumps, raw, stuck = self.unterminated_set()
        raw["layout"]["unterminated_phrases"] = stuck
        result = self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        self.assertGreater(result.stats["frames"], 0)

    def test_declaring_only_some_still_refuses_the_rest(self):
        """The narrow claim must not become a blanket one."""
        dumps, raw, stuck = self.unterminated_set()
        if len(stuck) < 2:
            self.skipTest("fixture has only one unterminated phrase")
        raw["layout"]["unterminated_phrases"] = stuck[:1]
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        message = str(caught.exception)
        self.assertIn("stop frame", message)
        for index in stuck[1:]:
            self.assertIn(str(index), message)

    def test_declaring_a_phrase_that_DOES_terminate_is_refused(self):
        """The field is a claim about the ROM, not a switch."""
        raw = copy.deepcopy(self.raw)
        raw["layout"]["unterminated_phrases"] = [0]
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(profile=Profile(raw, "<x>"))
        self.assertIn("do end in a stop frame", str(caught.exception))

class TestPhrasesThatConvertNothing(WorkflowFixture):
    """A phrase whose FIRST frame is a stop frame is refused.

    It reports as clean and terminated and changes not one byte, so every check
    downstream passes it: frame kinds are trivially preserved and the
    reconciliation only counts bytes that changed. Erased space reads as 0xFF,
    which IS a stop frame, so this is what a pointer one entry past the end of
    a table finds -- the shape of the Fathom defect.

    There is no threshold involved: a real phrase says something, so its first
    frame is never the one that ends it.
    """

    def hollow_set(self):
        """Phrase 1's bytes replaced by a stop frame, then unrelated data.

        Not all-fill: that case has its own, clearer refusal, and this test
        would otherwise be checking that one instead.
        """
        from synthetic import original
        from synthetic_game import _phrase
        dumps, raw = build()
        span = len(_phrase(original(), 7, 40, True))
        data = bytearray(dumps["U4"])
        data[0] = 0xFF                                   # an immediate stop
        for i in range(1, span):
            data[i] = (i * 7) & 0xFF                     # arbitrary, not fill
        dumps["U4"] = bytes(data)
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        return dumps, raw

    def test_it_is_refused(self):
        dumps, raw = self.hollow_set()
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        message = str(caught.exception)
        self.assertIn("convert nothing", message)
        self.assertNotIn("fill bytes", message)

    def test_naming_it_silent_does_not_get_round_it(self):
        """`silent_phrases` cannot excuse it: this guard runs first.

        A lone stop frame is not silence. It is a phrase that was never found,
        and no claim in a profile should be able to say otherwise.
        """
        dumps, raw = self.hollow_set()
        raw["layout"]["silent_phrases"] = [1]
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        self.assertIn("convert nothing", str(caught.exception))

    def test_a_real_phrase_is_not_caught_by_it(self):
        self.assertGreater(self.convert().stats["frames"], 0)


class TestMirrorDoubleCoverage(WorkflowFixture):
    """One physical byte may not be declared by a phrase in both windows.

    A 2 KB part answers at two addresses; converting some phrases through the
    lower window and others through the mirror is legitimate and is merged. But
    if one offset is inside a phrase in EACH window, two phrases describe the
    same bytes at different alignments, only one conversion can survive into the
    burned device, and the other phrase would read as corrupt.

    Changed-bytes cannot detect this -- a conversion may leave a byte
    unchanged -- so coverage is what is tested.
    """

    def test_the_same_offset_reached_through_both_windows_is_refused(self):
        # The fixture's U4 phrases are addressed through the mirror at 0xE800.
        # Point one table entry at the SAME offset in the lower window.
        raw = copy.deepcopy(self.raw)
        device = self.profile.device_for("U5")
        at = self.profile.table_offset - (device.cpu_address
                                          - self.profile.window_base)
        dumps = dict(self.dumps)
        data = bytearray(dumps["U5"])
        # Table order is c, a, d, b -- entry 1 is the U4 phrase at 0xE800.
        data[at + 2:at + 4] = (0xE000).to_bytes(2, "big")
        dumps["U5"] = bytes(data)
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        with self.assertRaises(ConversionRefused) as caught:
            self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        message = str(caught.exception)
        self.assertIn("mirrored device", message)
        self.assertIn("two different ways", message)

    def test_the_ordinary_mirrored_set_still_converts(self):
        self.assertGreater(self.convert().stats["frames"], 0)

    def test_the_same_phrase_named_through_both_windows_is_allowed(self):
        """Overlap is not conflict when both windows want the same byte.

        Two table entries can name one physical phrase through the lower window
        and through the mirror. Same alignment, same extent, so both
        conversions demand identical output and the device can represent it.
        Refusing that would refuse a correct layout.
        """
        raw = copy.deepcopy(self.raw)
        device = self.profile.device_for("U5")
        at = self.profile.table_offset - (device.cpu_address
                                          - self.profile.window_base)
        dumps = dict(self.dumps)
        data = bytearray(dumps["U5"])
        # Entry 1 is the U4 phrase at 0xE800; entry 3 is the other U4 phrase.
        # Point entry 3 at the SAME phrase through the lower window, so the two
        # extents cover the same physical offsets at the same alignment.
        mirrored = self.profile.device_for("U4")
        entry_one = int.from_bytes(data[at + 2:at + 4], "big")
        data[at + 6:at + 8] = (entry_one - mirrored.size).to_bytes(2, "big")
        dumps["U5"] = bytes(data)
        for entry in raw["devices"]:
            entry["sha256"] = sha256(dumps[entry["socket"]])
        result = self.convert(dumps=dumps, profile=Profile(raw, "<x>"))
        self.assertGreater(result.stats["frames"], 0)

class TestSpeechRunningOffTheEndOfAListedDevice(unittest.TestCase):
    """The case a START test cannot see: a device the profile does not list.

    If a set has two speech devices and the profile lists one, every phrase it
    declares starts inside the listed device, every byte it changes is inside
    it, that device changes, and the reconciliation balances. Nothing objects,
    while the other device's speech is never converted and the user burns a set
    that is half old tables.

    Where the speech STOPS is what gives it away. A phrase whose data really
    continues into the missing device runs off the end of the mapped one and
    terminates in the 0xFF that fills unmapped space.
    """

    WINDOW, SPEECH, TABLE = 0xC000, 0xC000, 0xF000

    def build_truncated_set(self):
        """Speech that overruns its device, with the next device unlisted."""
        from synthetic import original
        from synthetic_game import _phrase
        chip = original()
        body = _phrase(chip, 7, 40, True)

        size = 0x40
        speech = bytearray(b"\xFF" * size)
        # Fill the whole device with un-terminated speech, so the stream is
        # still going when the device ends.
        run = _phrase(chip, 7, 40, False)
        while len(run) < size:
            run += _phrase(chip, 9, 12, False)
        speech[0:size] = run[:size]

        table = bytearray(b"\xFF" * 0x1000)
        table[0:2] = self.SPEECH.to_bytes(2, "big")
        table[2:4] = self.TABLE.to_bytes(2, "big")

        dumps = {"U2": bytes(speech), "U5": bytes(table)}
        raw = {
            "schema_version": 1, "profile_id": "truncated", "profile_version": 1,
            "title": "Truncated", "manufacturer": "Bally", "year": 1981,
            "board": "Squawk & Talk AS-2518-61", "source_chip": "tms5200",
            "status": "draft",
            "memory": {"window_base": self.WINDOW, "window_size": 0x4000,
                       "fill": 255},
            "devices": [
                {"socket": "U2", "label": "speech", "type": "2716",
                 "size": size, "cpu_address": self.SPEECH, "mirrored": False,
                 "holds_speech": True, "sha256": sha256(dumps["U2"])},
                {"socket": "U5", "label": "table", "type": "2532",
                 "size": 0x1000, "cpu_address": self.TABLE, "mirrored": False,
                 "holds_speech": False, "sha256": sha256(dumps["U5"])},
            ],
            "layout": {"table_offset": self.TABLE - self.WINDOW,
                       "base_address": self.WINDOW, "phrases": 1,
                       "address_ordered": True, "has_end_bound": True,
                       "truncate_last_byte": []},
            "evidence": {"layout": "constructed for this test"},
        }
        return dumps, raw

    def test_it_is_refused(self):
        """Two guards can catch this; the set must not convert either way.

        Usually the overrun bytes CHANGE, and the converted-bytes check names
        them. The terminator check is the backstop for when they happen to
        convert to themselves, which changes nothing and so is invisible to a
        byte comparison.
        """
        dumps, raw = self.build_truncated_set()
        with self.assertRaises(ConversionRefused) as caught:
            convert_set(dumps, Profile(raw, "<truncated>"),
                        chips.resolve("tms5220"))
        message = str(caught.exception)
        self.assertIn("past the end of", message)

    def test_the_terminator_check_catches_it_on_its_own(self):
        """With the byte comparison satisfied, the backstop must still fire."""
        from tms52xx import workflow
        from tms52xx.rom import patch_rom as real_patch
        dumps, raw = self.build_truncated_set()
        profile = Profile(raw, "<truncated>")
        device = profile.device_for("U2")
        end = device.cpu_address - profile.window_base + device.size

        def patch(image, table, source, target, **kwargs):
            out, results = real_patch(image, table, source, target, **kwargs)
            # Undo every change past the device, so the converted-bytes check
            # sees nothing to complain about and only the terminator is wrong.
            data = bytearray(out)
            data[end:] = image[end:]
            return bytes(data), results

        workflow.patch_rom = patch
        try:
            with self.assertRaises(ConversionRefused) as caught:
                convert_set(dumps, profile, chips.resolve("tms5220"))
        finally:
            workflow.patch_rom = real_patch
        message = str(caught.exception)
        self.assertIn("unmapped space", message)
        self.assertIn("left unconverted", message)

    def test_the_phrase_starts_inside_the_listed_device(self):
        """Otherwise the START guard would be what fires, not this one."""
        dumps, raw = self.build_truncated_set()
        profile = Profile(raw, "<truncated>")
        device = profile.device_for("U2")
        at = device.cpu_address - profile.window_base
        self.assertTrue(at <= (self.SPEECH - self.WINDOW) < at + device.size)

class TestRateControlNeedsFirmwareEvidence(WorkflowFixture):
    """A C-family target is a claim about the BOARD, not about the data.

    The TMS5220C and TSP5220C carry LPC tables identical to the TMS5220's, so
    the converted bytes are the same whichever is named. What differs is that
    they read the 0x00/0x20 opcode as SET RATE where a TMS5200 ignores it. No
    amount of looking at speech data says whether a board sends one, so the
    profile has to carry the measurement.
    """

    def profile_with(self, commands):
        raw = copy.deepcopy(self.raw)
        if commands is None:
            raw.pop("chip_commands_observed", None)
        else:
            raw["chip_commands_observed"] = commands
        return Profile(raw, "<x>")

    def test_no_evidence_refuses_a_C_family_target(self):
        for target in ("tms5220c", "tsp5220c"):
            with self.assertRaises(ConversionRefused) as caught:
                convert_set(dict(self.dumps), self.profile_with(None),
                            chips.resolve(target))
            message = str(caught.exception)
            self.assertIn("SET RATE", message)
            self.assertIn("chip_commands_observed", message)

    def test_no_evidence_still_allows_the_plain_5220(self):
        """The gate is about the C family only."""
        result = convert_set(dict(self.dumps), self.profile_with(None),
                             chips.resolve("tms5220"))
        self.assertGreater(result.stats["frames"], 0)

    def test_evidence_without_a_rate_opcode_allows_it(self):
        result = convert_set(dict(self.dumps), self.profile_with(["0x60"]),
                             chips.resolve("tsp5220c"))
        self.assertGreater(result.stats["frames"], 0)

    def test_evidence_containing_a_rate_opcode_refuses_it(self):
        for opcode in ("0x00", "0x20", "0x2F"):
            with self.assertRaises(ConversionRefused) as caught:
                convert_set(dict(self.dumps),
                            self.profile_with(["0x60", opcode]),
                            chips.resolve("tms5220c"))
            self.assertIn("SET RATE", str(caught.exception))

    def test_the_override_is_explicit_and_works(self):
        result = convert_set(dict(self.dumps), self.profile_with(None),
                             chips.resolve("tsp5220c"),
                             allow_unverified_rate_control=True)
        self.assertGreater(result.stats["frames"], 0)

    def test_every_bundled_profile_carries_the_evidence(self):
        """Otherwise a C-family conversion of a shipped set would be refused."""
        from tms52xx.profiles import available
        for profile in available():
            self.assertTrue(profile.chip_commands_observed,
                            "%s records no command evidence" % profile.id)
            risky = [c for c in profile.chip_commands_observed
                     if (c & 0x70) in chips.Chip.SET_RATE_OPCODES]
            self.assertEqual(risky, [], profile.id)


class TestMirroredReconciliationIsHonest(WorkflowFixture):
    """Physical-device bytes and CPU-image bytes are different counts."""

    def aliased_set(self):
        """One phrase named through BOTH windows of the mirrored device."""
        raw = copy.deepcopy(self.raw)
        u5 = self.profile.device_for("U5")
        u4 = self.profile.device_for("U4")
        at = self.profile.table_offset - (u5.cpu_address
                                          - self.profile.window_base)
        dumps = dict(self.dumps)
        data = bytearray(dumps["U5"])
        entry = int.from_bytes(data[at + 2:at + 4], "big")
        data[at + 6:at + 8] = (entry - u4.size).to_bytes(2, "big")
        dumps["U5"] = bytes(data)
        for device in raw["devices"]:
            device["sha256"] = sha256(dumps[device["socket"]])
        return dumps, Profile(raw, "<x>")

    def test_the_two_counts_differ_and_both_are_reported(self):
        dumps, profile = self.aliased_set()
        result = convert_set(dumps, profile, self.target)
        physical = sum(e["changed_bytes"] for e in result.outputs)
        windows = sum(e["window_changed_bytes"] for e in result.outputs)
        self.assertNotEqual(physical, windows,
                            "the fixture must exercise the mirror")
        # The image total reconciles with the WINDOW total, never the physical.
        self.assertEqual(windows, result.stats["bytes_changed"])

    def test_a_device_merged_from_both_windows_says_so(self):
        dumps, profile = self.aliased_set()
        result = convert_set(dumps, profile, self.target)
        u4 = next(e for e in result.outputs if e["socket"] == "U4")
        self.assertEqual(u4["source_window"], "merged")

    def test_a_device_taken_only_from_its_mirror_says_that_instead(self):
        result = self.convert()
        u4 = next(e for e in result.outputs if e["socket"] == "U4")
        self.assertEqual(u4["source_window"], "mirror")
        self.assertTrue(u4["taken_from_mirror"])


class TestCoverageMeasuresConsumedBytes(WorkflowFixture):
    """The percentage must describe the ROM, not the pointer table."""

    def test_a_huge_declared_extent_does_not_inflate_it(self):
        """A phrase bounded far past its speech must not read as full coverage.

        Point the last phrase's bound at the table instead of at the next
        phrase: its declared extent grows enormously while the speech inside it
        is unchanged, so a declared-extent metric would jump and a consumed-byte
        metric must not.
        """
        before = self.convert()
        u5_before = next(e for e in before.outputs
                         if e["socket"] == "U5")["speech_coverage_percent"]

        raw = copy.deepcopy(self.raw)
        raw["layout"]["has_end_bound"] = False
        raw["layout"]["phrases"] = raw["layout"]["phrases"]
        after = convert_set(dict(self.dumps), Profile(raw, "<x>"), self.target)
        u5_after = next(e for e in after.outputs
                        if e["socket"] == "U5")["speech_coverage_percent"]
        self.assertAlmostEqual(u5_before, u5_after, places=1)

    def test_it_is_a_share_of_the_physical_device_not_the_window(self):
        """The divisor is the part's own size, not the window it answers in.

        A 2 KB device mirrored into a 4 KB window used to be divided by 4096,
        so a fully converted part could not read above 50% however complete the
        layout was. Asserted as the arithmetic rather than as a magnitude, so
        the fixture's own size cannot make it vacuous.
        """
        from tms52xx.bitstream import parse
        from tms52xx.rom import PhraseTable
        from tms52xx.workflow import _load_tables
        result = self.convert()
        device = self.profile.device_for("U4")
        self.assertTrue(device.mirrored)
        at = device.cpu_address - self.profile.window_base
        span = device.size * 2
        table = PhraseTable.from_pointers(
            result.before, self.profile.table_offset, self.profile.phrases,
            address_ordered=self.profile.address_ordered,
            has_end_bound=self.profile.has_end_bound,
            base_address=self.profile.base_address)
        src = _load_tables(chips.resolve(self.profile.source_chip), None)[0]
        physical = set()
        for phrase in table.phrases:
            frames, stopped = parse(
                bytes(result.before[phrase.start:phrase.end]),
                src.pitch_bits, list(src.k_widths))
            used = ((frames[-1].end_bit + 7) // 8) if frames else 0
            if not stopped:
                used = phrase.end - phrase.start
            for off in range(phrase.start, min(phrase.start + used, phrase.end)):
                if at <= off < at + span:
                    physical.add((off - at) % device.size)
        u4 = next(e for e in result.outputs if e["socket"] == "U4")
        self.assertAlmostEqual(u4["speech_coverage_percent"],
                               round(100.0 * len(physical) / device.size, 1),
                               places=1)
        self.assertTrue(physical, "the fixture must convert something in U4")

    def test_it_never_exceeds_one_hundred(self):
        for entry in self.convert().outputs:
            coverage = entry.get("speech_coverage_percent")
            if coverage is not None:
                self.assertLessEqual(coverage, 100.0)

class TestOutputContainmentIsIndependent(WorkflowFixture):
    """The second layer of the path defence, tested with the first removed.

    The profile loader restricts socket and type to safe identifiers, so in
    normal use no dangerous name reaches the writer. That makes the containment
    check unreachable through the front door -- and an untested guard is one
    nobody knows still works. This drives it directly by making `output_name`
    return a name the loader would never have allowed.
    """

    def test_a_name_with_a_separator_is_refused_before_anything_is_written(self):
        import tempfile
        from tms52xx import cli as cli_mod
        from tms52xx import workflow as workflow_mod
        real = workflow_mod.output_name

        def escaping(source_name, device, target, custom_tables=False):
            return ".." + os.sep + real(source_name, device, target,
                                        custom_tables)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("in", "out", "profiles"):
                (root / name).mkdir()
            u4 = root / "in" / "841-01_4.716"
            u5 = root / "in" / "841-02_5.532"
            u4.write_bytes(self.dumps["U4"])
            u5.write_bytes(self.dumps["U5"])
            write_profile(root / "profiles", self.raw)

            workflow_mod.output_name = escaping
            os.environ["UNDERSTUDY_PROFILE_DIR"] = str(root / "profiles")
            try:
                with self.assertRaises(SystemExit) as caught:
                    cli_mod.main(["convert-set", str(u4), str(u5),
                                  "--target", "tms5220",
                                  "-o", str(root / "out")])
            finally:
                workflow_mod.output_name = real
                os.environ.pop("UNDERSTUDY_PROFILE_DIR", None)

            self.assertIn("leaves the output directory", str(caught.exception))
            # And nothing was written anywhere, inside or outside.
            self.assertEqual(list((root / "out").iterdir()), [])
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ["in", "out", "profiles"])



class TestRunningFromAClone(unittest.TestCase):
    """`python understudy.py` is the documented path, so it is tested.

    Nothing is installed and nothing is built: the tool is pure standard
    library, and the launcher exists only because the code lives under `src/`,
    which Python does not search unless told to. That makes the launcher the
    first thing a new user touches and the easiest thing to break silently.
    """

    def run_launcher(self, *args, cwd=None):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)          # prove it needs no help
        env.pop("UNDERSTUDY_PROFILE_DIR", None)
        return subprocess.run([sys.executable, str(ROOT / "understudy.py"),
                               *args],
                              cwd=str(cwd or ROOT), capture_output=True,
                              text=True, env=env)

    def test_it_runs_with_nothing_installed_and_no_PYTHONPATH(self):
        result = self.run_launcher("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("understudy", result.stdout)

    def test_the_bundled_profiles_are_found_from_a_clone(self):
        result = self.run_launcher("profiles")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("embryon", result.stdout)

    def test_it_names_the_invocation_the_reader_actually_used(self):
        """Telling a clone user to run `understudy` sends them hunting.

        Driven through the unrecognised-set path, which prints a command for
        the reader to run next -- the place where naming the wrong entry point
        actually costs them something.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            here = Path(directory)
            (here / "u4.bin").write_bytes(bytes(2048))
            (here / "u5.bin").write_bytes(bytes(4096))
            result = self.run_launcher("identify", str(here / "u4.bin"),
                                       str(here / "u5.bin"), cwd=here)
        combined = result.stdout + result.stderr
        self.assertIn("understudy.py", combined,
                      "the printed command must name the launcher actually "
                      "used, not a command that is not on the reader's PATH")
        for line in combined.splitlines():
            if "inspect <image>" in line:
                self.assertNotIn("  understudy inspect", line)
                break
        else:
            self.fail("expected the manual path to be suggested")


class TestSuggestedCommandIsCopyPasteable(WorkflowFixture):
    """`identify` prints a command to copy. It has to survive being copied."""

    def test_a_filename_with_spaces_is_quoted(self):
        """Real dumps carry names like "... EPROM U3 06-20-1984.BIN".

        Unquoted, that becomes four arguments and the command fails on the
        line after the tool said it had identified the set.
        """
        import shlex
        from tms52xx.cli import shell_quote
        spaced = "Big_Bat_Baseball_Sound EPROM U3 06-20-1984.BIN"
        quoted = shell_quote(spaced)
        self.assertNotEqual(quoted, spaced, "a spaced name must be quoted")
        if os.name != "nt":
            self.assertEqual(shlex.split(quoted), [spaced])

    def test_an_ordinary_filename_is_left_alone(self):
        from tms52xx.cli import shell_quote
        for plain in ("841-01_4.716", "u4.bin", "U5.532"):
            self.assertEqual(shell_quote(plain), plain)

    def test_the_printed_command_round_trips_through_the_shell(self):
        import shlex
        from tms52xx.cli import shell_quote
        if os.name == "nt":
            self.skipTest("POSIX shell semantics")
        names = ["Big_Bat_Baseball_Sound EPROM U3 06-20-1984.BIN", "u4.bin"]
        line = " ".join(shell_quote(n) for n in names)
        self.assertEqual(shlex.split(line), names)

if __name__ == "__main__":
    unittest.main(verbosity=2)
