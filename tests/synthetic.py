"""Synthetic chip tables, so the suite runs without any real chip data.

THESE ARE NOT TMS5200 OR TMS5220 TABLES. They are invented values with the same
STRUCTURE -- field widths, table sizes, monotonic period ranges -- chosen so the
codec and the converter can be exercised end to end by anyone who has cloned
this repository and supplied nothing.

Two properties are reproduced deliberately, because the project turns on them:

  * both parts share IDENTICAL field widths, so conversion cannot change a
    stream's length and a ROM can be patched in place;
  * the stand-in cannot reach as long an excitation period as the original, so
    the bottom of the pitch range has nowhere to map to.

Everything else about these numbers is arbitrary.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tms52xx.tables import ChipTables      # noqa: E402

K_WIDTHS = [5, 5, 4, 4, 4, 4, 4, 3, 3, 3]
PITCH_BITS = 6


def _k_tables(offset: int):
    """Ten plausible monotonic K tables; `offset` makes the two parts differ."""
    return [[(-500 + offset) + i * (1000 // (1 << w))
             for i in range(1 << w)] for w in K_WIDTHS]


def _periods(longest: int):
    """63 monotonic periods from 14 up to `longest`, plus index 0 = unvoiced."""
    span = longest - 14
    return [0] + [14 + round(i * (span / 62)) for i in range(63)]


def original() -> ChipTables:
    """Stand-in for the original part: periods reaching 210 samples."""
    return ChipTables(name="synthetic-original", pitch_bits=PITCH_BITS,
                      k_widths=K_WIDTHS,
                      energy=[0] + [i * 4 for i in range(1, 15)] + [0],
                      pitch=_periods(210), k=_k_tables(0))


def understudy() -> ChipTables:
    """Stand-in for the substitute part: periods stopping at 159.

    The shorter ceiling is the point. Frames asking for a period longer than
    159 have no destination and must be clamped upward.
    """
    return ChipTables(name="synthetic-understudy", pitch_bits=PITCH_BITS,
                      k_widths=K_WIDTHS,
                      energy=[0] + [i * 4 for i in range(1, 15)] + [0],
                      pitch=_periods(159), k=_k_tables(7))
