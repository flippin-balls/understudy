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

        bounds = sorted(pointers) if not address_ordered else list(pointers)
        phrases = []
        for i in range(count):
            start = bounds[i]
            end = bounds[i + 1] if i + 1 < len(bounds) else len(rom)
            if end <= start:
                raise ValueError(
                    "phrase %d has end 0x%X <= start 0x%X; the table is probably "
                    "command-ordered (pass address_ordered=False) or the count "
                    "is wrong" % (i, end, start))
            phrases.append(Phrase(i, start, end))
        return cls(phrases)


@dataclass
class PhraseResult:
    phrase: Phrase
    frames: int
    clamped: int
    approximated: int
    stopped_cleanly: bool
    changed_bytes: int

    @property
    def clamped_fraction(self) -> float:
        return self.clamped / self.frames if self.frames else 0.0


def patch_rom(rom: bytes, table: PhraseTable, source: ChipTables,
              target: ChipTables,
              last_byte_verbatim: bool = True) -> Tuple[bytes, List[PhraseResult]]:
    """Convert every phrase in place. Returns (new_rom, per-phrase results).

    `last_byte_verbatim=False` treats each phrase as `rom[start:end-1]`, matching
    players that never transmit a phrase's final ROM byte. The untransmitted byte
    is left untouched in the output.

    The ROM is the same length as the input and differs only inside phrase
    extents. Nothing outside them -- pointer table, code, data -- is written.
    """
    out = bytearray(rom)
    results: List[PhraseResult] = []

    for phrase in table.phrases:
        end = phrase.end if last_byte_verbatim else phrase.end - 1
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
            frames=len(report),
            clamped=sum(1 for r in report if r.pitch_clamped),
            approximated=sum(1 for r in report if r.pitch_approximated),
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
        "clamped_percent": 100.0 * clamped / frames if frames else 0.0,
        "phrases_without_stop_frame": sum(1 for r in results
                                          if not r.stopped_cleanly),
        "bytes_changed": sum(r.changed_bytes for r in results),
    }
