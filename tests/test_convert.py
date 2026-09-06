"""Conversion behaviour, including the frames the TMS5220 cannot reproduce."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy                    # noqa: E402
from tms52xx import K_FIELDS, convert_stream, nearest_index, parse  # noqa: E402
from tms52xx.convert import convert_frames                    # noqa: E402
from tms52xx.tables import ChipTables                         # noqa: E402


def build(chip, frames):
    bits = []

    def put(value, width):
        bits.extend((value >> (width - 1 - i)) & 1 for i in range(width))

    for energy, repeat, pitch, ks in frames:
        put(energy, 4)
        if energy in (0x0, 0xF):
            continue
        put(repeat, 1)
        put(pitch, chip.pitch_bits)
        if repeat:
            continue
        for i in range(10 if pitch else 4):
            put(ks[i], chip.k_widths[i])
    data = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            data[i // 8] |= 1 << (i % 8)
    return bytes(data)


class TestNearest(unittest.TestCase):
    def test_picks_the_closest_entry(self):
        self.assertEqual(nearest_index(11, [0, 10, 20, 30]), 1)

    def test_ties_go_to_the_lower_index_deterministically(self):
        self.assertEqual(nearest_index(15, [0, 10, 20, 30]), 1)


class TestConversion(unittest.TestCase):
    def setUp(self):
        self.src = original()
        self.dst = understudy()

    def test_conversion_preserves_length_exactly(self):
        """The property that makes in-place ROM patching possible."""
        data = build(self.src, [(7, 0, 10, list(range(10))),
                                (9, 0, 0, [1, 2, 3, 4]),
                                (0xF, 0, 0, [])])
        out, _r, _ = convert_stream(data, self.src, self.dst)
        self.assertEqual(len(out), len(data))

    def test_refuses_a_matched_pair_that_is_not_the_52xx_grammar(self):
        """Agreeing with each other is not enough; they must be 52xx.

        Two table files that share a 5-bit pitch field pass the "same widths"
        check, and without a grammar check the tool would happily re-index them
        while presenting the result as a TMS52xx conversion. The frames of a
        51xx part do not have this layout, so the output would be nonsense.
        """
        from synthetic import K_WIDTHS
        def narrow(name):
            return ChipTables(name=name, pitch_bits=5, k_widths=K_WIDTHS,
                              energy=list(self.dst.energy),
                              pitch=[0] + [20 + i for i in range(31)],
                              k=[list(v) for v in self.dst.k])
        with self.assertRaises(ValueError) as caught:
            convert_stream(b"\x00", narrow("a"), narrow("b"))
        self.assertIn("not the TMS52xx frame grammar", str(caught.exception))

    def test_refuses_chips_with_different_field_widths(self):
        """Re-indexing is only valid within a family that shares the layout."""
        from synthetic import K_WIDTHS
        narrow = ChipTables(name="fake-51xx", pitch_bits=5, k_widths=K_WIDTHS,
                            energy=list(self.dst.energy),
                            pitch=[0] + [20 + i for i in range(31)],
                            k=[list(v) for v in self.dst.k])
        with self.assertRaises(ValueError):
            convert_stream(b"\x00", self.src, narrow)

    def test_output_parses_at_the_target_width(self):
        data = build(self.src, [(7, 0, 10, list(range(10))), (0xF, 0, 0, [])])
        out, _report, _ = convert_stream(data, self.src, self.dst)
        frames, stopped = parse(out, self.dst.pitch_bits, self.dst.k_widths)
        self.assertTrue(stopped)
        self.assertEqual(frames[0].kind, "voiced")

    def test_frame_kinds_survive_conversion(self):
        data = build(self.src, [(7, 0, 10, list(range(10))),
                                (9, 0, 0, [1, 2, 3, 4]),
                                (5, 1, 8, []),
                                (0x0, 0, 0, []),
                                (0xF, 0, 0, [])])
        out, _r, _ = convert_stream(data, self.src, self.dst)
        before = [f.kind for f in parse(data, self.src.pitch_bits,
                                        self.src.k_widths)[0]]
        after = [f.kind for f in parse(out, self.dst.pitch_bits,
                                       self.dst.k_widths)[0]]
        self.assertEqual(before, after)

    def test_unvoiced_stays_unvoiced(self):
        """Pitch index 0 must never be converted into a voiced frame."""
        data = build(self.src, [(9, 0, 0, [1, 2, 3, 4]), (0xF, 0, 0, [])])
        out, _r, _ = convert_stream(data, self.src, self.dst)
        frames, _ = parse(out, self.dst.pitch_bits, self.dst.k_widths)
        self.assertEqual(frames[0].kind, "unvoiced")
        self.assertEqual(frames[0].pitch, 0)

    def test_reachable_pitch_converts_without_clamping(self):
        """A mid-range period exists on both parts and should map cleanly."""
        index = 10
        data = build(self.src, [(7, 0, index, list(range(10))), (0xF, 0, 0, [])])
        _out, report, _ = convert_stream(data, self.src, self.dst)
        record = report[0]
        self.assertIsNotNone(record.source_f0)
        self.assertLess(abs(record.f0_error_hz), 3.0)

    def test_lowest_pitch_is_clamped_and_reported(self):
        """The point of the project: some frames have nowhere to map to.

        The stand-in part's period table stops shorter than the original's, so
        the lowest-pitched frames cannot be represented. Conversion must not
        pretend otherwise -- it must clamp AND say so.
        """
        lowest = len(self.src.pitch) - 1          # longest period = lowest f0
        data = build(self.src, [(7, 0, lowest, list(range(10))), (0xF, 0, 0, [])])
        _out, report, _ = convert_stream(data, self.src, self.dst)
        record = report[0]
        self.assertTrue(record.pitch_clamped)
        self.assertGreater(record.target_f0, record.source_f0,
                           "clamping to a shorter period must raise f0")

    def test_approximation_is_not_reported_as_clamping(self):
        """A period the target can nearly reach is not "at the floor".

        Conflating the two overstates the damage badly: on real tables a sweep
        across the pitch range produces one frame genuinely at the floor and
        several approximated by under 3 Hz. Reporting all of them as clamped
        would tell an operator the conversion is far worse than it is.
        """
        # Search for an index the target CANNOT hold exactly. Picking the
        # middle of the table and hoping was the earlier approach, and the
        # middle index happens to have an exact counterpart, so the positive
        # assertion below could never have held.
        reachable = max(p for p in self.dst.pitch if p)
        mid = next(i for i in range(1, len(self.src.pitch))
                   if 0 < self.src.pitch[i] <= reachable
                   and self.src.pitch[i] not in self.dst.pitch)
        data = build(self.src, [(7, 0, mid, list(range(10))), (0xF, 0, 0, [])])
        _out, report, _ = convert_stream(data, self.src, self.dst)
        record = report[0]
        self.assertFalse(record.pitch_clamped,
                         "a mid-range period was reported as at the floor")
        # ...and the positive half, without which this passes even if
        # approximation reporting were deleted outright.
        self.assertTrue(record.pitch_approximated,
                        "a period the target cannot hold exactly was not "
                        "reported as approximated")
        self.assertIsNotNone(record.f0_error_hz)
        self.assertNotEqual(self.src.pitch[mid],
                            self.dst.pitch[record.fields["pitch"]])

    def test_only_periods_beyond_the_ceiling_count_as_clamped(self):
        longest_target = max(p for p in self.dst.pitch if p)
        lowest = len(self.src.pitch) - 1
        self.assertGreater(self.src.pitch[lowest], longest_target,
                           "fixture no longer exercises the ceiling")
        data = build(self.src, [(7, 0, lowest, list(range(10))), (0xF, 0, 0, [])])
        _out, report, _ = convert_stream(data, self.src, self.dst)
        self.assertTrue(report[0].pitch_clamped)
        self.assertFalse(report[0].pitch_approximated,
                         "a frame cannot be both clamped and approximated")

    def test_the_stand_in_cannot_reach_the_original_floor(self):
        """States the constraint as an assertion rather than a comment."""
        self.assertGreater(self.dst.lowest_f0_hz, self.src.lowest_f0_hz)


class TestTableValidation(unittest.TestCase):
    def test_rejects_a_pitch_table_that_does_not_match_its_width(self):
        with self.assertRaises(ValueError):
            ChipTables(name="bad", pitch_bits=6, k_widths=[5, 5, 4, 4, 4, 4, 4, 3, 3, 3],
                       energy=[0] * 16, pitch=[0] * 32,
                       k=[[0] * (1 << w) for w in [5, 5, 4, 4, 4, 4, 4, 3, 3, 3]])

    def test_rejects_an_impossible_pitch_width(self):
        with self.assertRaises(ValueError):
            ChipTables(name="bad", pitch_bits=7, k_widths=[5, 5, 4, 4, 4, 4, 4, 3, 3, 3],
                       energy=[0] * 16, pitch=[0] * 128,
                       k=[[0] * (1 << w) for w in [5, 5, 4, 4, 4, 4, 4, 3, 3, 3]])

    def test_pitch_index_zero_has_no_frequency(self):
        self.assertIsNone(original().f0_hz(0))


class TestTruncatedFrames(unittest.TestCase):
    """A frame whose fields run off the end is left exactly as it was found.

    `parse` supplies zero bits past the end of the buffer so a truncated final
    frame still parses. Converting one is the trap: the fields that fit get
    re-indexed and written back, while the invented tail is discarded, so the
    frame emerges neither original nor converted. Since the stream is
    length-preserved in place, that silently corrupts real ROM bytes.
    """

    def setUp(self):
        self.src, self.dst = original(), understudy()

    def _stream(self):
        from test_rom import stream
        return stream(self.src, [(7, 0, 40, list(range(10))),
                                 (9, 0, 12, list(range(10)))])

    def test_truncated_frame_bytes_are_untouched(self):
        full = self._stream()
        data = full[:-1]                       # chop the last byte
        out, report, _stopped = convert_stream(data, self.src, self.dst)

        truncated = [r for r in report if r.skipped_truncated]
        self.assertEqual(len(truncated), 1)
        self.assertEqual(truncated[0].index, 1)
        self.assertEqual(truncated[0].fields, {})

        # The first frame converted, so the call did real work...
        self.assertNotEqual(out, data)
        # ...but every byte from the truncated frame's first bit onward is
        # identical to the input. Frame 0 is 50 bits, so byte 6 (bit 48) is the
        # first byte the truncated frame can reach.
        self.assertEqual(out[7:], data[7:])
        self.assertEqual(len(out), len(data))

    def test_every_truncation_length_is_safe(self):
        """Not one hand-picked cut: every cut leaves a valid, same-length stream."""
        full = self._stream()
        for cut in range(1, len(full)):
            data = full[:len(full) - cut]
            out, report, _ = convert_stream(data, self.src, self.dst)
            self.assertEqual(len(out), len(data), "cut=%d" % cut)
            for record in report:
                if record.skipped_truncated:
                    self.assertEqual(record.fields, {}, "cut=%d" % cut)


class TestIndexGuards(unittest.TestCase):
    """Reserved index values are never produced by a nearest-value search.

    Energy 0 is silence and energy 15 is the stop frame; pitch 0 is unvoiced.
    None of the three is an amplitude or a period, so a table whose nearest
    entry happens to be one of them must not be chosen -- converting a voiced
    frame into an unvoiced one, or an ordinary frame into a stop, truncates
    everything after it in the stream.
    """

    def test_energy_never_converts_to_silence_or_stop(self):
        self.assertNotIn(nearest_index(0, [0, 5, 9] + [99] * 13, forbid=(0, 15)),
                         (0, 15))
        table = [0] + [1] * 14 + [0]
        self.assertNotIn(nearest_index(0, table, forbid=(0, 15)), (0, 15))

    def test_pitch_never_converts_to_unvoiced(self):
        self.assertNotEqual(nearest_index(0, [0, 20, 40], forbid=(0,)), 0)

    def test_a_fully_forbidden_table_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            nearest_index(5, [1, 2], forbid=(0, 1))

    def test_a_hostile_energy_table_cannot_produce_a_stop_frame(self):
        """The guard is for TABLES A USER SUPPLIES, so test it with one.

        With the real 52xx tables the nearest entry is never a reserved index,
        so the guard never fires and a test using them proves nothing about the
        call site. These tables are valid -- 16 energy entries, pitch[0] == 0 --
        but place a reserved index right next to the value being matched, which
        is exactly the situation the guard exists to survive.
        """
        src = original()
        hostile = ChipTables(
            name="hostile", pitch_bits=src.pitch_bits,
            k_widths=list(src.k_widths),
            # index 15 (STOP) is the nearest entry to every source energy;
            # every legal index is far away.
            energy=[0] + [1000] * 14 + [src.energy[3]],
            pitch=list(src.pitch), k=[list(v) for v in src.k])
        frames, _ = parse(_one_frame(src, 3, 40), src.pitch_bits,
                          list(src.k_widths))
        convert_frames(frames, src, hostile)
        self.assertNotIn(frames[0].fields["energy"].index, (0, 15))

    def test_a_hostile_pitch_table_cannot_unvoice_a_frame(self):
        """Index 0 means unvoiced; choosing it would drop the K5-K10 fields."""
        src = original()
        hostile = ChipTables(
            name="hostile", pitch_bits=src.pitch_bits,
            k_widths=list(src.k_widths), energy=list(src.energy),
            # 0 (unvoiced) is numerically nearest to any short period here.
            pitch=[0] + [1000] * (len(src.pitch) - 1),
            k=[list(v) for v in src.k])
        frames, _ = parse(_one_frame(src, 7, 40), src.pitch_bits,
                          list(src.k_widths))
        self.assertEqual(frames[0].kind, "voiced")
        convert_frames(frames, src, hostile)
        self.assertNotEqual(frames[0].fields["pitch"].index, 0)

    def test_real_conversion_never_emits_a_reserved_index(self):
        """The guarantee end to end, over every source index, not just a unit."""
        src, dst = original(), understudy()
        for energy in range(1, 15):
            for pitch in (0, 1, 20, 40, 63):
                frames, _ = parse(
                    _one_frame(src, energy, pitch), src.pitch_bits,
                    list(src.k_widths))
                convert_frames(frames, src, dst)
                # Only the frame actually built above. Padding a stream to a
                # byte boundary appends zero bits, which parse correctly reads
                # as a trailing SILENCE frame -- its energy index is 0 by
                # definition, and asserting over it tests the padding, not the
                # guard.
                subject = frames[0]
                self.assertEqual(subject.kind,
                                 "voiced" if pitch else "unvoiced")
                got = subject.fields["energy"].index
                self.assertNotIn(got, (0, 15), "energy %d -> %d" % (energy, got))
                if pitch:
                    self.assertNotEqual(subject.fields["pitch"].index, 0,
                                        "voiced frame %d went unvoiced" % pitch)


def _one_frame(chip, energy, pitch):
    from test_rom import stream
    return stream(chip, [(energy, 0, pitch, list(range(10)))])


class TestTableValidation(unittest.TestCase):
    """Table files are user-supplied, so they are checked, not trusted."""

    def _tables(self, **overrides):
        base = original()
        kwargs = {"name": base.name, "pitch_bits": base.pitch_bits,
                  "k_widths": list(base.k_widths),
                  "energy": list(base.energy), "pitch": list(base.pitch),
                  "k": [list(v) for v in base.k]}
        kwargs.update(overrides)
        return ChipTables(**kwargs)

    def test_energy_must_have_sixteen_entries(self):
        with self.assertRaises(ValueError):
            self._tables(energy=[0] * 15)

    def test_pitch_index_zero_must_be_unvoiced(self):
        table = list(original().pitch)
        table[0] = 40
        with self.assertRaises(ValueError):
            self._tables(pitch=table)

    def test_pitch_must_contain_a_usable_period(self):
        with self.assertRaises(ValueError):
            self._tables(pitch=[0] * 64)

    def test_a_zero_period_anywhere_is_rejected(self):
        """Not just index 0. A zero at index 7 unvoices frames and divides by 0."""
        table = list(original().pitch)
        table[7] = 0
        with self.assertRaises(ValueError) as caught:
            self._tables(pitch=table)
        self.assertIn("index 7", str(caught.exception))

    def test_boolean_tables_are_rejected(self):
        """`True == 1` in Python, so booleans pass every numeric check."""
        table = list(original().pitch)
        table[7] = True
        with self.assertRaises(ValueError):
            self._tables(pitch=table)
        k = [list(v) for v in original().k]
        k[0][3] = False
        with self.assertRaises(ValueError):
            self._tables(k=k)

    def test_non_integer_tables_are_rejected(self):
        table = list(original().pitch)
        table[7] = 20.5
        with self.assertRaises(ValueError):
            self._tables(pitch=table)
        table[7] = "20"
        with self.assertRaises(ValueError):
            self._tables(pitch=table)

    def test_signed_k_values_are_accepted(self):
        """Real reflection coefficients run to about -501; do not reject them."""
        k = [list(v) for v in original().k]
        k[0][0] = -501
        self._tables(k=k)

    def test_periods_cannot_be_negative(self):
        table = list(original().pitch)
        table[5] = -1
        with self.assertRaises(ValueError):
            self._tables(pitch=table)


class TestEmittedIndexes(unittest.TestCase):
    """The OUTPUT BITS must carry the converted indexes, not just the report.

    Length, frame kinds and "it still parses" are all true of a conversion that
    returned its input unchanged, so none of them constrain the arithmetic. The
    tests here compute the expected destination index for every field with an
    independent brute-force search over the target tables, then read the index
    back out of the emitted bytes.
    """

    def setUp(self):
        self.src, self.dst = original(), understudy()

    @staticmethod
    def _expected(value, table, forbid=()):
        """Nearest legal index, computed here rather than by the library.

        Ties go to the lower index, matching the documented rule that the first
        closest entry wins.
        """
        best, best_delta = None, None
        for index, entry in enumerate(table):
            if index in forbid:
                continue
            delta = abs(entry - value)
            if best_delta is None or delta < best_delta:
                best, best_delta = index, delta
        return best

    def test_every_field_of_a_voiced_frame_lands_on_the_expected_index(self):
        source_ks = [1, 2, 3, 4, 5, 6, 7, 1, 2, 3]
        data = build(self.src, [(7, 0, 20, source_ks), (0xF, 0, 0, [])])
        out, _report, _ = convert_stream(data, self.src, self.dst)
        frames, _ = parse(out, self.dst.pitch_bits, self.dst.k_widths)

        got = frames[0]
        self.assertEqual(
            got.fields["energy"].index,
            self._expected(self.src.energy[7], self.dst.energy, forbid=(0, 15)))
        self.assertEqual(
            got.fields["pitch"].index,
            self._expected(self.src.pitch[20], self.dst.pitch, forbid=(0,)))
        for i, name in enumerate(K_FIELDS):
            self.assertEqual(
                got.fields[name].index,
                self._expected(self.src.k[i][source_ks[i]], self.dst.k[i]),
                "%s did not land on the nearest target entry" % name)

    def test_energy_remaps_when_the_tables_actually_differ(self):
        """Energy conversion needs its own fixture, because the real parts agree.

        PinMAME's TMS5200 and TMS5220 energy tables are byte-identical, so
        between those two parts energy conversion is genuinely a no-op and no
        test using realistic tables can constrain it. The code path still has to
        be right -- a user may supply any pair of table files -- so this uses a
        target whose energy table is deliberately shifted.
        """
        shifted = ChipTables(
            name="shifted", pitch_bits=self.dst.pitch_bits,
            k_widths=list(self.dst.k_widths),
            # index n now holds what index n+1 used to, so most source values
            # quantise one index lower.
            energy=[0] + [v for v in list(self.src.energy)[2:15]] + [200, 0],
            pitch=list(self.dst.pitch), k=[list(v) for v in self.dst.k])
        moved = 0
        for energy in range(1, 15):
            data = build(self.src, [(energy, 0, 20, [1] * 10), (0xF, 0, 0, [])])
            out, _r, _ = convert_stream(data, self.src, shifted)
            frames, _ = parse(out, shifted.pitch_bits, shifted.k_widths)
            got = frames[0].fields["energy"].index
            self.assertEqual(got, self._expected(self.src.energy[energy],
                                                 shifted.energy, forbid=(0, 15)))
            if got != energy:
                moved += 1
        self.assertGreater(moved, 0, "the fixture did not force any remapping")

    def test_the_conversion_is_not_a_no_op(self):
        """Guards the tests above: if nothing changed they would prove nothing."""
        data = build(self.src, [(7, 0, 20, [1, 2, 3, 4, 5, 6, 7, 1, 2, 3]),
                                (0xF, 0, 0, [])])
        out, _r, _ = convert_stream(data, self.src, self.dst)
        self.assertNotEqual(out, data)

    def test_an_unvoiced_frame_converts_only_its_four_k_fields(self):
        data = build(self.src, [(9, 0, 0, [1, 2, 3, 4]), (0xF, 0, 0, [])])
        out, _r, _ = convert_stream(data, self.src, self.dst)
        frames, _ = parse(out, self.dst.pitch_bits, self.dst.k_widths)
        self.assertEqual(frames[0].kind, "unvoiced")
        self.assertEqual(sorted(n for n in frames[0].fields if n.startswith("K")),
                         ["K1", "K2", "K3", "K4"])
        for i, name in enumerate(["K1", "K2", "K3", "K4"]):
            self.assertEqual(frames[0].fields[name].index,
                             self._expected(self.src.k[i][[1, 2, 3, 4][i]],
                                            self.dst.k[i]))

    def test_a_clamped_frame_lands_on_the_target_floor(self):
        """The one case conversion cannot fix, asserted exactly.

        The source's longest period is beyond anything the target can reach, so
        the only correct answer is the target's own longest period.
        """
        longest_src = max(range(len(self.src.pitch)),
                          key=lambda i: self.src.pitch[i])
        data = build(self.src, [(7, 0, longest_src, [1] * 10), (0xF, 0, 0, [])])
        out, report, _ = convert_stream(data, self.src, self.dst)
        frames, _ = parse(out, self.dst.pitch_bits, self.dst.k_widths)
        floor_index = max(range(len(self.dst.pitch)),
                          key=lambda i: self.dst.pitch[i])
        self.assertEqual(frames[0].fields["pitch"].index, floor_index)
        self.assertTrue(report[0].pitch_clamped)
        self.assertFalse(report[0].pitch_approximated)

    def test_an_approximated_frame_is_reported_and_actually_moves(self):
        """Approximation is a real index change, and is not called clamping."""
        moved = None
        for index in range(1, len(self.src.pitch)):
            want = self.src.pitch[index]
            if want > max(p for p in self.dst.pitch if p):
                continue
            if want not in self.dst.pitch:
                moved = index
                break
        self.assertIsNotNone(moved, "no approximating index in the fixtures")

        data = build(self.src, [(7, 0, moved, [1] * 10), (0xF, 0, 0, [])])
        out, report, _ = convert_stream(data, self.src, self.dst)
        frames, _ = parse(out, self.dst.pitch_bits, self.dst.k_widths)
        expected = self._expected(self.src.pitch[moved], self.dst.pitch,
                                  forbid=(0,))
        self.assertEqual(frames[0].fields["pitch"].index, expected)
        self.assertTrue(report[0].pitch_approximated)
        self.assertFalse(report[0].pitch_clamped)
        self.assertNotEqual(self.dst.pitch[expected], self.src.pitch[moved])


if __name__ == "__main__":
    unittest.main(verbosity=2)
