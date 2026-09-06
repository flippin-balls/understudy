"""TMS5200 -> TMS5220 stream conversion.

THE PROBLEM

The two chips share the frame grammar AND every field width. What differs is the
contents of the coefficient tables behind the indexes. A TMS5200 stream played
on a TMS5220 therefore parses perfectly and sounds wrong: every index still
lands in the right place and still means something else.

Conversion is not transcoding audio. It is re-indexing each parameter into the
destination chip's tables so the synthesised result is as close as that chip can
get -- which, for pitch, is sometimes not close at all. See
docs/PITCH_CEILING.md.

LENGTH IS PRESERVED, EXACTLY

Because no field changes width and no frame changes kind, a converted stream
occupies exactly as many bits as the original. That is what makes patching a
speech ROM in place viable: the converted phrase is written over the original at
the same offset, and no pointer table, phrase boundary or timing changes.
`convert_stream` asserts this rather than trusting it.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT

`nearest` maps each parameter independently to the destination index whose table
value is closest. It is the honest baseline: simple, auditable, and good enough
to establish what the harder approaches have to beat.

It is NOT optimal, and this project does not pretend otherwise. Choosing K
indexes jointly per frame -- scored by rendering rather than by table distance
-- does better, because the reflection coefficients interact. That work is
measured in docs/RESULTS.md and is not in this module, so that the baseline
stays readable and stays a baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .bitstream import Frame, K_FIELDS, parse, rebuild
from .tables import ChipTables


def nearest_index(value: int, table: Sequence[int]) -> int:
    """Index of the table entry closest to `value`.

    Ties go to the lower index, which is arbitrary but fixed: an unstable
    tie-break makes conversion non-deterministic and diffs meaningless.
    """
    best, best_delta = 0, None
    for index, entry in enumerate(table):
        delta = abs(entry - value)
        if best_delta is None or delta < best_delta:
            best, best_delta = index, delta
    return best


@dataclass
class FrameConversion:
    """What happened to one frame, in enough detail to audit it."""

    index: int
    kind: Optional[str]
    source_f0: Optional[float] = None
    target_f0: Optional[float] = None
    #: The source asked for a period the target chip cannot reach at all, so the
    #: pitch was forced up to the target's floor. This is the unfixable case.
    pitch_clamped: bool = False
    #: The period changed, but only to the nearest available entry. Ordinary
    #: quantisation, usually a fraction of a hertz, and not the same thing as
    #: hitting the floor -- conflating the two makes conversion look far worse
    #: than it is.
    pitch_approximated: bool = False
    fields: Dict[str, int] = None

    @property
    def f0_error_hz(self) -> Optional[float]:
        if self.source_f0 is None or self.target_f0 is None:
            return None
        return self.target_f0 - self.source_f0


def convert_frames(frames: List[Frame], source: ChipTables,
                   target: ChipTables) -> List[FrameConversion]:
    """Re-index every frame's parameters from `source` tables into `target`.

    Mutates the frames' field indexes in place and returns a per-frame record of
    what changed, including whether the destination chip could reach the pitch
    the source asked for.
    """
    if len(source.k) != len(target.k):
        raise ValueError("chips have different K counts")

    report: List[FrameConversion] = []
    for frame in frames:
        record = FrameConversion(index=frame.index, kind=frame.kind, fields={})

        if frame.kind in ("stop", "silence"):
            report.append(record)
            continue

        energy_spec = frame.fields.get("energy")
        if energy_spec is not None:
            want = source.energy[energy_spec.index]
            energy_spec.index = nearest_index(want, target.energy)
            record.fields["energy"] = energy_spec.index

        pitch_spec = frame.fields.get("pitch")
        if pitch_spec is not None and pitch_spec.index != 0:
            want_period = source.pitch[pitch_spec.index]
            record.source_f0 = source.f0_hz(pitch_spec.index)
            # Index 0 is unvoiced and must never be chosen as a "nearest period".
            candidates = list(target.pitch)
            candidates[0] = 10 ** 9
            pitch_spec.index = nearest_index(want_period, candidates)
            record.target_f0 = target.f0_hz(pitch_spec.index)
            got_period = target.pitch[pitch_spec.index]
            longest = max(p for p in target.pitch if p)
            record.pitch_clamped = want_period > longest
            record.pitch_approximated = (got_period != want_period
                                         and not record.pitch_clamped)
            record.fields["pitch"] = pitch_spec.index

        for i, name in enumerate(K_FIELDS):
            spec = frame.fields.get(name)
            if spec is None:
                continue
            want = source.k[i][spec.index]
            spec.index = nearest_index(want, target.k[i])
            record.fields[name] = spec.index

        report.append(record)
    return report


def convert_stream(data: bytes, source: ChipTables,
                   target: ChipTables) -> tuple:
    """Convert a whole stream. Returns (bytes, report, stopped_cleanly).

    The output is the same length as the input, byte for byte, and every field
    keeps its original bit offset. Only index values change.
    """
    if source.pitch_bits != target.pitch_bits or \
            list(source.k_widths) != list(target.k_widths):
        raise ValueError(
            "%s and %s do not share field widths; this converter re-indexes "
            "between parts of the same family and cannot relayout frames"
            % (source.name, target.name))

    frames, stopped = parse(data, source.pitch_bits, list(source.k_widths))
    report = convert_frames(frames, source, target)
    out = rebuild(frames, len(data), base=data)
    if len(out) != len(data):                    # cannot happen; cheap to prove
        raise AssertionError("conversion changed the stream length")
    return out, report, stopped
