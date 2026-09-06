"""Patch a Bally Squawk & Talk speech ROM from TMS5200 tables to TMS5220 tables.

WHY THIS IS SAFE TO DO IN PLACE

The two parts share every field width, so conversion changes index VALUES and
nothing else. A converted phrase occupies exactly the bytes the original did.
Nothing moves, so the pointer table stays valid, phrase boundaries stay valid,
and playback timing is unchanged. `patch_rom` verifies the length rather than
assuming it.

WHAT YOU HAVE TO TELL IT, AND WHY IT CANNOT GUESS

Squawk & Talk stores phrases as a table of 16-bit big-endian pointers followed
by the speech data, and that is the only part that generalises. Three things
vary between games and are not derivable from the ROM alone:

  * ORDERING. Some titles list phrases in address order; others list them in
    command order, so consecutive table entries are not consecutive in memory.
    At least one duplicates every entry.
  * BOUNDS. Most tables carry N+1 entries for N phrases, the last being the end
    bound of the final phrase. Some carry exactly N, leaving the final phrase's
    end implicit.
  * THE FINAL BYTE. Some players stream `rom[start:end]` verbatim; others send
    `rom[start:end-1]` and substitute a zero for the last byte, so the final ROM
    byte of a phrase is never transmitted. This is a property of the individual
    STREAM, not of the game -- single ROM sets are known to use both.

None of that changes what conversion does to the bits, but all of it changes
which bytes are a phrase. `PhraseTable.from_pointers` takes the decisions
explicitly so they are visible in your code rather than guessed in ours.

This module reads and writes only ROM images you already possess. It contains no
ROM data.
"""
from __future__ import annotations

from dataclasses import dataclass
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

        # Where the LAST phrase ends when nothing bounds it. "The end of the
        # image" is the obvious answer and is wrong whenever the pointer table
        # sits above the speech -- which is normal on a Squawk & Talk, where the
        # table lives in one socket and the phrases in another at a lower
        # address. The table's own bytes are provably not speech, so they bound
        # the last phrase just as surely as another pointer would.
        def implicit_end(start: int) -> int:
            if start < table_offset:
                return table_offset
            return len(rom)

        # Deriving extents needs address order; REPORTING must keep the caller's
        # order, because in a command-ordered table entry N is the phrase that
        # command N plays and that identity is the useful part. Sorting the
        # pointers and renumbering would silently relabel every phrase.
        if address_ordered:
            bounds = list(pointers)
            phrases = [Phrase(i, bounds[i],
                              bounds[i + 1] if i + 1 < len(bounds)
                              else implicit_end(bounds[i]))
                       for i in range(count)]
        else:
            ordered = sorted(set(pointers))
            successor = {value: (ordered[j + 1] if j + 1 < len(ordered)
                                 else implicit_end(value))
                         for j, value in enumerate(ordered)}
            phrases = [Phrase(i, pointers[i], successor[pointers[i]])
                       for i in range(count)]

        seen = {}
        for phrase in phrases:
            if phrase.end <= phrase.start:
                raise ValueError(
                    "phrase %d has end 0x%X <= start 0x%X; the table is probably "
                    "command-ordered (pass address_ordered=False) or the count "
                    "is wrong" % (phrase.index, phrase.end, phrase.start))
            # OVERLAP, not "below the table". The pointer table does not have
            # to precede the speech: on a Squawk & Talk the table commonly sits
            # in one socket and the phrases it points at in another, at a lower
            # address. What must not happen is a phrase extent covering the
            # table's own bytes, because patching it would rewrite the table.
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

        # NO OVERLAP CHECK, because a partial overlap cannot be built here and a
        # check that can never fire is worse than none: it implies a hazard the
        # code does not actually have. Two extents are always either identical
        # or disjoint. Address-ordered extents are consecutive pointer pairs, so
        # any decrease trips the end <= start refusal above and the surviving
        # tables are strictly increasing; command-ordered extents run from each
        # pointer to the next DISTINCT sorted pointer, which partitions the ROM.
        # `test_extents_are_identical_or_disjoint` proves this exhaustively over
        # every small layout, and is what protects the property if this changes.
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
              target: ChipTables,
              truncate_last_byte=False) -> Tuple[bytes, List[PhraseResult]]:
    """Convert every phrase in place. Returns (new_rom, per-phrase results).

    `truncate_last_byte` selects the phrases whose final ROM byte is never
    transmitted, and so must be left untouched: `False` for none (the default),
    `True` for all, or an iterable of phrase indexes. It is per-phrase because
    the convention is per-stream -- see `diagnose_last_byte`.

    The ROM is the same length as the input and differs only inside phrase
    extents. Nothing outside them -- pointer table, code, data -- is written.
    """
    truncated = _truncation_set(truncate_last_byte, table)
    out = bytearray(rom)
    results: List[PhraseResult] = []

    for phrase in table.phrases:
        end = phrase.end - 1 if phrase.index in truncated else phrase.end
        if end <= phrase.start:
            continue
        original = bytes(rom[phrase.start:end])
        converted, report, stopped = convert_stream(original, source, target)
        if len(converted) != len(original):
            raise AssertionError(
                "phrase %d changed length; conversion must be in place"
                % phrase.index)
        out[phrase.start:end] = converted
        results.append(PhraseResult(
            phrase=phrase,
            last_byte_truncated=phrase.index in truncated,
            frames=len(report),
            clamped=sum(1 for r in report if r.pitch_clamped),
            approximated=sum(1 for r in report if r.pitch_approximated),
            truncated=sum(1 for r in report if r.skipped_truncated),
            stopped_cleanly=stopped,
            changed_bytes=sum(1 for a, b in zip(original, converted) if a != b),
        ))

    return bytes(out), results


def summarise(results: Sequence[PhraseResult]) -> Dict[str, float]:
    """Headline numbers for a patched ROM."""
    frames = sum(r.frames for r in results)
    clamped = sum(r.clamped for r in results)
    return {
        "phrases": len(results),
        "frames": frames,
        "frames_clamped": clamped,
        "frames_approximated": sum(r.approximated for r in results),
        "frames_truncated": sum(r.truncated for r in results),
        "clamped_percent": 100.0 * clamped / frames if frames else 0.0,
        "phrases_without_stop_frame": sum(1 for r in results
                                          if not r.stopped_cleanly),
        "bytes_changed": sum(r.changed_bytes for r in results),
    }
