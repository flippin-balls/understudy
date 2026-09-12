"""Chip coefficient tables: the format, and loading one from anywhere.

Understudy BUNDLES the TMS5200 and TMS5220 tables -- see `chips.py` and
`data/` -- so nothing has to be extracted before a first conversion. This module
is the format and the loader; it is what reads the bundled files and equally
what reads one you supply with `--source-tables`. docs/PROVENANCE.md records
where the bundled data came from and how to check it.

    pitch_bits   6 on both 52xx parts. Present because the earlier TMS5100 and
                 TMS5110 use 5, and assuming that width for a 52xx stream
                 desynchronises every frame after the first voiced one.
    k_widths     bit width of K1..K10, in order.
    energy       index -> amplitude.
    pitch        index -> excitation PERIOD IN SAMPLES, not a frequency.
                 f0 = sample_rate / period. Index 0 means unvoiced.
    k            ten lists, index -> reflection coefficient (signed).

The two 52xx parts share every field width; only the table contents differ. The
pitch table is where they differ substantively, and that difference is the whole
reason this project exists -- see docs/PITCH_CEILING.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence
from . import reads

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
    def from_bytes(cls, raw: bytes, where="<bytes>") -> "ChipTables":
        """Parse tables from bytes already in hand.

        `from_json` re-reads the file; callers that must hash exactly what they
        parsed use this so the two cannot disagree.
        """
        return cls._parse(raw, Path(where))

    @classmethod
    def from_json(cls, path) -> "ChipTables":
        """Load a table file, naming what is wrong with it if it is wrong.

        These files are user-supplied and often hand-edited, so every schema
        problem becomes a `ValueError` that names the file and the field. A
        `KeyError` or a `TypeError` escaping from here reaches the user as a
        traceback, which tells them nothing they can act on.
        """
        return cls._parse(reads.read_bytes(path), Path(path))

    @classmethod
    def _parse(cls, body: bytes, where: Path) -> "ChipTables":
        try:
            raw = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ValueError("%s is not UTF-8 text: %s" % (where, error))
        except json.JSONDecodeError as error:
            raise ValueError("%s is not valid JSON: %s" % (where, error))

        if not isinstance(raw, dict):
            raise ValueError("%s must contain a JSON object, not %s"
                             % (where, type(raw).__name__))

        def field(name, want_list):
            if name not in raw:
                raise ValueError("%s: missing required field %r" % (where, name))
            value = raw[name]
            if want_list and not isinstance(value, list):
                raise ValueError("%s: field %r must be a list, not %s"
                                 % (where, name, type(value).__name__))
            return value

        name = field("name", False)
        if not isinstance(name, str):
            raise ValueError("%s: field 'name' must be a string, not %s"
                             % (where, type(name).__name__))
        k_raw = field("k", True)
        for i, row in enumerate(k_raw, start=1):
            if not isinstance(row, list):
                raise ValueError("%s: K%d must be a list, not %s"
                                 % (where, i, type(row).__name__))
        try:
            return cls(name=name,
                       pitch_bits=field("pitch_bits", False),
                       k_widths=list(field("k_widths", True)),
                       energy=list(field("energy", True)),
                       pitch=list(field("pitch", True)),
                       k=[list(row) for row in k_raw])
        except ValueError as error:
            raise ValueError("%s: %s" % (where, error))

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
                "%s not found. Understudy's own tables are bundled -- use "
                "`tms52xx.chips.resolve(\"%s\").tables()` for those. This "
                "function is for loading a directory of your own."
                % (path, name))
        out[name] = ChipTables.from_json(path)
    return out
