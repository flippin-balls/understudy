"""understudy -- TMS5220 speech chips standing in for unobtainable TMS5200s.

The TMS5200 is long out of production. Machines that shipped with one still
need to talk, and the TMS5220 is the part you can actually buy. It runs the same
frame grammar but different coefficient tables and a different pitch field
width, so existing speech data does not simply play on it.

This library re-indexes TMS5200 LPC data into TMS5220 tables, and is honest
about where that cannot work: the TMS5220's excitation period table stops
shorter than the TMS5200's, so the bottom of the pitch range has no destination
to map to. See docs/PITCH_CEILING.md.
"""
from .bitstream import (ENERGY_SILENCE, ENERGY_STOP, K_FIELDS, BitReader,
                        Frame, parse, rebuild, summarize)
from .convert import FrameConversion, convert_frames, convert_stream, nearest_index
from .tables import SAMPLE_RATE, ChipTables, load_pair

__version__ = "0.1.0"

__all__ = [
    "BitReader", "ChipTables", "ENERGY_SILENCE", "ENERGY_STOP", "Frame",
    "FrameConversion", "K_FIELDS", "SAMPLE_RATE", "convert_frames",
    "convert_stream", "load_pair", "nearest_index", "parse", "rebuild",
    "summarize",
]
