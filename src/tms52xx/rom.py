"""Patch a Bally Squawk & Talk speech ROM from TMS5200 tables to TMS5220 tables.

Conversion changes index values and nothing else, so a converted phrase occupies
exactly the bytes the original did: the pointer table stays valid, phrase
boundaries stay valid, and timing is unchanged. `patch_rom` verifies the length
rather than assuming it, and re-parses its own output to confirm no frame
changed kind.

Squawk & Talk addresses phrases through a table of 16-bit big-endian pointers,
and that is the only part that generalises. The table may sit below the speech
or above it. Ordering
(address or command), whether the table carries an end bound, and whether the
player transmits each phrase's final ROM byte all vary between titles and are
not derivable from the ROM alone -- so `PhraseTable.from_pointers` takes them
explicitly rather than guessing. docs/SQUAWK_AND_TALK.md covers how to find
them, and what each one does if you get it wrong.

This module reads and writes only ROM images you already possess. It contains no
ROM data of any kind.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

from .bitstream import parse
from .convert import FrameConversion, convert_stream
from .tables import ChipTables


@dataclass(frozen=True)
class Phrase:
    """One speech stream's extent inside a ROM image."""

    index: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class PhraseTable:
    """Where the phrases are. You supply the layout; see the module docstring."""

    phrases: List[Phrase]

    @classmethod
    def from_pointer_pairs(cls, rom: bytes, table_offset: int, count: int,
                           base_address: int = 0) -> "PhraseTable":
        """Read a table of 4-byte (start, end) records into phrase extents.

        Some sets do not store a list of starts and derive each end from the
        next entry. They store both ends of every phrase, one 4-byte record per
        phrase: start high, start low, end high, end low. Centaur and Medusa are
        both built this way, and reading such a table as a list of starts
        produces phrases that are individually plausible -- every other pointer
        is a real phrase start -- while silently describing half the ROM.

        The record form carries its own bounds, so there is nothing to derive
        and no ordering to know: `address_ordered` and `has_end_bound` have no
        meaning here. Ends are used exactly as stored rather than being clamped
        at the table, because an end that runs into the table is a misread
        table, not a phrase to be trimmed -- and is refused below.
        """
        if table_offset < 0 or count < 0 or base_address < 0:
            raise ValueError("table_offset, count and base_address must be "
                             "non-negative (got %d, %d, %d)"
                             % (table_offset, count, base_address))
        if count == 0:
            raise ValueError("count must be at least 1")

        end_of_table = table_offset + count * 4
        if end_of_table > len(rom):
            raise ValueError(
                "pointer-pair table of %d records at 0x%X runs past the end of "
                "a %d-byte ROM" % (count, table_offset, len(rom)))

        phrases = []
        for i in range(count):
            at = table_offset + 4 * i
            start = int.from_bytes(rom[at:at + 2], "big") - base_address
            end = int.from_bytes(rom[at + 2:at + 4], "big") - base_address
            for name, value in (("start", start), ("end", end)):
                if not 0 <= value <= len(rom):
                    raise ValueError(
                        "record %d has %s 0x%X, outside a %d-byte ROM -- check "
                        "table_offset and base_address"
                        % (i, name, value, len(rom)))
            if end <= start:
                raise ValueError(
                    "record %d has end 0x%X <= start 0x%X. These are (start, "
                    "end) pairs; a table of plain start pointers read this way "
                    "produces exactly this." % (i, end, start))
            if start < end_of_table and table_offset < end:
                raise ValueError(
                    "phrase %d (0x%X-0x%X) overlaps the pointer table at "
                    "0x%X-0x%X; patching it would corrupt the table"
                    % (i, start, end, table_offset, end_of_table))
            phrases.append(Phrase(i, start, end))
        return cls(phrases)

    @classmethod
    def from_pointers(cls, rom: bytes, table_offset: int, count: int,
                      address_ordered: bool = True,
                      has_end_bound: bool = True,
                      base_address: int = 0) -> "PhraseTable":
        """Read a 16-bit big-endian pointer table into phrase extents.

        `count` is the number of PHRASES. With `has_end_bound`, count+1 pointers
        are read and the last is the end of the final phrase.

        `base_address` is subtracted from each pointer, for ROMs whose pointers
        are CPU addresses rather than file offsets.

        With `address_ordered=False` the pointers are sorted before bounds are
        derived, because a command-ordered table's neighbours are not adjacent
        in memory and differencing it directly produces nonsense extents.
        """
        if table_offset < 0 or count < 0 or base_address < 0:
            raise ValueError("table_offset, count and base_address must be "
                             "non-negative (got %d, %d, %d)"
                             % (table_offset, count, base_address))
        if count == 0:
            raise ValueError("count must be at least 1")

        needed = count + (1 if has_end_bound else 0)
        end_of_table = table_offset + needed * 2
        if end_of_table > len(rom):
            raise ValueError(
                "pointer table of %d entries at 0x%X runs past the end of a "
                "%d-byte ROM" % (needed, table_offset, len(rom)))

        pointers = [int.from_bytes(rom[table_offset + 2 * i:table_offset + 2 * i + 2],
                                   "big") - base_address
                    for i in range(needed)]
        for i, value in enumerate(pointers):
            if not 0 <= value <= len(rom):
                raise ValueError(
                    "pointer %d resolves to 0x%X, outside a %d-byte ROM -- "
                    "check table_offset and base_address"
                    % (i, value, len(rom)))

        # THE POINTER TABLE BOUNDS EVERY PHRASE, not just the last one.
        #
        # Its bytes are never speech, so a phrase can never span it. That
        # matters in two arrangements, and both occur in real sets:
        #
        #   table ABOVE the speech -- the last phrase has no following pointer,
        #     and running it to the end of the image would swallow the table;
        #   table BETWEEN phrases -- Fathom's sits at $FA6F with speech both
        #     below it and above it at $FAD3, so the phrase below would
        #     otherwise run through the table to reach it.
        #
        # Clamping every end at the table start handles both, and leaves a
        # phrase that ends before the table untouched.
        def implicit_end(start: int) -> int:
            if start < table_offset:
                return table_offset
            return len(rom)

        def bounded(start: int, end: int) -> int:
            if start < table_offset < end:
                return table_offset
            return end

        # Extents need address order; reporting keeps the caller's order. In a
        # command-ordered table entry N is what command N plays, and sorting the
        # pointers would relabel every phrase.
        if address_ordered:
            bounds = list(pointers)
            phrases = [Phrase(i, bounds[i],
                              bounded(bounds[i],
                                      bounds[i + 1] if i + 1 < len(bounds)
                                      else implicit_end(bounds[i])))
                       for i in range(count)]
        else:
            ordered = sorted(set(pointers))
            successor = {value: (ordered[j + 1] if j + 1 < len(ordered)
                                 else implicit_end(value))
                         for j, value in enumerate(ordered)}
            phrases = [Phrase(i, pointers[i],
                              bounded(pointers[i], successor[pointers[i]]))
                       for i in range(count)]

        seen = {}
        for phrase in phrases:
            if phrase.end <= phrase.start:
                raise ValueError(
                    "phrase %d has end 0x%X <= start 0x%X; the table is probably "
                    "command-ordered (pass address_ordered=False) or the count "
                    "is wrong" % (phrase.index, phrase.end, phrase.start))
            # An overlap test, not "below the table": the table need not
            # precede the speech. What must not happen is a phrase covering the
            # table's own bytes, which patching would rewrite.
            if phrase.start < end_of_table and table_offset < phrase.end:
                raise ValueError(
                    "phrase %d (0x%X-0x%X) overlaps the pointer table at "
                    "0x%X-0x%X; patching it would corrupt the table"
                    % (phrase.index, phrase.start, phrase.end,
                       table_offset, end_of_table))
            # Duplicate pointers are documented as occurring: two commands can
            # name the same phrase. That is legal and must not be an error, but
            # the byte range must only be converted ONCE.
            seen.setdefault((phrase.start, phrase.end), []).append(phrase.index)

        # No overlap check: extents here are always identical or disjoint.
        # Address-ordered ones are consecutive pointer pairs, so any decrease
        # trips the refusal above; command-ordered ones run to the next distinct
        # sorted pointer. The suite exercises every layout in a bounded domain.
        return cls(phrases)


@dataclass
class PhraseResult:
    phrase: Phrase
    frames: int
    clamped: int
    approximated: int
    truncated: int
    stopped_cleanly: bool
    changed_bytes: int
    last_byte_truncated: bool = False
    #: When two commands name the same phrase, both are reported so neither
    #: command's identity is lost, but only the first did the physical work.
    #: This holds that first phrase's index on every later alias, and `summarise`
    #: leaves aliases out of its physical totals.
    alias_of: Optional[int] = None
    #: Frames whose kind (voiced/unvoiced/silence/stop) survived conversion,
    #: measured by re-parsing the OUTPUT with the target tables rather than by
    #: trusting the conversion. A kind change means the bit layout moved, which
    #: desynchronises everything after it.
    kinds_preserved: int = 0
    #: Absolute f0 error in hertz for each voiced frame the target could reach.
    #: Clamped frames are excluded: their error is the pitch floor, not
    #: quantisation, and averaging the two together hides both.
    f0_errors: Sequence[float] = ()

    @property
    def clamped_fraction(self) -> float:
        return self.clamped / self.frames if self.frames else 0.0


def _truncation_set(truncate_last_byte, table: "PhraseTable") -> set:
    """Normalise False / True / an iterable of indexes into a set of indexes."""
    if truncate_last_byte is False or truncate_last_byte is None:
        return set()
    if truncate_last_byte is True:
        return {p.index for p in table.phrases}
    wanted = set(truncate_last_byte)
    known = {p.index for p in table.phrases}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError("no such phrase index: %s (the table has %d phrases)"
                         % (", ".join(str(i) for i in unknown), len(known)))
    return wanted


def diagnose_last_byte(rom: bytes, table: PhraseTable,
                       source: ChipTables) -> Dict[int, str]:
    """Whether each phrase needs its final ROM byte in order to terminate.

    WHAT THIS CAN AND CANNOT TELL YOU. It cannot tell you which convention the
    player uses -- that is firmware behaviour and is not recorded in the speech
    data. What it can tell you is whether the final byte is NEEDED, which is the
    half of the question that decides whether `--truncate-last-byte` is safe:

      "required"  only `rom[start:end]` ends in a stop frame. The final byte
                  carries part of the terminator, so truncating this phrase
                  would remove it.
      "spare"     `rom[start:end-1]` already ends in a stop frame. The final
                  byte sits past the terminator; truncating is safe, and the
                  default leaves it alone in the output anyway.
      "no stop"   neither reading ends in a stop frame. The extent is probably
                  not a phrase -- check the layout before converting.

    Note there is no fourth verdict. `parse` scans left to right and halts at the
    first stop frame, so a strict prefix can never terminate where the whole
    stream did not. "the short reading works and the long one does not" is
    unreachable, and a verdict for it would be decoration.
    """
    verdicts: Dict[int, str] = {}
    for phrase in table.phrases:
        full = bytes(rom[phrase.start:phrase.end])
        _frames, whole = parse(full, source.pitch_bits, list(source.k_widths))
        short = False
        if len(full) > 1:
            _frames, short = parse(full[:-1], source.pitch_bits,
                                   list(source.k_widths))
        if short and not whole:                  # see the note above
            raise AssertionError(
                "phrase %d terminates only when its last byte is dropped, which "
                "a prefix scan cannot do" % phrase.index)
        verdicts[phrase.index] = ("spare" if short else
                                  "required" if whole else "no stop")
    return verdicts


def patch_rom(rom: bytes, table: PhraseTable, source: ChipTables,
              target: ChipTables, truncate_last_byte=False,
              allow_unterminated: bool = False
              ) -> Tuple[bytes, List[PhraseResult]]:
    """Convert every phrase in place. Returns (new_rom, per-phrase results).

    `truncate_last_byte` selects the phrases whose final ROM byte is never
    transmitted, and so must be left untouched: `False` for none (the default),
    `True` for all, or an iterable of phrase indexes. It is per-phrase because
    the convention is per-stream -- see `diagnose_last_byte`.

    FAILS CLOSED. If any phrase does not end in a stop frame this raises rather
    than returning, because the usual cause is a wrong layout aimed at code or
    data and the result would be a plausible-looking corrupt ROM. Pass
    `allow_unterminated=True` if you have checked and the phrases really are
    unterminated, or an iterable of the phrase indexes that are known not to
    terminate -- which keeps the refusal in force for every other phrase. This lives here rather than in the command line so that a
    library caller gets the same protection as a CLI user.

    The ROM is the same length as the input and differs only inside phrase
    extents. Nothing outside them -- pointer table, code, data -- is written.
    """
    truncated = _truncation_set(truncate_last_byte, table)
    out = bytearray(rom)
    results: List[PhraseResult] = []
    # Duplicate pointers are legal, so the same bytes can be declared twice.
    # Convert them once: a second pass would produce the same output but double
    # every total in the manifest.
    done: Dict[tuple, PhraseResult] = {}

    # Grouped by DECLARED extent, before truncation: keying on the truncated
    # end would split one phrase into two groups when only one alias was
    # truncated, and count its bytes twice.
    for phrase in table.phrases:
        group = (phrase.start, phrase.end)
        end = phrase.end - 1 if phrase.index in truncated else phrase.end

        first = done.get(group)
        if first is not None:
            if first.last_byte_truncated != (phrase.index in truncated):
                raise ValueError(
                    "phrases %d and %d name the same bytes (0x%X-0x%X) but only "
                    "one was given --truncate-last-byte. The final byte is "
                    "either transmitted or it is not; pass both indexes or "
                    "neither."
                    % (first.phrase.index, phrase.index,
                       phrase.start, phrase.end))
            results.append(replace(first, phrase=phrase,
                                   alias_of=first.phrase.index))
            continue

        if end <= phrase.start:
            # Skipping here would drop the phrase from the results entirely:
            # no stop-frame check, no manifest entry, and a conversion that
            # reports fewer phrases than the layout declared while claiming
            # success. A phrase with nothing left to convert is a layout error.
            raise ValueError(
                "phrase %d has no convertible bytes (0x%X-0x%X%s); check the "
                "layout, and --truncate-last-byte if you passed it"
                % (phrase.index, phrase.start, phrase.end,
                   ", less its untransmitted final byte"
                   if phrase.index in truncated else ""))
        original = bytes(rom[phrase.start:end])
        converted, report, stopped = convert_stream(original, source, target)
        if len(converted) != len(original):
            raise AssertionError(
                "phrase %d changed length; conversion must be in place"
                % phrase.index)
        out[phrase.start:end] = converted

        # Re-parse what was written, with the target tables, and compare frame
        # kinds. A changed kind means a changed length, so everything after it
        # is being read at the wrong bit offset. Checking the output rather than
        # the report means a conversion bug cannot report its way past this.
        source_frames, _ = parse(original, source.pitch_bits,
                                 list(source.k_widths))
        target_frames, _ = parse(converted, target.pitch_bits,
                                 list(target.k_widths))
        preserved = sum(1 for a, b in zip(source_frames, target_frames)
                        if a.kind == b.kind)
        if len(source_frames) != len(target_frames) or \
                preserved != len(source_frames):
            raise AssertionError(
                "phrase %d: conversion changed the frame structure (%d of %d "
                "kinds preserved, %d frames in and %d out). The output would "
                "desynchronise; refusing to return it."
                % (phrase.index, preserved, len(source_frames),
                   len(source_frames), len(target_frames)))

        result = PhraseResult(
            kinds_preserved=preserved,
            f0_errors=tuple(abs(r.f0_error_hz) for r in report
                            if r.f0_error_hz is not None
                            and not r.pitch_clamped),
            phrase=phrase,
            last_byte_truncated=phrase.index in truncated,
            frames=len(report),
            clamped=sum(1 for r in report if r.pitch_clamped),
            approximated=sum(1 for r in report if r.pitch_approximated),
            truncated=sum(1 for r in report if r.skipped_truncated),
            stopped_cleanly=stopped,
            changed_bytes=sum(1 for a, b in zip(original, converted) if a != b),
        )
        done[group] = result
        results.append(result)

    # Every declared phrase produces a result: duplicates that share an extent
    # each get their own entry, marked with `alias_of`, so no command loses its
    # identity and no total is counted twice.
    unterminated = [r.phrase.index for r in results if not r.stopped_cleanly]
    if allow_unterminated is not True and allow_unterminated:
        # An iterable of indexes: those phrases are known not to terminate and
        # every other one must still be refused.
        expected = set(allow_unterminated)
        unterminated = [i for i in unterminated if i not in expected]
        allow_unterminated = False
    if unterminated and not allow_unterminated:
        raise ValueError(
            "%d of %d phrase(s) do not end in a stop frame (first is phrase "
            "%d); the declared layout is probably wrong. Pass "
            "allow_unterminated=True to convert them anyway, or a list of "
            "the phrase indexes that are known not to terminate."
            % (len(unterminated), len(results), unterminated[0]))

    return bytes(out), results


def summarise(results: Sequence[PhraseResult]) -> Dict[str, float]:
    """Headline numbers for a patched ROM."""
    # Physical totals count each converted extent once. `phrases` counts what
    # the layout DECLARED, which is a different and also useful number: with
    # duplicate pointers a ROM has more commands than phrases.
    unique = [r for r in results if r.alias_of is None]
    frames = sum(r.frames for r in unique)
    clamped = sum(r.clamped for r in unique)
    summary = {
        "phrases": len(results),
        "distinct_phrases": len(unique),
        "frames": frames,
        "frames_clamped": clamped,
        "frames_approximated": sum(r.approximated for r in unique),
        "frames_truncated": sum(r.truncated for r in unique),
        "clamped_percent": 100.0 * clamped / frames if frames else 0.0,
        "phrases_without_stop_frame": sum(1 for r in results
                                          if not r.stopped_cleanly),
        "bytes_changed": sum(r.changed_bytes for r in unique),
        "frame_kinds_preserved": sum(r.kinds_preserved for r in unique),
    }
    errors = sorted(e for r in unique for e in r.f0_errors)
    if errors:
        summary["f0_error_hz"] = {
            "frames": len(errors),
            "median": round(statistics.median(errors), 3),
            "mean": round(statistics.fmean(errors), 3),
            "max": round(errors[-1], 3),
        }
    return summary
