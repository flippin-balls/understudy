"""Chip coefficient tables -- loaded, never bundled.

WHY THIS SHIPS NO TABLE DATA

A TMS5200 or TMS5220 stream is meaningless without the chip's coefficient
tables: energy, pitch and K1..K10. This project does not distribute them.

The reason is provenance, not a legal conclusion -- docs/PROVENANCE.md sets out
the position and its limits. Every convenient machine-readable copy in
circulation traces back to an emulator source tree,
and the largest of those -- PinMAME -- is mid-migration from the old MAME
licence to 3-Clause BSD on a per-file basis, with unconverted files still under
terms that restrict commercial use. Vendoring a generated copy would inherit
that ambiguity into every downstream user of this library, permanently, to save
them one command. That trade is not worth making.

So you supply the tables. `docs/PROVENANCE.md` sets out where to get them and
what each field means; `from_pinmame.py` in that directory will extract them
from a checkout you already have.

WHAT THE STRUCTURE MEANS

    pitch_bits   6 on both 52xx parts. Present because the earlier TMS5100 and
                 TMS5110 use 5, and assuming that width for a 52xx stream
                 desynchronises every frame after the first voiced one.
    k_widths     bit width of K1..K10, in order.
    energy       index -> amplitude
    pitch        index -> excitation PERIOD IN SAMPLES, not a frequency.
                 f0 = sample_rate / period. Index 0 means unvoiced.
    k            ten lists, index -> reflection coefficient.

The two 52xx parts share every field width; ONLY the table contents differ.
The pitch table is where they differ substantively, and that difference is the
whole reason this project exists. See docs/PITCH_CEILING.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

#: Synthesis sample rate of the TMS52xx family. Pitch table entries are periods
#: in samples at this rate, so f0 = SAMPLE_RATE / period. This is not the LPC
#: frame rate, which is a different and slower thing.
SAMPLE_RATE = 8000


def _integer(value, where: str) -> None:
    """Reject anything that is not a plain int.

    `bool` is excluded explicitly because it is a subclass of `int`, so a table
    of `true`/`false` would otherwise pass every numeric check and then quantise
    the whole stream onto two levels.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer, got %r" % (where, value))


def _non_negative(value, where: str) -> None:
    """For energies, periods and widths. NOT for K: those are signed.

    Reflection coefficients are signed Q values -- the real tables run from
    about -501 to +506 -- so a non-negative rule applied to them would reject
    every genuine chip table.
    """
    _integer(value, where)
    if value < 0:
        raise ValueError("%s must not be negative, got %r" % (where, value))


@dataclass(frozen=True)
class ChipTables:
    """One chip variant's coefficient tables."""

    name: str
    pitch_bits: int
    k_widths: Sequence[int]
    energy: Sequence[int]
    pitch: Sequence[int]
    k: Sequence[Sequence[int]]

    def __post_init__(self) -> None:
        if self.pitch_bits not in (5, 6):
            raise ValueError("pitch_bits must be 6 (both 52xx parts) or 5 "
                             "(the earlier 51xx family), got %r"
                             % (self.pitch_bits,))
        if len(self.k_widths) != 10:
            raise ValueError("expected 10 K widths, got %d" % len(self.k_widths))
        if len(self.k) != 10:
            raise ValueError("expected 10 K tables, got %d" % len(self.k))
        if len(self.energy) != 16:
            raise ValueError("energy table must have 16 entries (a 4-bit field), "
                             "got %d" % len(self.energy))

        # Types before values. JSON will happily hand over floats, strings and
        # booleans, and `True == 1` in Python, so a table of booleans would pass
        # every numeric check below and then quantise everything to two levels.
        _non_negative(self.pitch_bits, "pitch_bits")
        for i, width in enumerate(self.k_widths, start=1):
            _non_negative(width, "K%d width" % i)
        for i, value in enumerate(self.energy):
            _non_negative(value, "energy[%d]" % i)
        for i, value in enumerate(self.pitch):
            _non_negative(value, "pitch[%d]" % i)
        for i, values in enumerate(self.k, start=1):
            for j, value in enumerate(values):
                _integer(value, "K%d[%d]" % (i, j))      # signed

        if self.pitch[0] != 0:
            raise ValueError("pitch index 0 must be 0 (unvoiced); got %r"
                             % (self.pitch[0],))
        # EVERY other entry must be a usable period, not merely non-negative. A
        # zero at, say, index 7 is silently fatal twice over: `nearest_index`
        # forbids only index 0, so a voiced frame can be quantised onto index 7
        # and emerge unvoiced -- which drops K5-K10 and desynchronises the rest
        # of the stream -- and `f0_hz` then divides by that zero.
        zeros = [i for i, p in enumerate(self.pitch) if i and p == 0]
        if zeros:
            raise ValueError(
                "pitch periods must be positive except at index 0 (unvoiced); "
                "zero at index %s" % ", ".join(str(i) for i in zeros[:8]))
        if len(self.pitch) != 1 << self.pitch_bits:
            raise ValueError(
                "pitch table has %d entries but pitch_bits=%d implies %d"
                % (len(self.pitch), self.pitch_bits, 1 << self.pitch_bits))
        for i, (width, values) in enumerate(zip(self.k_widths, self.k), start=1):
            if len(values) != 1 << width:
                raise ValueError(
                    "K%d table has %d entries but its width %d implies %d"
                    % (i, len(values), width, 1 << width))

    def f0_hz(self, pitch_index: int, sample_rate: int = SAMPLE_RATE):
        """Fundamental frequency for a pitch index, or None if unvoiced.

        Pitch indexes are NOT comparable between chips -- the same index means
        a different period on a TMS5200 than on a TMS5220. Compare hertz.
        """
        if not 0 <= pitch_index < len(self.pitch):
            raise IndexError("pitch index %d out of range" % pitch_index)
        period = self.pitch[pitch_index]
        return None if period == 0 else sample_rate / period

    @property
    def lowest_f0_hz(self) -> float:
        """Lowest fundamental this chip can be made to produce."""
        periods = [p for p in self.pitch if p]
        return SAMPLE_RATE / max(periods)

    @classmethod
    def from_json(cls, path) -> "ChipTables":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(name=raw["name"],
                   pitch_bits=raw["pitch_bits"],
                   k_widths=list(raw["k_widths"]),
                   energy=list(raw["energy"]),
                   pitch=list(raw["pitch"]),
                   k=[list(v) for v in raw["k"]])

    def to_json(self, path) -> None:
        Path(path).write_text(json.dumps({
            "name": self.name,
            "pitch_bits": self.pitch_bits,
            "k_widths": list(self.k_widths),
            "energy": list(self.energy),
            "pitch": list(self.pitch),
            "k": [list(v) for v in self.k],
        }, indent=1), encoding="utf-8")


def load_pair(directory) -> Dict[str, ChipTables]:
    """Load `tms5200.json` and `tms5220.json` from `directory`."""
    directory = Path(directory)
    out = {}
    for name in ("tms5200", "tms5220"):
        path = directory / ("%s.json" % name)
        if not path.exists():
            raise FileNotFoundError(
                "%s not found. This project does not ship chip tables; see "
                "docs/PROVENANCE.md for how to produce them." % path)
        out[name] = ChipTables.from_json(path)
    return out
