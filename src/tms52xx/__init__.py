"""understudy -- TMS5220 speech chips standing in for unobtainable TMS5200s.

The TMS5200 is long out of production. Machines that shipped with one still
need to talk, and the TMS5220 is a later part from the same family. It runs the same
frame grammar with the same field widths, but different coefficient tables, so
the index values in existing speech data mean different things to it.

This library re-indexes TMS5200 LPC data into TMS5220 tables. Because no field
changes width, the result is the same length as the original and can be patched
into a ROM in place. One thing it cannot fix: the TMS5220's excitation period
table stops shorter than the TMS5200's, so the bottom of the pitch range has no
destination to map to and is clamped upward. See docs/PITCH_CEILING.md.
"""
from .bitstream import (ENERGY_SILENCE, ENERGY_STOP, K_FIELDS, BitReader,
                        Frame, parse, rebuild, summarize)
from .convert import FrameConversion, convert_frames, convert_stream, nearest_index
from .tables import SAMPLE_RATE, ChipTables, load_pair

__version__ = "0.3.0"

__all__ = [
    "BitReader", "ChipTables", "ENERGY_SILENCE", "ENERGY_STOP", "Frame",
    "FrameConversion", "K_FIELDS", "SAMPLE_RATE", "convert_frames",
    "convert_stream", "load_pair", "nearest_index", "parse", "rebuild",
    "summarize",
]
