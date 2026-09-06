"""ROM patching: in place, bounded, and loud about layout mistakes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy                 # noqa: E402
from tms52xx.rom import PhraseTable, patch_rom, summarise   # noqa: E402


def stream(chip, frames):
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


class RomFixture(unittest.TestCase):
    """A tiny ROM: pointer table, then two phrases, then unrelated bytes."""

    def setUp(self):
        self.src, self.dst = original(), understudy()
        a = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        b = stream(self.src, [(9, 0, 12, list(range(10))),
                              (5, 0, 0, [1, 2, 3, 4]), (0xF, 0, 0, [])])
        table_at, data_at = 0, 6
        rom = bytearray(b"\x00" * data_at)
        starts = [data_at, data_at + len(a)]
        end = data_at + len(a) + len(b)
        for i, value in enumerate(starts + [end]):
            rom[table_at + 2 * i:table_at + 2 * i + 2] = value.to_bytes(2, "big")
        rom += a + b
        self.tail = b"\xDE\xAD\xBE\xEF"
        rom += self.tail
        self.rom = bytes(rom)
        self.table = PhraseTable.from_pointers(self.rom, 0, 2)


class TestPhraseTable(RomFixture):
    def test_reads_extents_from_the_pointer_table(self):
        self.assertEqual(len(self.table.phrases), 2)
        self.assertEqual(self.table.phrases[0].start, 6)
        self.assertEqual(self.table.phrases[0].end,
                         self.table.phrases[1].start)

    def test_rejects_a_table_that_runs_off_the_end(self):
        with self.assertRaises(ValueError):
            PhraseTable.from_pointers(self.rom, len(self.rom) - 2, 8)

    def test_rejects_a_pointer_outside_the_rom(self):
        broken = bytearray(self.rom)
        broken[0:2] = (0xFFFF).to_bytes(2, "big")
        with self.assertRaises(ValueError):
            PhraseTable.from_pointers(bytes(broken), 0, 2)

    def test_command_ordered_table_is_diagnosed_not_silently_wrong(self):
        """Differencing a command-ordered table gives a negative extent."""
        swapped = bytearray(self.rom)
        first = self.rom[0:2]
        swapped[0:2] = self.rom[2:4]
        swapped[2:4] = first
        with self.assertRaises(ValueError):
            PhraseTable.from_pointers(bytes(swapped), 0, 2)

    def test_command_ordered_table_works_when_declared(self):
        swapped = bytearray(self.rom)
        first = self.rom[0:2]
        swapped[0:2] = self.rom[2:4]
        swapped[2:4] = first
        table = PhraseTable.from_pointers(bytes(swapped), 0, 2,
                                          address_ordered=False)
        self.assertEqual(len(table.phrases), 2)


class TestPatch(RomFixture):
    def test_rom_length_is_unchanged(self):
        out, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        self.assertEqual(len(out), len(self.rom))

    def test_nothing_outside_the_phrases_is_touched(self):
        out, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        self.assertEqual(out[:6], self.rom[:6], "pointer table was modified")
        self.assertEqual(out[-len(self.tail):], self.tail,
                         "bytes after the speech data were modified")

    def test_the_phrases_actually_changed(self):
        out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        self.assertNotEqual(out, self.rom)
        self.assertTrue(all(r.changed_bytes > 0 for r in results))

    def test_reports_clamping_per_phrase(self):
        _out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        summary = summarise(results)
        self.assertEqual(summary["phrases"], 2)
        self.assertGreater(summary["frames"], 0)
        self.assertGreaterEqual(summary["clamped_percent"], 0.0)

    def test_truncated_convention_leaves_the_final_byte_alone(self):
        """The guarantee that matters, asserted directly.

        Comparing the two whole outputs for inequality is not the right test:
        the excluded byte can convert to itself by coincidence, and then a
        correct implementation looks broken. What must hold is that under the
        truncated convention the last ROM byte of every phrase is untouched,
        because the player never transmits it.
        """
        out, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                           last_byte_verbatim=False)
        for phrase in self.table.phrases:
            self.assertEqual(out[phrase.end - 1], self.rom[phrase.end - 1],
                             "phrase %d's untransmitted final byte was written"
                             % phrase.index)

    def test_patching_is_idempotent_under_the_same_tables(self):
        """Converting an already-converted ROM with the same pair is stable."""
        once, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        twice, _ = patch_rom(once, self.table, self.dst, self.dst)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main(verbosity=2)
