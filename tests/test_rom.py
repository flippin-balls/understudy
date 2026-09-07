"""ROM patching: in place, bounded, and loud about layout mistakes."""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original, understudy                 # noqa: E402
from tms52xx.rom import (Phrase, PhraseResult, PhraseTable,    # noqa: E402
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

    def test_reports_clamping_with_exact_counts(self):
        """Exact numbers, from a phrase built to clamp a known count.

        `clamped_percent >= 0` holds for any number the summary could produce,
        including one from a summariser that had stopped counting, so the
        counts are asserted exactly.
        """
        longest = max(range(len(self.src.pitch)),
                      key=lambda i: self.src.pitch[i])
        reachable = max(p for p in self.dst.pitch if p)
        # Two frames beyond the target's reach, one comfortably inside it.
        # An index inside the target's range that it cannot hold EXACTLY, so
        # the frame is approximated rather than clamped or unchanged.
        low = next(i for i in range(1, len(self.src.pitch))
                   if 0 < self.src.pitch[i] <= reachable
                   and self.src.pitch[i] not in self.dst.pitch)
        body = stream(self.src, [(7, 0, longest, list(range(10))),
                                 (8, 0, longest, list(range(10))),
                                 (9, 0, low, list(range(10))),
                                 (0xF, 0, 0, [])])
        rom = bytearray(6)
        for i, value in enumerate([6, 6 + len(body)]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom += body
        table = PhraseTable.from_pointers(bytes(rom), 0, 1)

        _out, results = patch_rom(bytes(rom), table, self.src, self.dst)
        summary = summarise(results)
        self.assertEqual(summary["phrases"], 1)
        self.assertEqual(summary["frames"], 4)
        self.assertEqual(summary["frames_clamped"], 2)
        self.assertEqual(summary["frames_approximated"], 1)
        self.assertAlmostEqual(summary["clamped_percent"], 50.0)
        self.assertEqual(results[0].clamped, 2)

    def test_truncated_convention_leaves_the_final_byte_alone(self):
        """Comparing the two whole outputs for inequality is not the right test:
        the excluded byte can convert to itself by coincidence, and then a
        correct implementation looks broken. What must hold is that under the
        truncated convention the last ROM byte of every phrase is untouched,
        because the player never transmits it.
        """
        # allow_unterminated: this fixture's final bytes carry the stop frame,
        # so truncating removes the terminator. That is the guard doing its job
        # and is tested elsewhere; here the subject is which BYTES get written.
        out, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                           truncate_last_byte=True, allow_unterminated=True)
        for phrase in self.table.phrases:
            self.assertEqual(out[phrase.end - 1], self.rom[phrase.end - 1],
                             "phrase %d's untransmitted final byte was written"
                             % phrase.index)

    def test_running_the_conversion_twice_moves_the_indexes_again(self):
        """The trap the documentation warns about, demonstrated not asserted.

        A second source->target pass reads already-converted indexes as though
        they were source indexes and moves them a second time. The result stays
        the same length and still parses, so nothing about the file reveals it;
        only knowing which image you started from does.
        """
        once, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        twice, _ = patch_rom(once, self.table, self.src, self.dst)
        self.assertNotEqual(once, twice)
        self.assertEqual(len(once), len(twice))

    def test_converting_a_rom_to_its_own_tables_is_refused(self):
        """A no-op the user cannot have meant, so it is an error rather than a
        silent rewrite of a ROM with itself."""
        once, _ = patch_rom(self.rom, self.table, self.src, self.dst)
        with self.assertRaises(ValueError) as caught:
            patch_rom(once, self.table, self.dst, self.dst)
        self.assertIn("identical tables", str(caught.exception))



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


class TestLibraryFailsClosed(RomFixture):
    """The refusal lives in the library, not only in the command line.

    A caller who imports `patch_rom` gets the same protection as one who runs
    the CLI. Safety implemented only at the command line is safety that the
    people most likely to automate this do not get.
    """

    def test_patch_rom_refuses_an_unterminated_phrase(self):
        # Truncating a phrase whose final byte carries the stop frame removes
        # the terminator, which is the cheapest way to produce the condition.
        with self.assertRaises(ValueError) as caught:
            patch_rom(self.rom, self.table, self.src, self.dst,
                      truncate_last_byte=True)
        self.assertIn("do not end in a stop frame", str(caught.exception))

    def test_the_override_is_available(self):
        out, results = patch_rom(self.rom, self.table, self.src, self.dst,
                                 truncate_last_byte=True,
                                 allow_unterminated=True)
        self.assertEqual(len(out), len(self.rom))
        self.assertFalse(all(r.stopped_cleanly for r in results))

    def test_a_clean_conversion_needs_no_override(self):
        out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        self.assertTrue(all(r.stopped_cleanly for r in results))
        self.assertNotEqual(out, self.rom)

    def test_frame_kinds_are_checked_against_the_written_output(self):
        _out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        for r in results:
            self.assertEqual(r.kinds_preserved, r.frames,
                             "phrase %d changed a frame kind" % r.phrase.index)


class TestEveryPhraseIsReported(RomFixture):
    """A declared phrase always produces a result, or the run fails.

    Silently dropping one would take its stop-frame check with it: the
    conversion would report success over fewer phrases than the layout
    declared, and the manifest would not show the difference.
    """

    def _one_byte_phrase_rom(self):
        body = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        rom = bytearray(6)
        # Phrase 0 is a single byte; phrase 1 is the rest.
        for i, value in enumerate([6, 7, 7 + len(body)]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom += b"\x00" + body
        return bytes(rom)

    def test_a_phrase_with_nothing_left_to_convert_is_an_error(self):
        rom = self._one_byte_phrase_rom()
        table = PhraseTable.from_pointers(rom, 0, 2)
        self.assertEqual(table.phrases[0].length, 1)
        with self.assertRaises(ValueError) as caught:
            patch_rom(rom, table, self.src, self.dst, truncate_last_byte=[0],
                      allow_unterminated=True)
        self.assertIn("no convertible bytes", str(caught.exception))

    def test_every_phrase_declared_produces_a_result(self):
        """Including duplicates, which share an extent but not an identity."""
        _out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        self.assertEqual(len(results), len(self.table.phrases))
        self.assertEqual([r.phrase.index for r in results],
                         [p.index for p in self.table.phrases])

        a_start = self.table.phrases[0].start
        b_start = self.table.phrases[1].start
        rom = bytearray(self.rom)
        for i, value in enumerate([a_start, a_start, b_start]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        duplicated = PhraseTable.from_pointers(bytes(rom), 0, 2,
                                               address_ordered=False)
        _out, results = patch_rom(bytes(rom), duplicated, self.src, self.dst)
        self.assertEqual([r.phrase.index for r in results], [0, 1])


class TestDuplicatePointerAccounting(RomFixture):
    """Two commands naming one phrase must not be counted as two phrases.

    The bytes are converted once, but summing per-phrase totals across the alias
    would double every physical quantity in the manifest.
    """

    def _duplicated(self):
        a_start = self.table.phrases[0].start
        b_start = self.table.phrases[1].start
        rom = bytearray(self.rom)
        for i, value in enumerate([a_start, a_start, b_start]):
            rom[2 * i:2 * i + 2] = value.to_bytes(2, "big")
        rom = bytes(rom)
        return rom, PhraseTable.from_pointers(rom, 0, 2, address_ordered=False)

    def test_totals_reconcile_with_the_bytes_that_actually_changed(self):
        rom, table = self._duplicated()
        out, results = patch_rom(rom, table, self.src, self.dst)
        summary = summarise(results)
        actual = sum(1 for a, b in zip(rom, out) if a != b)
        self.assertEqual(summary["bytes_changed"], actual)

    def test_both_commands_are_still_reported(self):
        """Deduplicating must not cost a command its identity."""
        rom, table = self._duplicated()
        _out, results = patch_rom(rom, table, self.src, self.dst)
        self.assertEqual([r.phrase.index for r in results], [0, 1])
        self.assertIsNone(results[0].alias_of)
        self.assertEqual(results[1].alias_of, 0)
        self.assertEqual(results[1].phrase.start, results[0].phrase.start)

    def test_the_summary_distinguishes_commands_from_phrases(self):
        rom, table = self._duplicated()
        _out, results = patch_rom(rom, table, self.src, self.dst)
        summary = summarise(results)
        self.assertEqual(summary["phrases"], 2)
        self.assertEqual(summary["distinct_phrases"], 1)

    def test_frames_are_not_counted_twice(self):
        rom, table = self._duplicated()
        _out, results = patch_rom(rom, table, self.src, self.dst)
        solo = PhraseTable.from_pointers(rom, 0, 1, address_ordered=False)
        _out, solo_results = patch_rom(rom, solo, self.src, self.dst)
        self.assertEqual(summarise(results)["frames"],
                         summarise(solo_results)["frames"])

    def test_totals_reconcile_without_duplicates_too(self):
        """Guards the fix: the ordinary path must not have been broken."""
        out, results = patch_rom(self.rom, self.table, self.src, self.dst)
        actual = sum(1 for a, b in zip(self.rom, out) if a != b)
        self.assertEqual(summarise(results)["bytes_changed"], actual)
        self.assertEqual(summarise(results)["distinct_phrases"], 2)


class TestSummaryStatistics(RomFixture):
    def test_median_is_the_true_median_for_an_even_count(self):
        """`errors[len // 2]` is the upper middle value, not the median.

        With an even number of samples it overstates a documented measurement,
        which is the number a reader is most likely to quote.
        """
        results = [PhraseResult(phrase=self.table.phrases[0], frames=1,
                                clamped=0, approximated=0, truncated=0,
                                stopped_cleanly=True, changed_bytes=0,
                                f0_errors=(1.0, 2.0, 3.0, 10.0))]
        summary = summarise(results)
        self.assertEqual(summary["f0_error_hz"]["median"], 2.5)
        self.assertEqual(summary["f0_error_hz"]["mean"], 4.0)
        self.assertEqual(summary["f0_error_hz"]["max"], 10.0)
        self.assertEqual(summary["f0_error_hz"]["frames"], 4)

    def test_median_for_an_odd_count(self):
        results = [PhraseResult(phrase=self.table.phrases[0], frames=1,
                                clamped=0, approximated=0, truncated=0,
                                stopped_cleanly=True, changed_bytes=0,
                                f0_errors=(1.0, 4.0, 100.0))]
        self.assertEqual(summarise(results)["f0_error_hz"]["median"], 4.0)

    def test_no_f0_section_when_nothing_was_voiced(self):
        results = [PhraseResult(phrase=self.table.phrases[0], frames=1,
                                clamped=0, approximated=0, truncated=0,
                                stopped_cleanly=True, changed_bytes=0)]
        self.assertNotIn("f0_error_hz", summarise(results))


class TestTableAbovePhrases(unittest.TestCase):
    """The pointer table does not have to sit below the speech it points at.

    On a Squawk & Talk the table commonly lives in one ROM socket and the
    phrases in another at a LOWER address -- Embryon's table is at CPU $FC1C in
    U5 while its speech starts at $E800 in U4. Two things follow:

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


class TestTableBetweenPhrases(unittest.TestCase):
    """A pointer table can sit BETWEEN the speech, not only above or below it.

    Fathom does exactly that: entries 0-26 point below the table at $FA6F and
    entry 27 points above it at $FAD3. Without clamping every phrase at the
    table, the phrase below runs through the table to reach the one above --
    which is refused as an overlap, so the whole layout is unusable and the
    speech above the table is never converted.
    """

    def setUp(self):
        self.src, self.dst = original(), understudy()
        a = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        b = stream(self.src, [(9, 0, 12, list(range(10))), (0xF, 0, 0, [])])
        # speech, gap, TABLE, gap, more speech
        self.low = 4
        self.table_at = 0x100
        self.high = 0x180
        rom = bytearray(b"\x00" * 0x200)
        rom[self.low:self.low + len(a)] = a
        rom[self.high:self.high + len(b)] = b
        for i, value in enumerate([self.low, self.high]):
            rom[self.table_at + 2 * i:self.table_at + 2 * i + 2] = \
                value.to_bytes(2, "big")
        self.rom = bytes(rom)

    def test_a_phrase_below_the_table_stops_at_it(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          address_ordered=False,
                                          has_end_bound=False)
        low = next(p for p in table.phrases if p.start == self.low)
        self.assertEqual(low.end, self.table_at,
                         "the phrase below ran through the pointer table")

    def test_the_phrase_above_the_table_is_still_reachable(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          address_ordered=False,
                                          has_end_bound=False)
        high = next(p for p in table.phrases if p.start == self.high)
        self.assertEqual(high.end, len(self.rom))

    def test_the_table_survives_patching(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          address_ordered=False,
                                          has_end_bound=False)
        out, _results = patch_rom(self.rom, table, self.src, self.dst)
        self.assertEqual(out[self.table_at:self.table_at + 4],
                         self.rom[self.table_at:self.table_at + 4])

    def test_both_phrases_actually_convert(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          address_ordered=False,
                                          has_end_bound=False)
        out, results = patch_rom(self.rom, table, self.src, self.dst)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertGreater(r.changed_bytes, 0,
                               "phrase %d converted nothing" % r.phrase.index)

    def test_address_ordered_layouts_are_clamped_too(self):
        table = PhraseTable.from_pointers(self.rom, self.table_at, 2,
                                          address_ordered=True,
                                          has_end_bound=False)
        low = next(p for p in table.phrases if p.start == self.low)
        self.assertEqual(low.end, self.table_at)


class TestLastByteConvention(RomFixture):
    """The final-byte convention is per phrase, and is read off the data."""

    def test_truncation_can_be_selected_per_phrase(self):
        """A single ROM set can use both conventions, so one flag is not enough."""
        only_second, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                                   truncate_last_byte=[1],
                                   allow_unterminated=True)
        all_of_them, _ = patch_rom(self.rom, self.table, self.src, self.dst,
                                   truncate_last_byte=True,
                                   allow_unterminated=True)
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
                                  truncate_last_byte=[1],
                                  allow_unterminated=True)
        self.assertEqual([r.last_byte_truncated for r in results], [False, True])

    def test_an_unknown_phrase_index_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_rom(self.rom, self.table, self.src, self.dst,
                      truncate_last_byte=[99])

    def test_diagnosis_gives_the_exact_verdict_for_a_known_phrase(self):
        """Built to be `required`, and asserted to be exactly that.

        "either required or spare" holds for every phrase that has a stop
        frame at all, so the exact verdict is asserted instead.
        """
        body = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        for pad, expected in ((0, "required"), (1, "spare"), (2, "spare")):
            data = body + b"\x00" * pad
            rom = bytes(4) + data
            table = PhraseTable(phrases=[Phrase(0, 4, 4 + len(data))])
            self.assertEqual(diagnose_last_byte(rom, table, self.src)[0],
                             expected, "pad=%d" % pad)

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


class PointerPairTable(unittest.TestCase):
    """Tables that store both bounds of every phrase, as Centaur's does.

    Reading such a table as a list of starts is the failure this form exists to
    prevent: every other pointer IS a real phrase start, so the wrong reading
    produces phrases that all parse and terminate while describing half the ROM.
    """

    def setUp(self):
        self.src = original()
        body = stream(self.src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        self.body = body
        # Three phrases with a gap between them, then the table after them.
        # The gaps matter: with the phrases laid end to end, every end pointer
        # equals the next start pointer and the two readings coincide. Real
        # sets are not all contiguous -- Medusa's are not -- and the gap is what
        # makes a misread visible.
        step = len(body) + 4
        self.starts = [0x10, 0x10 + step, 0x10 + 2 * step]
        self.table_at = 0x10 + 3 * step
        rom = bytearray(self.table_at + 3 * 4 + 8)
        for start in self.starts:
            rom[start:start + len(body)] = body
        for i, start in enumerate(self.starts):
            at = self.table_at + 4 * i
            rom[at:at + 2] = start.to_bytes(2, "big")
            rom[at + 2:at + 4] = (start + len(body)).to_bytes(2, "big")
        self.rom = bytes(rom)

    def table(self, count=3, rom=None):
        return PhraseTable.from_pointer_pairs(rom or self.rom, self.table_at,
                                              count)

    def test_each_record_gives_one_phrase_with_both_its_bounds(self):
        phrases = self.table().phrases
        self.assertEqual([p.start for p in phrases], self.starts)
        self.assertEqual([p.end for p in phrases],
                         [s + len(self.body) for s in self.starts])

    def test_reading_a_pair_table_as_starts_invents_phrases_and_does_not_raise(self):
        """The motivating failure, demonstrated rather than asserted.

        Read as starts, every END pointer becomes a phrase too, so the table
        describes twice as many phrases as exist and the invented ones cover
        whatever lies between the real ones -- fill, padding, or code. Nothing
        raises: that is what makes this form worth supporting rather than
        detecting.
        """
        as_starts = PhraseTable.from_pointers(
            self.rom, self.table_at, 6, address_ordered=False,
            has_end_bound=False)
        self.assertEqual(len(as_starts.phrases), 6)
        self.assertNotEqual([p.start for p in as_starts.phrases], self.starts)
        real = {(p.start, p.end) for p in self.table().phrases}
        read = {(p.start, p.end) for p in as_starts.phrases}
        # Twice the phrases, and the extra ones are not speech at all.
        self.assertEqual(len(as_starts.phrases), 2 * len(self.starts))
        self.assertTrue(read - real, "the misreading must invent phrases")
        for start, end in read - real:
            self.assertNotIn(start, self.starts)

    def test_a_record_whose_end_precedes_its_start_is_refused(self):
        rom = bytearray(self.rom)
        at = self.table_at
        rom[at:at + 2] = (self.starts[1]).to_bytes(2, "big")
        rom[at + 2:at + 4] = (self.starts[0]).to_bytes(2, "big")
        with self.assertRaises(ValueError) as caught:
            self.table(rom=bytes(rom))
        self.assertIn("(start, end) pairs", str(caught.exception))

    def test_a_record_pointing_outside_the_rom_is_refused(self):
        rom = bytearray(self.rom)
        rom[self.table_at:self.table_at + 2] = (0xFFFF).to_bytes(2, "big")
        with self.assertRaises(ValueError) as caught:
            self.table(rom=bytes(rom))
        self.assertIn("outside", str(caught.exception))

    def test_a_phrase_overlapping_the_table_is_refused(self):
        """Patching it would rewrite the table that describes it."""
        rom = bytearray(self.rom)
        rom[self.table_at + 2:self.table_at + 4] = (
            self.table_at + 4).to_bytes(2, "big")
        with self.assertRaises(ValueError) as caught:
            self.table(rom=bytes(rom))
        self.assertIn("overlaps the pointer table", str(caught.exception))

    def test_a_table_running_past_the_end_of_the_rom_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.table(count=64)
        self.assertIn("runs past the end", str(caught.exception))

    def test_records_are_four_bytes_not_two(self):
        """A pair table of N phrases occupies 4N bytes.

        Off-by-a-factor-of-two here would read the second half of the table as
        phrases, which is exactly what a plain-starts reading does.
        """
        with self.assertRaises(ValueError):
            PhraseTable.from_pointer_pairs(self.rom[:self.table_at + 4 * 3 - 1],
                                           self.table_at, 3)
        self.assertEqual(len(self.table().phrases), 3)

    def test_conversion_through_a_pair_table_stays_in_place(self):
        patched, results = patch_rom(self.rom, self.table(), self.src,
                                     understudy())
        self.assertEqual(len(patched), len(self.rom))
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.stopped_cleanly for r in results))
        changed = [i for i, (a, b) in enumerate(zip(self.rom, patched))
                   if a != b]
        self.assertTrue(changed)
        self.assertTrue(all(any(p.start <= i < p.end
                                for p in self.table().phrases)
                            for i in changed))


class AllowUnterminatedByName(unittest.TestCase):
    """`allow_unterminated` takes a list, so one phrase can be excused alone.

    A blanket `True` excuses every phrase in the set, which is the wrong shape
    for a ROM with exactly one phrase the player has to terminate: it would
    also excuse a second, unnoticed one -- and an unterminated phrase is what a
    layout aimed at code looks like.
    """

    def setUp(self):
        self.src = original()
        # Two phrases, neither carrying a stop frame.
        body = stream(self.src, [(7, 0, 40, list(range(10)))])
        self.span = len(body)
        rom = bytearray(4 + 2 * self.span)
        rom[4:4 + self.span] = body
        rom[4 + self.span:4 + 2 * self.span] = body
        self.rom = bytes(rom)
        self.table = PhraseTable(phrases=[
            Phrase(0, 4, 4 + self.span),
            Phrase(1, 4 + self.span, 4 + 2 * self.span)])

    def patch(self, allow):
        return patch_rom(self.rom, self.table, self.src, understudy(),
                         allow_unterminated=allow)

    def test_neither_phrase_terminates(self):
        with self.assertRaises(ValueError) as caught:
            self.patch(False)
        message = str(caught.exception)
        self.assertIn("2 of 2", message)
        self.assertIn("phrase 0", message)

    def test_naming_one_still_refuses_the_other(self):
        with self.assertRaises(ValueError) as caught:
            self.patch([0])
        message = str(caught.exception)
        self.assertIn("1 of 2", message)
        self.assertIn("phrase 1", message)

    def test_naming_both_converts(self):
        _patched, results = self.patch([0, 1])
        self.assertEqual(len(results), 2)
        self.assertFalse(any(r.stopped_cleanly for r in results))

    def test_true_still_excuses_everything(self):
        _patched, results = self.patch(True)
        self.assertEqual(len(results), 2)

    def test_an_empty_list_excuses_nothing(self):
        with self.assertRaises(ValueError):
            self.patch([])


if __name__ == "__main__":
    unittest.main(verbosity=0)
