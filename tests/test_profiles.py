"""Profiles: validation, assembly, mirror handling, and refusing to guess.

The failure this file exists to prevent is a profile being applied to a ROM set
it does not describe. That produces a file of the right length that is silently
wrong, so identification is by exact hash and everything short of that is
refused rather than resolved.
"""
import copy
import hashlib
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

    #: Digests of the COEFFICIENTS ONLY -- not the file, not the provenance
    #: block, not the formatting. Pinned here so that changing the numbers has
    #: to change this file too. Without an independent expected value, the
    #: provenance tests are circular: a coordinated edit to the JSON and the
    #: notice would pass every "does the metadata agree with itself" check
    #: while shipping different coefficients.
    #:
    #: These are the values validated end to end against an original Bally
    #: Embryon ROM set, and byte-compared against both MAME and PinMAME.
    COEFFICIENT_DIGESTS = {
        "tms5200": "4fa12f1327a02822cb7b9e392b633c3b"
                   "f1dacbff88dbd42153a36518ad8367f0",
        "tms5220": "728aa528ea0ffeeb806a76c1d31f11ba"
                   "2a3006e7e96dc1f893ee812588bdca5e",
    }

    @staticmethod
    def _coefficient_digest(table):
        canon = json.dumps({"pitch_bits": table.pitch_bits,
                            "k_widths": list(table.k_widths),
                            "energy": list(table.energy),
                            "pitch": list(table.pitch),
                            "k": [list(v) for v in table.k]},
                           sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def test_the_bundled_coefficients_are_the_ones_that_were_validated(self):
        """The numbers themselves, against a pinned expectation.

        Every other provenance test asks whether the metadata agrees with
        itself. This asks whether the data is the data.
        """
        for name, expected in self.COEFFICIENT_DIGESTS.items():
            got = self._coefficient_digest(chips.resolve(name).tables())
            self.assertEqual(got, expected,
                             "%s coefficients differ from the validated set" % name)

    def test_the_two_parts_differ_where_they_are_supposed_to(self):
        """A concrete structural fact, not a hash: the pitch ceilings differ."""
        src = chips.resolve("tms5200").tables()
        dst = chips.resolve("tms5220").tables()
        self.assertEqual(max(src.pitch), 211)
        self.assertEqual(max(dst.pitch), 159)
        self.assertEqual(list(src.energy), list(dst.energy),
                         "the energy tables are identical on real 52xx parts")
        self.assertEqual(len(src.pitch), 64)
        self.assertEqual(src.pitch_bits, 6)
        self.assertEqual(dst.pitch_bits, 6)

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
        """Right length is not enough; it has to be hex."""
        for bad in ("abc", "z" * 64, "g" * 64, "-" * 64, 12345, None.__class__):
            raw = copy.deepcopy(self.raw)
            raw["devices"][0]["sha256"] = bad
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn("sha256", str(caught.exception), repr(bad))

    def test_an_uppercase_hash_is_accepted_and_normalised(self):
        raw = copy.deepcopy(self.raw)
        raw["devices"][0]["sha256"] = raw["devices"][0]["sha256"].upper()
        self.assertEqual(Profile(raw, "<x>").devices[0].sha256,
                         self.raw["devices"][0]["sha256"])

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

    def test_layout_flags_must_be_booleans_not_strings(self):
        """A truthy string would silently flip the layout."""
        for key in ("address_ordered", "has_end_bound"):
            raw = copy.deepcopy(self.raw)
            raw["layout"][key] = "false"          # truthy!
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn(key, str(caught.exception))

    def test_layout_numbers_must_be_integers(self):
        for key in ("table_offset", "phrases", "base_address"):
            raw = copy.deepcopy(self.raw)
            raw["layout"][key] = "0x3C1C"
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn(key, str(caught.exception))

    def test_device_flags_must_be_booleans(self):
        for key in ("mirrored", "holds_speech"):
            raw = copy.deepcopy(self.raw)
            raw["devices"][0][key] = "yes"
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn(key, str(caught.exception))

    def test_containers_must_be_the_right_shape(self):
        for key, value in (("devices", {}), ("layout", []), ("memory", 7)):
            raw = copy.deepcopy(self.raw)
            raw[key] = value
            with self.assertRaises(ProfileError):
                Profile(raw, "<x>")

    def test_overlapping_devices_are_rejected(self):
        """Two devices cannot answer one address."""
        raw = copy.deepcopy(self.raw)
        raw["devices"][1]["cpu_address"] = raw["devices"][0]["cpu_address"]
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("both cover", str(caught.exception))

    def test_a_mirror_overlapping_the_next_device_is_rejected(self):
        """The mirror occupies address space too, and it is easy to forget."""
        raw = copy.deepcopy(self.raw)
        # U4 is 0x800 at 0xE000 mirrored to 0xE800; put U5 at 0xE800.
        raw["devices"][1]["cpu_address"] = 0xE800
        raw["devices"][1]["size"] = 0x800
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<x>")
        self.assertIn("both cover", str(caught.exception))

    def test_applies_to_must_be_driver_names(self):
        for bad in (["ok", 7], [""], [None], ["  "]):
            raw = copy.deepcopy(self.raw)
            raw["applies_to"] = bad
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn("applies_to", str(caught.exception), repr(bad))

    def test_applies_to_defaults_to_just_this_profile(self):
        raw = copy.deepcopy(self.raw)
        raw.pop("applies_to", None)
        self.assertEqual(Profile(raw, "<x>").revisions, [raw["profile_id"]])

    def test_a_profile_id_that_is_a_path_is_rejected(self):
        """The id becomes `<outdir>/<id>.manifest.json`."""
        for bad in ("../evil", "a/b", "a\\b", "Embryon", "-x", "", "a b"):
            raw = copy.deepcopy(self.raw)
            raw["profile_id"] = bad
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<x>")
            self.assertIn("profile_id", str(caught.exception), repr(bad))

    def test_ordinary_ids_are_accepted(self):
        for good in ("embryon", "flash-gordon", "eight_ball", "m_mpac2"):
            raw = copy.deepcopy(self.raw)
            raw["profile_id"] = good
            self.assertEqual(Profile(raw, "<x>").id, good)

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

    def test_the_SAME_offset_converted_two_ways_is_refused(self):
        """One device cannot hold two different things at one offset."""
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        image[0xE000 - 0xC000] ^= 0xFF
        image[0xE800 - 0xC000] ^= 0x0F        # same offset, different result
        with self.assertRaises(ProfileError) as caught:
            self.profile.extract(bytes(image), self.profile.device_for("U4"),
                                 original)
        message = str(caught.exception)
        self.assertIn("two different ways", message)
        self.assertIn("offset 0x0", message)

    def test_different_offsets_reached_through_different_mirrors_are_merged(self):
        """A set may reach some phrases low and others high.

        A 2 KB part answers at two addresses, so both windows are the same
        device; converting offset 0x10 through the lower one and offset 0x400
        through the upper one touches two different bytes of one ROM. Eight Ball
        Deluxe is built this way. Refusing it would be refusing a correct
        layout, so the halves are merged and only a genuine collision refused.
        """
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        low = 0xE000 - 0xC000
        high = 0xE800 - 0xC000
        image[low + 0x10] ^= 0xFF             # offset 0x10, via the low window
        image[high + 0x400] ^= 0xFF           # offset 0x400, via the mirror
        got = self.profile.extract(bytes(image), self.profile.device_for("U4"),
                                   original)
        self.assertTrue(got.changed)
        self.assertEqual(len(got.data), self.profile.device_for("U4").size)
        self.assertEqual(got.data[0x10], self.dumps["U4"][0x10] ^ 0xFF)
        self.assertEqual(got.data[0x400], self.dumps["U4"][0x400] ^ 0xFF)
        # Everything else is untouched.
        for i, (a, b) in enumerate(zip(got.data, self.dumps["U4"])):
            if i not in (0x10, 0x400):
                self.assertEqual(a, b, "offset 0x%X" % i)

    def test_both_halves_converted_identically_is_not_a_conflict(self):
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        image[0xE000 - 0xC000] ^= 0xFF
        image[0xE800 - 0xC000] ^= 0xFF        # the same change
        got = self.profile.extract(bytes(image), self.profile.device_for("U4"),
                                   original)
        self.assertEqual(got.data[0], self.dumps["U4"][0] ^ 0xFF)

    def test_mirror_halves_changing_IDENTICALLY_is_accepted(self):
        """A layout may address phrases through both windows.

        The device can represent that result, so refusing it would reject a
        legitimate layout. What must be refused is the halves diverging.
        """
        image = bytearray(self.profile.assemble(self.dumps))
        original = bytes(image)
        image[0xE000 - 0xC000] ^= 0xFF
        image[0xE800 - 0xC000] ^= 0xFF        # the same change
        got = self.profile.extract(bytes(image), self.profile.device_for("U4"),
                                   original)
        self.assertTrue(got.changed)
        self.assertEqual(got.data[0], self.dumps["U4"][0] ^ 0xFF)


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
        self.assertEqual(self.profile.phrases, 20)

    def test_its_layout_matches_what_the_project_established(self):
        self.assertEqual(self.profile.table_offset, 0x3C1C)
        self.assertEqual(self.profile.base_address, 0xC000)
        self.assertFalse(self.profile.address_ordered)
        # 21 pointers: 20 phrases and a final END BOUND at $F9DA. Reading that
        # last entry as a phrase made it run into 6800 code, and converting it
        # stopped the board booting in simulation.
        self.assertTrue(self.profile.has_end_bound)

    def test_the_mirrored_socket_is_recorded(self):
        u4 = self.profile.device_for("U4")
        self.assertTrue(u4.mirrored)
        self.assertEqual(u4.size, 2048)
        self.assertEqual(u4.device_type, "2716")

    def test_the_profile_identity_is_portable(self):
        """A manifest must not record one workstation's filesystem layout."""
        self.assertEqual(self.profile.identity, "data/profiles/embryon.json")
        self.assertNotIn("/home", self.profile.identity)

    def test_a_custom_profile_reports_where_it_was_loaded_from(self):
        import tempfile
        from synthetic_game import build as build_game, write_profile as write
        with tempfile.TemporaryDirectory() as tmp:
            _dumps, raw = build_game()
            path = write(tmp, raw)
            loaded = profiles.load_file(path)
            self.assertEqual(loaded.identity, str(path))

    def test_status_is_not_overclaimed(self):
        """Nothing may claim silicon verification until it has happened."""
        self.assertNotEqual(self.profile.status, "silicon-verified")
        self.assertIn("not_verified", self.profile.evidence)

    def test_profiles_declare_the_revisions_they_serve(self):
        """One sound ROM set usually serves several game revisions.

        The 49 Squawk & Talk drivers collapse to 19 distinct sound ROM sets, so
        coverage counted in drivers and coverage counted in soundsets are very
        different numbers. Both are stated, so `applies_to` must be present and
        must include the profile's own id.
        """
        for profile in profiles.available():
            self.assertTrue(profile.applies_to,
                            "%s declares no applies_to" % profile.id)
            self.assertIn(profile.id, profile.revisions, profile.id)
            self.assertEqual(len(profile.revisions), len(set(profile.revisions)),
                             "%s repeats a revision" % profile.id)

    def test_no_two_profiles_claim_the_same_revision(self):
        """Two profiles serving one driver would make `--game` ambiguous."""
        seen = {}
        for profile in profiles.available():
            for revision in profile.revisions:
                self.assertNotIn(revision, seen,
                                 "%s and %s both claim %s"
                                 % (seen.get(revision), profile.id, revision))
                seen[revision] = profile.id

    def test_every_bundled_profile_carries_its_evidence(self):
        """Each shipped profile must say what was checked and what was not."""
        for profile in profiles.available():
            self.assertIn("independent_check", profile.evidence,
                          "%s ships without an independent frame check" % profile.id)
            self.assertIn("emulation", profile.evidence, profile.id)
            self.assertIn("not_verified", profile.evidence, profile.id)
            self.assertEqual(profile.status, "board-simulated", profile.id)

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


class EntryFormSchema(unittest.TestCase):
    """`entry_form` says what one table entry IS, and must not be guessable."""

    def setUp(self):
        _dumps, self.raw = build()

    def profile(self, **layout):
        raw = copy.deepcopy(self.raw)
        raw["layout"].update(layout)
        return raw

    def test_defaults_to_starts_so_existing_profiles_keep_their_meaning(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"].pop("entry_form", None)
        self.assertEqual(Profile(raw, "<t>").entry_form, "starts")

    def test_an_unknown_entry_form_is_refused_and_names_the_known_ones(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self.profile(entry_form="pairs"), "<t>")
        self.assertIn("start_end_pairs", str(caught.exception))

    def test_pair_form_refuses_fields_that_would_have_no_effect(self):
        """Ordering and an end bound mean nothing to a (start, end) record.

        Accepting and ignoring them would let a profile state something about
        its layout that does nothing -- and a claim nobody applies is the kind
        that later gets read as verified.
        """
        for key in ("address_ordered", "has_end_bound"):
            raw = self.profile(entry_form="start_end_pairs")
            for other in ("address_ordered", "has_end_bound"):
                raw["layout"].pop(other, None)
            raw["layout"][key] = True
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<t>")
            self.assertIn(key, str(caught.exception))

    def test_pair_form_does_not_require_ordering_fields(self):
        raw = self.profile(entry_form="start_end_pairs")
        for key in ("address_ordered", "has_end_bound"):
            raw["layout"].pop(key, None)
        self.assertEqual(Profile(raw, "<t>").entry_form, "start_end_pairs")

    def test_starts_form_still_requires_them(self):
        for key in ("address_ordered", "has_end_bound"):
            raw = copy.deepcopy(self.raw)
            raw["layout"].pop("entry_form", None)
            raw["layout"].pop(key)
            with self.assertRaises(ProfileError) as caught:
                Profile(raw, "<t>")
            self.assertIn(key, str(caught.exception))


class SilentPhraseSchema(unittest.TestCase):
    def setUp(self):
        _dumps, self.raw = build()

    def test_defaults_to_none_declared(self):
        self.assertEqual(Profile(self.raw, "<t>").silent_phrases, [])

    def test_must_be_a_list(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["silent_phrases"] = 3
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<t>")
        self.assertIn("silent_phrases", str(caught.exception))

    def test_an_index_outside_the_phrase_range_is_refused(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["silent_phrases"] = [raw["layout"]["phrases"]]
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<t>")
        self.assertIn("not a phrase index", str(caught.exception))

    def test_a_bare_string_is_refused_not_read_character_by_character(self):
        """`list("0x60")` is `["0","x","6","0"]`.

        Coercing instead of validating would turn one command into four bogus
        ones, and the rate-control gate would then read them as evidence.
        """
        raw = copy.deepcopy(self.raw)
        raw["chip_commands_observed"] = "0x60"
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<t>")
        message = str(caught.exception)
        self.assertIn("chip_commands_observed", message)
        self.assertIn("list", message)

    def test_command_evidence_must_be_byte_values(self):
        for bad in (["0xZZ"], [256], [-1], [None], [["0x60"]], [True]):
            raw = copy.deepcopy(self.raw)
            raw["chip_commands_observed"] = bad
            with self.assertRaises(ProfileError, msg="%r accepted" % bad):
                Profile(raw, "<t>")

    def test_command_evidence_accepts_hex_strings_and_ints(self):
        for good, expected in ((["0x60"], [0x60]), ([0x60], [0x60]),
                               (["0x60", "0x10"], [0x60, 0x10])):
            raw = copy.deepcopy(self.raw)
            raw["chip_commands_observed"] = good
            self.assertEqual(Profile(raw, "<t>").chip_commands_observed,
                             expected)

    def test_absent_evidence_is_None_not_an_empty_list(self):
        """None means "nobody measured"; [] would mean "measured, saw none"."""
        raw = copy.deepcopy(self.raw)
        raw.pop("chip_commands_observed", None)
        self.assertIsNone(Profile(raw, "<t>").chip_commands_observed)

    def test_a_bool_is_not_an_index(self):
        """`true` is an int in Python, and would silently mean phrase 1."""
        raw = copy.deepcopy(self.raw)
        raw["layout"]["silent_phrases"] = [True]
        with self.assertRaises(ProfileError):
            Profile(raw, "<t>")


class UnterminatedPhraseSchema(unittest.TestCase):
    def setUp(self):
        _dumps, self.raw = build()

    def test_defaults_to_none_declared(self):
        self.assertEqual(Profile(self.raw, "<t>").unterminated_phrases, [])

    def test_must_be_a_list(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["unterminated_phrases"] = 2
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<t>")
        self.assertIn("unterminated_phrases", str(caught.exception))

    def test_an_index_outside_the_phrase_range_is_refused(self):
        raw = copy.deepcopy(self.raw)
        raw["layout"]["unterminated_phrases"] = [99]
        with self.assertRaises(ProfileError) as caught:
            Profile(raw, "<t>")
        self.assertIn("not a phrase index", str(caught.exception))

class SafeDeviceIdentifiers(unittest.TestCase):
    """Socket and type end up in an output filename, so they are restricted.

    A profile can come from anywhere -- UNDERSTUDY_PROFILE_DIR exists so a
    contributor can try one before sending it -- and `output_name` builds
    "<stem>_<socket>_<type>_<target><suffix>". A socket containing a separator
    puts a burn image somewhere the user did not ask for.
    """

    ATTACKS = ["../../escaped", "..\\..\\escaped", "/etc/passwd", "U4/../../x",
               "U4/x", "U4\\x", "a:b", ".", "..", ".hidden", "U4.",
               "", "   ", "U4\x00x", "U4\n"]

    def setUp(self):
        _dumps, self.raw = build()

    def test_dangerous_sockets_are_refused(self):
        for attack in self.ATTACKS:
            raw = copy.deepcopy(self.raw)
            raw["devices"][0]["socket"] = attack
            with self.assertRaises(ProfileError, msg="socket %r accepted" % attack):
                Profile(raw, "<t>")

    def test_dangerous_device_types_are_refused(self):
        for attack in self.ATTACKS:
            raw = copy.deepcopy(self.raw)
            raw["devices"][0]["type"] = attack
            with self.assertRaises(ProfileError, msg="type %r accepted" % attack):
                Profile(raw, "<t>")

    def test_ordinary_designators_still_load(self):
        for good in ("U4", "U9", "2532", "2716", "U-4", "U_4", "27C64", "A1"):
            raw = copy.deepcopy(self.raw)
            raw["devices"][0]["socket"] = good          # never collides with U5
            raw["devices"][0]["type"] = good
            device = Profile(raw, "<t>").devices[0]
            self.assertEqual(device.socket, good)
            self.assertEqual(device.device_type, good)

    def test_no_accepted_identifier_can_build_an_escaping_name(self):
        """The property, not a list of blocked strings.

        Whatever the loader accepts must produce a single path component whose
        resolved location is inside the output directory -- checked on both
        posix and Windows path semantics, since the tool is used on Windows.
        """
        import ntpath
        import posixpath
        from tms52xx.workflow import output_name
        from tms52xx import chips
        candidates = ["U4", "U9", "2532", "A-1", "a_b", "x.y", "1", "Z9",
                      "27C64", "u4"]          # never "U5": the other device
        for value in candidates:
            raw = copy.deepcopy(self.raw)
            raw["devices"][0]["socket"] = value
            raw["devices"][0]["type"] = value
            device = Profile(raw, "<t>").devices[0]
            name = output_name("841-01_4.716", device,
                               chips.resolve("tms5220"))
            for mod in (posixpath, ntpath):
                self.assertEqual(mod.basename(name), name,
                                 "%r produced a multi-component name" % value)
                joined = mod.normpath(mod.join("/out", name))
                self.assertTrue(joined.replace("\\", "/").startswith("/out/"),
                                "%r escaped: %r" % (value, joined))


class MatchDistinguishesSpeechSetFromBurnableSet(unittest.TestCase):
    """`identify` must not call a set ready when `convert_set` will refuse it.

    `convert_set` authenticates and emits EVERY device -- one holding no speech
    is still copied out as a burn image, so it has to be hashed too. A set whose
    speech ROMs all match can therefore still be short of what conversion needs,
    and saying "complete" then, with a convert-set command printed underneath,
    is the mismatch this separates.

    Built with a device that really does hold no speech -- the one carrying the
    pointer table -- rather than by relabelling a speech device, which the
    workflow refuses for its own good reasons.
    """

    WINDOW, SPEECH, TABLE = 0xC000, 0xC000, 0xF000

    def setUp(self):
        from synthetic import original
        from synthetic_game import _phrase
        body = _phrase(original(), 7, 40, True)
        speech = bytearray(b"\xFF" * 0x800)
        speech[0:len(body)] = body
        table = bytearray(b"\xFF" * 0x1000)
        table[0:2] = self.SPEECH.to_bytes(2, "big")
        table[2:4] = (self.SPEECH + len(body)).to_bytes(2, "big")
        self.dumps = {"U2": bytes(speech), "U5": bytes(table)}
        self.raw = {
            "schema_version": 1, "profile_id": "twodev", "profile_version": 1,
            "title": "Two Device", "manufacturer": "Bally", "year": 1981,
            "board": "Squawk & Talk AS-2518-61", "source_chip": "tms5200",
            "status": "draft", "chip_commands_observed": ["0x60"],
            "memory": {"window_base": self.WINDOW, "window_size": 0x4000,
                       "fill": 255},
            "devices": [
                {"socket": "U2", "label": "speech", "type": "2716",
                 "size": 0x800, "cpu_address": self.SPEECH, "mirrored": False,
                 "holds_speech": True, "sha256": sha256(self.dumps["U2"])},
                {"socket": "U5", "label": "table", "type": "2532",
                 "size": 0x1000, "cpu_address": self.TABLE, "mirrored": False,
                 "holds_speech": False, "sha256": sha256(self.dumps["U5"])},
            ],
            "layout": {"table_offset": self.TABLE - self.WINDOW,
                       "base_address": self.WINDOW, "phrases": 1,
                       "address_ordered": True, "has_end_bound": True,
                       "truncate_last_byte": []},
            "evidence": {"layout": "constructed for this test"},
        }

    def matches(self, files):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "twodev.json"
            path.write_text(json.dumps(self.raw), encoding="utf-8")
            return profiles.identify(files, directory=directory)

    def test_speech_only_is_identified_but_not_burnable(self):
        found = self.matches({"speech.bin": self.dumps["U2"]})
        self.assertEqual(len(found), 1)
        match = found[0]
        self.assertTrue(match.complete, "the speech ROM does identify the set")
        self.assertFalse(match.burnable, "but the set is not complete")
        self.assertEqual(match.unsupplied, ["U5"])

    def test_the_full_set_is_both(self):
        found = self.matches({"speech.bin": self.dumps["U2"],
                              "table.bin": self.dumps["U5"]})
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].complete)
        self.assertTrue(found[0].burnable)
        self.assertEqual(found[0].unsupplied, [])

    def test_burnable_predicts_exactly_what_convert_set_accepts(self):
        """The invariant behind the fix, checked both ways."""
        from tms52xx import chips
        from tms52xx.workflow import ConversionRefused, convert_set
        cases = [({"U2": self.dumps["U2"]}, {"speech.bin": self.dumps["U2"]}),
                 ({"U2": self.dumps["U2"], "U5": self.dumps["U5"]},
                  {"speech.bin": self.dumps["U2"],
                   "table.bin": self.dumps["U5"]})]
        seen = set()
        for supplied, files in cases:
            match = self.matches(files)[0]
            try:
                convert_set(dict(supplied), Profile(copy.deepcopy(self.raw),
                                                    "<t>"),
                            chips.resolve("tms5220"))
                worked = True
            except ConversionRefused:
                worked = False
            seen.add(worked)
            self.assertEqual(match.burnable, worked,
                             "burnable=%s but convert_set worked=%s"
                             % (match.burnable, worked))
        self.assertEqual(seen, {True, False}, "both outcomes must be exercised")



if __name__ == "__main__":
    unittest.main(verbosity=2)
