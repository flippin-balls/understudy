"""Conversion behaviour, including the case the project exists to be honest about."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy                    # noqa: E402
from tms52xx import convert_stream, nearest_index, parse      # noqa: E402
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

    def test_refuses_chips_with_different_field_widths(self):
        """Re-indexing is only valid within a family that shares the layout."""
        from synthetic import K_WIDTHS
        narrow = ChipTables(name="fake-51xx", pitch_bits=5, k_widths=K_WIDTHS,
                            energy=list(self.dst.energy), pitch=[0] * 32,
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
        mid = len(self.src.pitch) // 2
        data = build(self.src, [(7, 0, mid, list(range(10))), (0xF, 0, 0, [])])
        _out, report, _ = convert_stream(data, self.src, self.dst)
        record = report[0]
        self.assertFalse(record.pitch_clamped,
                         "a mid-range period was reported as at the floor")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
