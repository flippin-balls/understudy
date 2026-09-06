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


if __name__ == "__main__":
    unittest.main(verbosity=2)
