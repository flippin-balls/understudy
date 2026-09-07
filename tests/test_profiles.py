"""Profiles: validation, assembly, mirror handling, and refusing to guess.

The failure this file exists to prevent is a profile being applied to a ROM set
it does not describe. That produces a file of the right length that is silently
wrong, so identification is by exact hash and everything short of that is
refused rather than resolved.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_game import build, write_profile               # noqa: E402
from tms52xx import chips, profiles                           # noqa: E402
from tms52xx.profiles import Profile, ProfileError, sha256    # noqa: E402


class TestChipRegistry(unittest.TestCase):
    def test_resolves_ids_and_markings(self):
        for name, expected in (("tms5200", "tms5200"), ("TMS5200NL", "tms5200"),
                               ("CD2501E", "tms5200"), ("TMC0285", "tms5200"),
                               ("tsp5220c", "tsp5220c"), ("TSP5220C", "tsp5220c"),
                               ("TMS5220C", "tms5220c"), ("tms 5220", "tms5220")):
            self.assertEqual(chips.resolve(name).id, expected, name)

    def test_unknown_chip_names_the_known_ones(self):
        with self.assertRaises(ValueError) as caught:
            chips.resolve("tms5110")
        self.assertIn("tms5220", str(caught.exception))

    def test_the_5220_family_shares_one_table(self):
        """5220, 5220C and TSP5220C: decap-verified identical LPC tables."""
        used = {chips.resolve(x).table
                for x in ("tms5220", "tms5220c", "tsp5220c")}
        self.assertEqual(used, {"tms5220"})
        loaded = [chips.resolve(x).tables()
                  for x in ("tms5220", "tms5220c", "tsp5220c")]
        for other in loaded[1:]:
            self.assertEqual(list(other.pitch), list(loaded[0].pitch))
            self.assertEqual([list(v) for v in other.k],
                             [list(v) for v in loaded[0].k])

    def test_the_source_and_target_tables_are_not_the_same(self):
        """If they were, conversion would be a no-op and nothing would say so."""
        src = chips.resolve("tms5200").tables()
        dst = chips.resolve("tms5220").tables()
        self.assertNotEqual(list(src.pitch), list(dst.pitch))

    def test_bundled_tables_have_the_expected_pitch_ceilings(self):
        """The headline numbers, read off the data actually shipped."""
        self.assertAlmostEqual(chips.resolve("tms5200").tables().lowest_f0_hz,
                               37.91, places=1)
        self.assertAlmostEqual(chips.resolve("tms5220").tables().lowest_f0_hz,
                               50.31, places=1)

    def test_bundled_tables_carry_provenance(self):
        for table in ("tms5200", "tms5220"):
            prov = chips.bundled_provenance(table)
            self.assertIsNotNone(prov, table)
            self.assertEqual(prov["license"], "BSD-3-Clause")
            self.assertIn("mame", prov["repository"])
            self.assertEqual(len(prov["source_sha256"]), 64)
            self.assertTrue(prov["copyright_holders"])

    def test_the_licence_materials_ship_beside_the_data(self):
        """BSD-3-Clause requires its notice to accompany redistribution.

        Files sitting beside the repository do not survive `pip install`, so
        they live inside the package.
        """
        for name in ("BSD-3-Clause.txt", "THIRD_PARTY_NOTICES.md"):
            path = chips.LICENSE_DIR / name
            self.assertTrue(path.exists(), path)
            self.assertTrue(path.read_text(encoding="utf-8").strip(), name)
        text = chips.notices()
        self.assertIn("BSD-3-Clause", text)
        self.assertIn("mamedev/mame", text)

    def test_the_packaged_notice_matches_the_repository_copy(self):
        """Two copies can drift; the packaged one is what users receive."""
        root = Path(ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        packaged = (chips.LICENSE_DIR / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8")
        self.assertEqual(root, packaged,
                         "THIRD_PARTY_NOTICES.md and its packaged copy differ; "
                         "run tools/sync_notices.py")
        root_licence = Path(ROOT / "LICENSES" / "BSD-3-Clause.txt").read_text(
            encoding="utf-8")
        self.assertEqual(root_licence,
                         (chips.LICENSE_DIR / "BSD-3-Clause.txt").read_text(
                             encoding="utf-8"))

    def test_the_notice_records_the_hash_of_the_data_actually_shipped(self):
        """The notice must describe THIS data, not a version of it."""
        text = chips.notices()
        for table in ("tms5200", "tms5220"):
            prov = chips.bundled_provenance(table)
            self.assertIn(prov["source_sha256"], text, table)
            self.assertIn(prov["struct"], text, table)

    def test_a_source_part_is_not_offered_as_a_target(self):
        self.assertEqual(chips.resolve("tms5200").role, "source")
        self.assertNotIn("tms5200", [c.id for c in chips.TARGETS])


class SynthProfile(unittest.TestCase):
    def setUp(self):
        self.dumps, self.raw = build()
        self.profile = Profile(copy.deepcopy(self.raw), "<synth>")

    def _broken(self, **changes):
        raw = copy.deepcopy(self.raw)
        for path, value in changes.items():
            node = raw
            parts = path.split(".")
            for key in parts[:-1]:
                node = node[int(key)] if key.isdigit() else node[key]
            last = parts[-1]
            if value is None:
                node.pop(int(last) if last.isdigit() else last, None)
            else:
                node[int(last) if last.isdigit() else last] = value
        return raw


class TestProfileValidation(SynthProfile):
    """A malformed profile must be named, not silently half-applied."""

    def test_a_good_profile_parses(self):
        self.assertEqual(self.profile.id, "synthgame")
        self.assertEqual(len(self.profile.speech_devices), 2)
        self.assertTrue(self.profile.identifiable)

    def test_schema_version_must_match(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self._broken(schema_version=99), "<x>")
        self.assertIn("schema_version", str(caught.exception))

    def test_missing_required_fields_are_named(self):
        for field in ("profile_id", "layout", "devices", "memory", "status"):
            with self.assertRaises(ProfileError) as caught:
                Profile(self._broken(**{field: None}), "<x>")
            self.assertIn(field, str(caught.exception), field)

    def test_status_must_be_a_known_value(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self._broken(status="perfect"), "<x>")
        self.assertIn("status", str(caught.exception))

    def test_a_device_that_does_not_fit_the_window_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][1]["cpu_address"] = 0xFF00     # 4 KB from 0xFF00 overruns
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("does not fit", str(caught.exception))

    def test_a_mirrored_device_must_fit_BOTH_copies(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["cpu_address"] = 0xFC00     # mirror would run off
        with self.assertRaises(ProfileError):
            Profile(raw, "<x>")

    def test_duplicate_sockets_are_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][1]["socket"] = "U4"
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("twice", str(caught.exception))

    def test_a_profile_with_no_speech_device_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        for device in raw["devices"]:
            device["holds_speech"] = False
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("holds_speech", str(caught.exception))

    def test_a_malformed_hash_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["sha256"] = "abc"
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("sha256", str(caught.exception))

    def test_truncate_indexes_must_be_real_phrases(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["truncate_last_byte"] = [99]
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("phrase index", str(caught.exception))

    def test_zero_phrases_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["phrases"] = 0
        with self.assertRaises(ProfileError):
            Profile(raw, "<x>")

    def test_a_file_that_is_not_json_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            with self.assertRaises(ProfileError) as caught:
                profiles.load_file(path)
            self.assertIn("bad.json", str(caught.exception))


class TestAssembly(SynthProfile):
    """Building the CPU's view, including the mirror, without hand-work."""

    def test_assembles_to_the_declared_window(self):
        image = self.profile.assemble(self.dumps)
        self.assertEqual(len(image), self.profile.window_size)

    def test_the_mirror_is_populated(self):
        image = self.profile.assemble(self.dumps)
        at = 0xE000 - 0xC000
        self.assertEqual(image[at:at + 0x800], image[at + 0x800:at + 0x1000])
        self.assertEqual(image[at:at + 0x800], self.dumps["U4"])

    def test_unpopulated_windows_are_filled_not_left_short(self):
        image = self.profile.assemble(self.dumps)
        self.assertEqual(set(image[:0x2000]), {self.profile.fill})

    def test_a_wrong_sized_dump_is_refused(self):
        with self.assertRaises(ProfileError) as caught:
            self.profile.assemble({"U4": self.dumps["U4"][:-1],
                                   "U5": self.dumps["U5"]})
        self.assertIn("U4", str(caught.exception))

    def test_extract_round_trips_when_nothing_changed(self):
        image = self.profile.assemble(self.dumps)
        for device in self.profile.devices:
            got = self.profile.extract(image, device, image)
            self.assertEqual(got.data, self.dumps[device.socket])
            self.assertFalse(got.changed)

    def test_extract_takes_the_half_that_changed(self):
        """A mirrored device converted through its mirror must burn the mirror."""
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        at = 0xE800 - 0xC000                      # the mirror half
        image[at] ^= 0xFF
        device = self.profile.device_for("U4")
        got = self.profile.extract(bytes(image), device, original)
        self.assertTrue(got.changed)
        self.assertTrue(got.from_mirror)
        self.assertEqual(got.data[0], self.dumps["U4"][0] ^ 0xFF)

    def test_both_mirror_halves_changing_is_refused(self):
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        image[0xE000 - 0xC000] ^= 0xFF
        image[0xE800 - 0xC000] ^= 0xFF
        with self.assertRaises(ProfileError) as caught:
            self.profile.extract(bytes(image), self.profile.device_for("U4"),
                                 original)
        self.assertIn("both mirror halves", str(caught.exception))


class TestIdentification(SynthProfile):
    """Exact hashes identify. Nothing else does."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_profile(self.dir, self.raw)

    def tearDown(self):
        self.tmp.cleanup()

    def _files(self, **overrides):
        files = {"u4.bin": self.dumps["U4"], "u5.bin": self.dumps["U5"]}
        files.update(overrides)
        return files

    def test_a_complete_set_matches(self):
        matches = profiles.identify(self._files(), self.dir)
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].complete)
        self.assertEqual(sorted(matches[0].matched), ["U4", "U5"])

    def test_one_wrong_byte_makes_it_a_partial_match(self):
        """The whole point: a near-miss must not be treated as a hit."""
        corrupt = bytearray(self.dumps["U5"])
        corrupt[10] ^= 0x01
        matches = profiles.identify(self._files(**{"u5.bin": bytes(corrupt)}),
                                    self.dir)
        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0].complete)
        self.assertEqual(matches[0].missing, ["U5"])

    def test_a_right_sized_wrong_file_does_not_match(self):
        matches = profiles.identify(
            self._files(**{"u4.bin": b"\x00" * len(self.dumps["U4"])}), self.dir)
        self.assertFalse(matches[0].complete)

    def test_unknown_dumps_match_nothing(self):
        self.assertEqual(
            profiles.identify({"x.bin": b"\x00" * 2048}, self.dir), [])

    def test_extra_unrelated_files_do_not_prevent_a_match(self):
        matches = profiles.identify(self._files(**{"junk.bin": b"\x01" * 99}),
                                    self.dir)
        self.assertTrue(matches[0].complete)

    def test_a_profile_without_hashes_never_matches(self):
        """No hashes means no automatic selection, by construction."""
        raw = copy.deepcopy(self.raw)
        raw["profile_id"] = "nohash"
        for device in raw["devices"]:
            device.pop("sha256")
        write_profile(self.dir, raw)
        matches = profiles.identify(self._files(), self.dir)
        self.assertEqual([m.profile.id for m in matches], ["synthgame"])

    def test_two_profiles_claiming_one_id_are_rejected(self):
        """`--game` is what users are told to use when a match is ambiguous.

        With duplicate ids it resolved by filename order, silently applying a
        layout nobody asked for.
        """
        other = copy.deepcopy(self.raw)
        other["profile_version"] = 2
        (self.dir / "zz-other.json").write_text(json.dumps(other))
        with self.assertRaises(ProfileError) as caught:
            profiles.available(self.dir)
        self.assertIn("claim the id", str(caught.exception))

    def test_one_file_cannot_satisfy_two_sockets(self):
        """Two sockets can hold identical bytes; one dump is still one dump."""
        raw = copy.deepcopy(self.raw)
        raw["profile_id"] = "twins"
        digest = sha256(self.dumps["U4"])
        for device in raw["devices"]:
            device["sha256"] = digest
        import shutil
        shutil.rmtree(self.dir)
        write_profile(self.dir, raw)

        matches = profiles.identify({"only-one.bin": self.dumps["U4"]}, self.dir)
        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0].complete,
                         "one file was counted as both sockets")
        self.assertEqual(len(matches[0].matched), 1)
        self.assertEqual(len(matches[0].missing), 1)

    def test_two_copies_of_that_file_do_satisfy_both(self):
        raw = copy.deepcopy(self.raw)
        raw["profile_id"] = "twins"
        digest = sha256(self.dumps["U4"])
        for device in raw["devices"]:
            device["sha256"] = digest
        import shutil
        shutil.rmtree(self.dir)
        write_profile(self.dir, raw)
        matches = profiles.identify({"a.bin": self.dumps["U4"],
                                     "b.bin": self.dumps["U4"]}, self.dir)
        self.assertTrue(matches[0].complete)
        self.assertNotEqual(matches[0].matched["U4"], matches[0].matched["U5"])

    def test_a_broken_profile_file_raises_rather_than_being_skipped(self):
        """A profile silently vanishing is how the wrong one gets picked."""
        (self.dir / "broken.json").write_text('{"schema_version": 99}')
        with self.assertRaises(ProfileError):
            profiles.identify(self._files(), self.dir)


class TestBundledEmbryonProfile(unittest.TestCase):
    """The one real profile that ships."""

    def setUp(self):
        self.profile = profiles.get("embryon")

    def test_it_parses_and_is_identifiable(self):
        self.assertEqual(self.profile.id, "embryon")
        self.assertTrue(self.profile.identifiable)
        self.assertEqual(self.profile.phrases, 21)

    def test_its_layout_matches_what_the_project_established(self):
        self.assertEqual(self.profile.table_offset, 0x3C1C)
        self.assertEqual(self.profile.base_address, 0xC000)
        self.assertFalse(self.profile.address_ordered)
        self.assertFalse(self.profile.has_end_bound)

    def test_the_mirrored_socket_is_recorded(self):
        u4 = self.profile.device_for("U4")
        self.assertTrue(u4.mirrored)
        self.assertEqual(u4.size, 2048)
        self.assertEqual(u4.device_type, "2716")

    def test_status_is_not_overclaimed(self):
        """Nothing may claim silicon verification until it has happened."""
        self.assertNotEqual(self.profile.status, "silicon-verified")
        self.assertIn("not_verified", self.profile.evidence)

    def test_every_bundled_profile_parses(self):
        found = profiles.available()
        self.assertTrue(found)
        for profile in found:
            self.assertIn(profile.status, profiles.STATUS_VALUES)
            self.assertTrue(profile.speech_devices)

    def test_no_bundled_profile_contains_rom_data(self):
        """Profiles carry facts and hashes, never contents.

        A blunt size check: a profile that grew large enough to hold speech is
        doing something it should not.
        """
        for path in profiles.BUNDLED_PROFILE_DIR.glob("*.json"):
            raw = json.loads(path.read_text())
            text = json.dumps(raw)
            self.assertLess(len(text), 8000, path.name)
            for key in ("data", "bytes", "contents", "rom", "image"):
                self.assertNotIn(key, raw, "%s: %r" % (path.name, key))


if __name__ == "__main__":
    unittest.main(verbosity=2)
