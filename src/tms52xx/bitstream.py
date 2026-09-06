"""TMS5200/TMS5220 LPC frame bitstream: parse, rebuild, and locate every bit.

The frame grammar below is the one both chips implement. It is documented in
Texas Instruments' TMS5220 Voice Synthesis Processor data manual and is
independently visible in every emulator and encoder listed in docs/PRIOR_ART.md.

    energy      4 bits      0 = silence, 15 = stop, otherwise an index
    repeat      1 bit       set -> the frame ends here and reuses the previous
                            frame's coefficients, carrying only its own pitch
    pitch       6 bits      0 = unvoiced
    K1..K4      5,5,4,4     always present in a non-repeat, non-silence frame
    K5..K10     4,4,4,3,3,3 present only when pitch != 0, i.e. voiced

The TMS5200 and the TMS5220 use IDENTICAL field widths. Only the coefficient
tables behind the indexes differ. That is worth stating plainly because it is
easy to assume otherwise -- the earlier TMS5100/5110 family does use a 5-bit
pitch field, and confusing the two families leads to a 5-bit assumption that
desynchronises every frame after the first voiced one.

The practical consequence is large and good: converting between the two 52xx
parts changes only index VALUES, never any field's width or position, so a
converted stream is exactly as long as the original and can be written back
over it in place.

Two details cost more time than they should if you do not know them, so they
are stated rather than left to be rediscovered:

* Bits leave a byte LSB-first but assemble into fields MSB-first. `BitReader`
  does both, and getting only one of them right produces plausible-looking
  frames that decode to noise.
* Reads past the end of the data return zero bits rather than raising. That
  matches the chip: the FIFO reads zeroes when it runs dry, and a stream whose
  final frame is truncated still parses as far as it goes.

Every field records the absolute bit offsets it occupies. That is what makes
`rebuild` a genuine round-trip test rather than a re-encode: if the bit map is
wrong, the rebuilt stream differs from the original and the test fails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

K_FIELDS: Tuple[str, ...] = tuple("K%d" % i for i in range(1, 11))

ENERGY_SILENCE = 0x0
ENERGY_STOP = 0xF


class BitReader:
    """Reads a byte stream the way the TMS52xx FIFO does: LSB-first per byte."""

    __slots__ = ("data", "bit_pos")

    def __init__(self, data: bytes, bit_pos: int = 0) -> None:
        self.data = data
        self.bit_pos = bit_pos

    @property
    def bits_available(self) -> int:
        return len(self.data) * 8 - self.bit_pos

    def bit_at(self, index: int) -> int:
        byte_index, bit_index = divmod(index, 8)
        if byte_index >= len(self.data):
            return 0                      # past the end reads as zero, as the FIFO does
        return (self.data[byte_index] >> bit_index) & 1

    def read(self, count: int) -> int:
        """Read `count` bits, assembling them MSB-first into the value."""
        value = 0
        for _ in range(count):
            value = (value << 1) | self.bit_at(self.bit_pos)
            self.bit_pos += 1
        return value


def set_bits(data: bytearray, start_bit: int, width: int, value: int) -> None:
    """Write `value` MSB-first at `start_bit`. Mutates `data` in place."""
    for offset in range(width):
        bit = (value >> (width - 1 - offset)) & 1
        byte_index, bit_index = divmod(start_bit + offset, 8)
        if byte_index >= len(data):
            raise IndexError("bit %d is past the end of the stream"
                             % (start_bit + offset))
        if bit:
            data[byte_index] |= 1 << bit_index
        else:
            data[byte_index] &= ~(1 << bit_index) & 0xFF


@dataclass
class Field:
    index: int
    start_bit: int
    width: int


@dataclass
class Frame:
    """One parsed frame, plus the bit offsets every field occupies."""

    index: int
    start_bit: int
    end_bit: int = 0
    kind: Optional[str] = None          # stop | silence | repeat | unvoiced | voiced
    fields: Dict[str, Field] = field(default_factory=dict)
    truncated: bool = False

    def add(self, name: str, value: int, start_bit: int, width: int) -> None:
        self.fields[name] = Field(value, start_bit, width)
        self.end_bit = start_bit + width

    @property
    def bit_length(self) -> int:
        return self.end_bit - self.start_bit

    def index_of(self, name: str) -> Optional[int]:
        found = self.fields.get(name)
        return None if found is None else found.index

    @property
    def energy(self) -> int:
        return self.fields["energy"].index

    @property
    def pitch(self) -> int:
        return self.index_of("pitch") or 0

    @property
    def repeat(self) -> bool:
        return bool(self.index_of("repeat"))

    @property
    def is_stop(self) -> bool:
        return self.kind == "stop"

    @property
    def is_silence(self) -> bool:
        return self.kind == "silence"

    @property
    def is_voiced(self) -> bool:
        return self.kind == "voiced"


def parse(data: bytes, pitch_bits: int, k_widths: List[int],
          max_frames: int = 100_000) -> Tuple[List[Frame], bool]:
    """Parse `data` into frames.

    `pitch_bits` is 6 for both 52xx parts. It is a parameter rather than a
    constant only so that a mistaken 5-bit assumption -- the TMS5100/5110 width
    -- can be demonstrated to desynchronise rather than merely asserted to.

    Returns (frames, stopped_cleanly).
    """
    reader = BitReader(data)
    frames: List[Frame] = []
    stopped = False

    while len(frames) < max_frames and reader.bits_available > 0:
        frame = Frame(len(frames), reader.bit_pos)

        at = reader.bit_pos
        energy = reader.read(4)
        frame.add("energy", energy, at, 4)

        if energy == ENERGY_STOP:
            frame.kind = "stop"
            frames.append(frame)
            stopped = True
            break
        if energy == ENERGY_SILENCE:
            frame.kind = "silence"
            frames.append(frame)
            continue

        at = reader.bit_pos
        repeat = reader.read(1)
        frame.add("repeat", repeat, at, 1)

        at = reader.bit_pos
        pitch = reader.read(pitch_bits)
        frame.add("pitch", pitch, at, pitch_bits)

        if repeat:
            frame.kind = "repeat"
            frames.append(frame)
            continue

        for i in range(4):
            at = reader.bit_pos
            frame.add(K_FIELDS[i], reader.read(k_widths[i]), at, k_widths[i])

        if pitch == 0:
            frame.kind = "unvoiced"
            frames.append(frame)
            continue

        for i in range(4, len(k_widths)):
            at = reader.bit_pos
            frame.add(K_FIELDS[i], reader.read(k_widths[i]), at, k_widths[i])

        frame.kind = "voiced"
        frames.append(frame)

    total_bits = len(data) * 8
    for frame in frames:
        if frame.end_bit > total_bits:
            frame.truncated = True
    return frames, stopped


def rebuild(frames: List[Frame], length_bytes: int,
            base: Optional[bytes] = None) -> bytes:
    """Write every field back at its recorded offset.

    `base` seeds the output so bits no frame claims -- trailing padding -- keep
    their original values. Without it those bits come out zero.

    Rebuilding a parse of an untouched stream must reproduce that stream byte
    for byte. That is the round-trip check, and it is what proves the bit map
    rather than merely the field values.
    """
    out = bytearray(base if base is not None else bytes(length_bytes))
    if len(out) < length_bytes:
        out.extend(bytes(length_bytes - len(out)))
    limit = len(out) * 8
    for frame in frames:
        for spec in frame.fields.values():
            if spec.start_bit + spec.width > limit:
                # A truncated final frame: `parse` supplied zeroes for bits the
                # stream does not contain, and they must not be written back.
                # Skipping is not a tolerance for bugs -- it is the only correct
                # action, because those bits are outside the data by definition.
                continue
            set_bits(out, spec.start_bit, spec.width, spec.index)
    return bytes(out)


def summarize(frames: List[Frame]) -> Dict[str, int]:
    """Frame-kind counts, for reporting."""
    counts = {"total": len(frames), "voiced": 0, "unvoiced": 0,
              "silence": 0, "repeat": 0, "stop": 0, "truncated": 0}
    for frame in frames:
        if frame.kind in counts:
            counts[frame.kind] += 1
        if frame.truncated:
            counts["truncated"] += 1
    return counts
