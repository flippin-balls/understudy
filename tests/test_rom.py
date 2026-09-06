"""ROM patching: in place, bounded, and loud about layout mistakes."""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy                 # noqa: E402
from tms52xx.rom import (Phrase, PhraseTable,                  # noqa: E402
                         diagnose_last_byte,
                         patch_rom, summarise)


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
        """Comparing the two whole outputs for inequality is not the right test:
        the excluded byte can convert to itself by coincidence, and then a
        correct implementation looks broken. What must hold is that under the
        truncated convention the last ROM byte of every phrase is untouched,
        because the player never transmits it.
        """
        out, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                           truncate_last_byte=True)
        for phrase in self.table.phrases:
            self.assertEqual(out[phrase.end - 1], self.rom[phrase.end - 1],
                             "phrase %d's untransmitted final byte was written"
                             % phrase.index)

    def test_patching_is_idempotent_under_the_same_tables(self):
        """Converting an already-converted ROM with the same pair is stable."""
        once, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        twice, _ = patch_rom(once, self.table, self.dst, self.dst)
        self.assertEqual(once, twice)



class TestLayoutRefusals(RomFixture):
    """Layouts that would corrupt a ROM are rejected, not warned about."""

    def test_rejects_negative_layout_numbers(self):
        for kwargs in ({"table_offset": -1}, {"count": -1},
                       {"base_address": -1}):
            with self.assertRaises(ValueError):
                PhraseTable.from_pointers(
                    self.rom, kwargs.get("table_offset", 0),
                    kwargs.get("count", 2),
                    base_address=kwargs.get("base_address", 0))

    def test_rejects_zero_phrases(self):
        with self.assertRaises(ValueError):
            PhraseTable.from_pointers(self.rom, 0, 0)

    def test_rejects_a_phrase_that_starts_inside_the_pointer_table(self):
        """A phrase overlapping its own table would destroy it when patched."""
        rom = bytearray(self.rom)
        rom[0:2] = (2).to_bytes(2, "big")     # phrase 0 starts mid-table
        with self.assertRaises(ValueError) as caught:
            PhraseTable.from_pointers(bytes(rom), 0, 2)
        self.assertIn("pointer table", str(caught.exception))

    def test_command_ordered_keeps_command_identity(self):
        """Entry N stays phrase N; it is not renumbered into address order.

        The point of a command-ordered table is that index N is what command N
        plays. Sorting the pointers to derive extents is necessary, but carrying
        that sort into the reported order silently relabels every phrase and
        would send a caller's edit to the wrong utterance.
        """
        a_start, b_start = self.table.phrases[0].start, self.table.phrases[1].start
        end = self.table.phrases[1].end
        rom = bytearray(self.rom)
        # Command order: command 0 -> the SECOND phrase, command 1 -> the first.
        for i, value in enumerate([b_start, a_start, end]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        table = PhraseTable.from_pointers(bytes(rom), 0, 2,
                                          address_ordered=False)
        self.assertEqual(table.phrases[0].start, b_start)
        self.assertEqual(table.phrases[1].start, a_start)
        # ...and each still gets its own correct extent, not its neighbour's.
        self.assertEqual(table.phrases[0].end, end)
        self.assertEqual(table.phrases[1].end, b_start)

    def test_duplicate_pointers_are_allowed_but_converted_once(self):
        """Two commands naming one phrase is documented, and must not double-convert."""
        a_start = self.table.phrases[0].start
        b_start = self.table.phrases[1].start
        rom = bytearray(self.rom)
        for i, value in enumerate([a_start, a_start, b_start]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom = bytes(rom)
        table = PhraseTable.from_pointers(rom, 0, 2, address_ordered=False)
        self.assertEqual(table.phrases[0].start, table.phrases[1].start)
        self.assertEqual(table.phrases[0].end, table.phrases[1].end)

        out, results = patch_rom(rom, table, self.src, self.dst)
        self.assertEqual(len(results), 2)
        # Convert the same phrase alone; the shared bytes must match exactly.
        # If the duplicate were converted twice the second pass would re-index
        # already-converted values and the two images would diverge.
        solo = PhraseTable.from_pointers(rom, 0, 1, address_ordered=False)
        solo_out, _ = patch_rom(rom, solo, self.src, self.dst)
        span = slice(table.phrases[0].start, table.phrases[0].end)
        self.assertEqual(out[span], solo_out[span])

    def test_extents_are_identical_or_disjoint(self):
        """Exhaustive: no accepted layout can produce a PARTIAL overlap.

        This is the property `from_pointers` relies on instead of an overlap
        check -- a phrase byte must be converted either once or not at all, and
        two extents that share only some bytes would convert the shared ones
        twice. Rather than test one hand-made case, enumerate every small
        pointer table and assert the property over all of them, so the guarantee
        survives a future change to how extents are derived.
        """
        rom = bytes(24)
        accepted = 0
        for count in (1, 2, 3):
            for ordered in (True, False):
                for end_bound in (True, False):
                    n = count + (1 if end_bound else 0)
                    if 2 * n > len(rom):
                        continue
                    for pointers in itertools.product(range(0, 25, 2), repeat=n):
                        buf = bytearray(rom)
                        for i, value in enumerate(pointers):
                            buf[2 * i:2 * i + 2] = value.to_bytes(2, "big")
                        try:
                            table = PhraseTable.from_pointers(
                                bytes(buf), 0, count, address_ordered=ordered,
                                has_end_bound=end_bound)
                        except ValueError:
                            continue
                        accepted += 1
                        extents = [(p.start, p.end) for p in table.phrases]
                        for a, b in itertools.combinations(extents, 2):
                            if a == b:
                                continue
                            self.assertFalse(
                                a[0] < b[1] and b[0] < a[1],
                                "layout %r accepted with overlapping extents "
                                "%r and %r" % (pointers, a, b))
        self.assertGreater(accepted, 1000)   # the sweep really did exercise it


class TestTableAbovePhrases(unittest.TestCase):
    """The pointer table does not have to sit below the speech it points at.

    On a Squawk & Talk the table commonly lives in one ROM socket and the
    phrases in another at a LOWER address -- Embryon's table is at CPU $FC1C in
    U5 while its speech starts at $E800 in U4. Two things follow, and both were
    originally wrong here:

      * a phrase starting below the table is normal, not a layout error; and
      * with no end bound, the last phrase runs to the TABLE, not to the end of
        the image, because the table's own bytes are not speech.
    """

    def setUp(self):
        self.src, self.dst = original(), understudy()
        a = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        b = stream(self.src, [(9, 0, 12, list(range(10))), (0xF, 0, 0, [])])
        self.speech_at = 4
        self.table_at = self.speech_at + len(a) + len(b) + 3   # a gap, then table
        rom = bytearray(b"\x00" * self.table_at)
        rom[self.speech_at:self.speech_at + len(a)] = a
        rom[self.speech_at + len(a):self.speech_at + len(a) + len(b)] = b
        self.starts = [self.speech_at, self.speech_at + len(a)]
        for value in self.starts:
            rom += value.to_bytes(2, "big")
        rom += b"\xAA" * 6            # whatever follows the table
        self.rom = bytes(rom)

    def test_phrases_below_the_table_are_accepted(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          has_end_bound=False)
        self.assertEqual([p.start for p in table.phrases], self.starts)

    def test_the_last_phrase_stops_at_the_table_not_the_image_end(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          has_end_bound=False)
        self.assertEqual(table.phrases[-1].end, self.table_at)
        self.assertNotEqual(table.phrases[-1].end, len(self.rom))

    def test_patching_leaves_the_table_and_everything_after_it_intact(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          has_end_bound=False)
        out, _results = patch_rom(self.rom, table, self.src, self.dst)
        self.assertEqual(out[self.table_at:], self.rom[self.table_at:])
        self.assertNotEqual(out[:self.table_at], self.rom[:self.table_at])

    def test_a_phrase_that_really_covers_the_table_is_still_refused(self):
        """The check is an overlap test, so it must still fire when it should."""
        rom = bytearray(self.rom)
        # Point phrase 1 into the middle of the table's own bytes.
        rom[self.table_at + 2:self.table_at + 4] = \
            (self.table_at + 1).to_bytes(2, "big")
        with self.assertRaises(ValueError) as caught:
            PhraseTable.from_pointers(bytes(rom), self.table_at, 2,
                                      has_end_bound=False)
        self.assertIn("overlaps the pointer table", str(caught.exception))


class TestLastByteConvention(RomFixture):
    """The final-byte convention is per phrase, and is read off the data."""

    def test_truncation_can_be_selected_per_phrase(self):
        """A single ROM set can use both conventions, so one flag is not enough."""
        only_second, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                                   truncate_last_byte=[1])
        all_of_them, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                                   truncate_last_byte=True)
        none_of_them, _ = patch_rom(self.rom, self.table, self.src, self.dst)

        first, second = self.table.phrases
        # Phrase 1's last byte is untouched under both selections that include it.
        self.assertEqual(only_second[second.end - 1], self.rom[second.end - 1])
        self.assertEqual(all_of_them[second.end - 1], self.rom[second.end - 1])
        # Phrase 0's last byte is converted when it is NOT in the selection, and
        # left alone when it is -- so the selection is really per phrase.
        self.assertEqual(only_second[first.start:first.end],
                         none_of_them[first.start:first.end])
        self.assertNotEqual(only_second[:first.end], all_of_them[:first.end])

    def test_results_record_which_phrases_were_truncated(self):
        _out, results = patch_rom(self.rom, self.table, self.src, self.dst,
                                  truncate_last_byte=[1])
        self.assertEqual([r.last_byte_truncated for r in results], [False, True])

    def test_an_unknown_phrase_index_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_rom(self.rom, self.table, self.src, self.dst,
                      truncate_last_byte=[99])

    def test_diagnosis_reads_whether_the_final_byte_is_needed(self):
        verdicts = diagnose_last_byte(self.rom, self.table, self.src)
        self.assertEqual(sorted(verdicts), [0, 1])
        for index, verdict in verdicts.items():
            self.assertIn(verdict, ("required", "spare"),
                          "phrase %d: %s" % (index, verdict))

    def test_diagnosis_spots_a_phrase_with_no_stop_frame(self):
        """An extent that is not a phrase is named as such, not guessed at."""
        rom = bytearray(self.rom)
        first = self.table.phrases[0]
        rom[first.start:first.end] = b"\x11" * first.length
        verdicts = diagnose_last_byte(bytes(rom), self.table, self.src)
        self.assertEqual(verdicts[0], "no stop")

    def test_both_reachable_verdicts_really_occur(self):
        """`required` and `spare` both occur, so neither is dead.

        A stop frame is four bits, so whether the final byte is needed depends
        on where the stream happens to end. Padding a phrase by one byte moves
        it from one verdict to the other, which is the whole distinction.
        """
        body = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        got = set()
        for pad in (0, 1):
            data = body + b"\x00" * pad
            rom = bytes(4) + data
            table = PhraseTable(phrases=[Phrase(0, 4, 4 + len(data))])
            got.add(diagnose_last_byte(rom, table, self.src)[0])
        self.assertEqual(got, {"required", "spare"})


if __name__ == "__main__":
    unittest.main(verbosity=0)
