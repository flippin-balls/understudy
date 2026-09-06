"""Frame grammar, bit ordering, and the round-trip that proves the bit map."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original                                  # noqa: E402
from tms52xx import ENERGY_SILENCE, ENERGY_STOP, parse, rebuild  # noqa: E402
from tms52xx.bitstream import BitReader, set_bits                # noqa: E402


class TestBitOrder(unittest.TestCase):
    def test_bits_leave_the_byte_lsb_first(self):
        """0x01 is bit 0. Reading MSB-first per byte is the classic mistake."""
        self.assertEqual(BitReader(bytes([0x01])).read(1), 1)
        self.assertEqual(BitReader(bytes([0x80])).read(1), 0)

    def test_fields_assemble_msb_first(self):
        # bits 0..3 of 0b1011 -> read as a 4-bit field, MSB-first, is 0b1101.
        self.assertEqual(BitReader(bytes([0b00001011])).read(4), 0b1101)

    def test_reads_past_the_end_are_zero_not_an_error(self):
        reader = BitReader(bytes([0xFF]))
        self.assertEqual(reader.read(8), 0xFF)
        self.assertEqual(reader.read(8), 0)      # the FIFO reads dry as zeroes

    def test_set_bits_round_trips_through_bit_reader(self):
        buf = bytearray(4)
        set_bits(buf, 3, 6, 0b101101)
        self.assertEqual(BitReader(bytes(buf), 3).read(6), 0b101101)

    def test_set_bits_refuses_to_run_off_the_end(self):
        with self.assertRaises(IndexError):
            set_bits(bytearray(1), 4, 8, 0xFF)


class TestFrameGrammar(unittest.TestCase):
    def setUp(self):
        self.chip = original()

    def _stream(self, *frames):
        """Build a stream from (energy, repeat, pitch, ks) tuples."""
        bits = []

        def put(value, width):
            bits.extend((value >> (width - 1 - i)) & 1 for i in range(width))

        for energy, repeat, pitch, ks in frames:
            put(energy, 4)
            if energy in (ENERGY_STOP, ENERGY_SILENCE):
                continue
            put(repeat, 1)
            put(pitch, self.chip.pitch_bits)
            if repeat:
                continue
            count = 10 if pitch else 4
            for i in range(count):
                put(ks[i], self.chip.k_widths[i])
        data = bytearray((len(bits) + 7) // 8)
        for i, bit in enumerate(bits):
            if bit:
                data[i // 8] |= 1 << (i % 8)
        return bytes(data)

    def test_stop_frame_ends_the_stream(self):
        data = self._stream((ENERGY_STOP, 0, 0, []))
        frames, stopped = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertTrue(stopped)
        self.assertEqual([f.kind for f in frames], ["stop"])

    def test_silence_frame_carries_only_energy(self):
        data = self._stream((ENERGY_SILENCE, 0, 0, []), (ENERGY_STOP, 0, 0, []))
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(frames[0].kind, "silence")
        self.assertEqual(frames[0].bit_length, 4)

    def test_unvoiced_frame_carries_four_k_values(self):
        data = self._stream((7, 0, 0, [1, 2, 3, 4]), (ENERGY_STOP, 0, 0, []))
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(frames[0].kind, "unvoiced")
        self.assertIsNotNone(frames[0].index_of("K4"))
        self.assertIsNone(frames[0].index_of("K5"))

    def test_voiced_frame_carries_ten(self):
        data = self._stream((7, 0, 20, list(range(10))), (ENERGY_STOP, 0, 0, []))
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(frames[0].kind, "voiced")
        self.assertIsNotNone(frames[0].index_of("K10"))

    def test_repeat_frame_ends_after_pitch(self):
        data = self._stream((7, 1, 20, []), (ENERGY_STOP, 0, 0, []))
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(frames[0].kind, "repeat")
        self.assertIsNone(frames[0].index_of("K1"))
        self.assertEqual(frames[0].bit_length, 4 + 1 + self.chip.pitch_bits)

    def test_truncated_final_frame_rebuilds_without_error(self):
        """A stream cut mid-frame must rebuild to its own length, not raise.

        Players that never transmit a phrase's final ROM byte produce exactly
        this: the last frame claims bits the data does not contain. `parse`
        supplies zeroes for them and `rebuild` must not write them back.
        """
        data = self._stream((7, 0, 20, list(range(10))))[:-1]
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertTrue(any(f.truncated for f in frames))
        self.assertEqual(len(rebuild(frames, len(data), base=data)), len(data))

    def test_round_trip_is_byte_exact(self):
        """Rebuilding an untouched parse must reproduce the input exactly.

        This is the check that proves the BIT MAP, not merely the values: a
        field recorded at the wrong offset still parses, and still fails here.
        """
        data = self._stream((7, 0, 20, list(range(10))),
                            (9, 0, 0, [1, 2, 3, 4]),
                            (5, 1, 18, []),
                            (ENERGY_SILENCE, 0, 0, []),
                            (ENERGY_STOP, 0, 0, []))
        frames, _ = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(rebuild(frames, len(data), base=data), data)

    def test_wrong_pitch_width_desynchronises(self):
        """A 6-bit 52xx stream read at the 51xx 5-bit width misreads everything.

        Asserted on field VALUES and frame lengths rather than on frame kinds:
        with a short stream the kinds can coincide by luck while every
        coefficient underneath them is wrong, which is exactly the failure mode
        that makes a 5-bit assumption so hard to notice.
        """
        data = self._stream((7, 0, 20, list(range(10))),
                            (9, 0, 17, list(range(10))),
                            (ENERGY_STOP, 0, 0, []))
        right, _ = parse(data, 6, self.chip.k_widths)
        wrong, _ = parse(data, 5, self.chip.k_widths)

        self.assertEqual(right[0].pitch, 20)
        self.assertNotEqual(wrong[0].pitch, 20)
        self.assertNotEqual(right[0].bit_length, wrong[0].bit_length)
        self.assertNotEqual([f.index_of("K1") for f in right],
                            [f.index_of("K1") for f in wrong])


class TestPathologicalStreams(unittest.TestCase):
    """Long and degenerate inputs, where a fixed frame cap used to bite."""

    def setUp(self):
        self.chip = original()

    def test_a_very_long_silence_run_still_reaches_its_stop_frame(self):
        """50,001 bytes: two silence frames per byte, then a stop.

        A fixed 100,000-frame cap truncated this and reported `stopped=False`,
        which is indistinguishable from a genuinely unterminated phrase -- a far
        more serious condition, and one the converter refuses on. The bound is
        derived from the input instead: no frame is shorter than four bits.
        """
        data = b"\x00" * 50_000 + b"\x0F"
        frames, stopped = parse(data, self.chip.pitch_bits, self.chip.k_widths)
        self.assertTrue(stopped)
        self.assertEqual(frames[-1].kind, "stop")
        self.assertEqual(len(frames), 100_001)

    def test_an_explicit_cap_that_is_too_small_is_an_error(self):
        data = b"\x00" * 100 + b"\x0F"
        with self.assertRaises(ValueError) as caught:
            parse(data, self.chip.pitch_bits, self.chip.k_widths, max_frames=5)
        self.assertIn("max_frames", str(caught.exception))

    def test_empty_input(self):
        frames, stopped = parse(b"", self.chip.pitch_bits, self.chip.k_widths)
        self.assertEqual(frames, [])
        self.assertFalse(stopped)
        self.assertEqual(rebuild(frames, 0), b"")

    def test_a_single_stop_byte(self):
        frames, stopped = parse(b"\x0F", self.chip.pitch_bits,
                                self.chip.k_widths)
        self.assertTrue(stopped)
        self.assertEqual([f.kind for f in frames], ["stop"])

    def test_all_ones(self):
        """0xFF is a stop frame in the low nibble; it must not run away."""
        frames, stopped = parse(b"\xFF" * 64, self.chip.pitch_bits,
                                self.chip.k_widths)
        self.assertTrue(stopped)
        self.assertEqual(frames[0].kind, "stop")


class TestKnownVector(unittest.TestCase):
    """One frame written out by hand, bit by bit, from the field spec.

    Every other test in this file builds its input with a helper that shares the
    parser's assumptions, so parser and fixture can be wrong together. This one
    does not: the bit string below is transcribed from the documented frame
    grammar, and only the byte-packing rule ("bit N of the stream is bit N%8 of
    byte N//8, least significant first") is applied programmatically.

    A voiced TMS52xx frame, field by field:

        energy  4 bits  0111    ->  7
        repeat  1 bit   0
        pitch   6 bits  010100  -> 20
        K1      5 bits  00001   ->  1
        K2      5 bits  00010   ->  2
        K3      4 bits  0011    ->  3
        K4      4 bits  0100    ->  4
        K5      4 bits  0101    ->  5
        K6      4 bits  0110    ->  6
        K7      4 bits  0111    ->  7
        K8      3 bits  001     ->  1
        K9      3 bits  010     ->  2
        K10     3 bits  011     ->  3

    which is 4+1+6+5+5+4+4+4+4+4+3+3+3 = 50 bits, the documented voiced length.
    """

    BITS = ("0111" "0" "010100" "00001" "00010" "0011" "0100"
            "0101" "0110" "0111" "001" "010" "011")
    FIELDS = [("energy", 7, 0, 4), ("repeat", 0, 4, 1), ("pitch", 20, 5, 6),
              ("K1", 1, 11, 5), ("K2", 2, 16, 5), ("K3", 3, 21, 4),
              ("K4", 4, 25, 4), ("K5", 5, 29, 4), ("K6", 6, 33, 4),
              ("K7", 7, 37, 4), ("K8", 1, 41, 3), ("K9", 2, 44, 3),
              ("K10", 3, 47, 3)]

    @classmethod
    def packed(cls):
        data = bytearray((len(cls.BITS) + 7) // 8)
        for i, bit in enumerate(cls.BITS):
            if bit == "1":
                data[i // 8] |= 1 << (i % 8)
        return bytes(data)

    def test_the_vector_is_the_documented_length(self):
        self.assertEqual(len(self.BITS), 50)
        self.assertEqual(sum(w for _n, _v, _o, w in self.FIELDS), 50)

    def test_parse_recovers_every_field_at_its_stated_offset(self):
        chip = original()
        frames, stopped = parse(self.packed(), chip.pitch_bits, chip.k_widths)
        self.assertFalse(stopped)
        self.assertEqual(frames[0].kind, "voiced")
        for name, value, offset, width in self.FIELDS:
            field = frames[0].fields[name]
            self.assertEqual(field.index, value, "%s value" % name)
            self.assertEqual(field.start_bit, offset, "%s offset" % name)
            self.assertEqual(field.width, width, "%s width" % name)

    def test_rebuild_from_nothing_reproduces_the_vector(self):
        """No `base`, so the bytes can only come from the recorded bit offsets.

        With `base=data` a rebuild that ignored every field and returned the
        base unchanged would pass. Here there is nothing to return.
        """
        chip = original()
        data = self.packed()
        frames, _ = parse(data, chip.pitch_bits, chip.k_widths)
        self.assertEqual(rebuild(frames, len(data)), data)

    def test_changing_one_index_changes_exactly_the_expected_bits(self):
        """The write path is checked against a hand-computed expectation too."""
        chip = original()
        data = self.packed()
        frames, _ = parse(data, chip.pitch_bits, chip.k_widths)
        frames[0].fields["pitch"].index = 0b101011            # 43
        expected_bits = (self.BITS[:5] + "101011" + self.BITS[11:])
        expected = bytearray((len(expected_bits) + 7) // 8)
        for i, bit in enumerate(expected_bits):
            if bit == "1":
                expected[i // 8] |= 1 << (i % 8)
        self.assertEqual(rebuild(frames, len(data)), bytes(expected))
        self.assertNotEqual(rebuild(frames, len(data)), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
