"""TMS5200 -> TMS5220 stream conversion.

The two chips share the frame grammar and every field width; only the contents
of the coefficient tables differ. So a TMS5200 stream played on a TMS5220 parses
perfectly and sounds wrong -- every index lands in the right place and means
something else. Conversion re-indexes each parameter into the destination
chip's tables.

Because no field changes width and no frame changes kind, the converted stream
occupies exactly as many bits as the original. That is what makes patching a
speech ROM in place viable, and `convert_stream` asserts it rather than trusting
it.

Each parameter is mapped independently to the nearest destination value. That is
not optimal -- the reflection coefficients interact, so choosing the ten K
indexes jointly per frame would do better -- but it is the mapping the frame
grammar guarantees is length-preserving, and it is auditable frame by frame from
the manifest. What conversion cannot fix at all is pitch below the TMS5220's
floor; see docs/PITCH_CEILING.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .bitstream import Frame, K_FIELDS, parse, rebuild

#: The TMS52xx frame grammar. Both the TMS5200 and the TMS5220 use exactly
#: these widths -- that identity is what makes conversion length-preserving and
#: therefore patchable in place. Anything else is a different chip family.
PITCH_BITS = 6
K_WIDTHS = (5, 5, 4, 4, 4, 4, 4, 3, 3, 3)
from .tables import ChipTables


def nearest_index(value: int, table: Sequence[int],
                  forbid: Sequence[int] = ()) -> int:
    """Index of the table entry closest to `value`, skipping `forbid`.

    Ties go to the lower index, which is arbitrary but fixed: an unstable
    tie-break makes conversion non-deterministic and diffs meaningless.

    `forbid` exists because some indexes are grammar, not data. Energy 0 means
    silence and energy 15 means stop; pitch 0 means unvoiced. Choosing one of
    those as a "nearest value" would not merely pick a poor amplitude, it would
    change what the frame IS -- turning speech into a stop frame truncates
    everything after it. On the real tables this does not currently occur, which
    is why it is enforced here rather than left to whatever tables a user
    supplies.
    """
    forbidden = set(forbid)
    best, best_delta = None, None
    for index, entry in enumerate(table):
        if index in forbidden:
            continue
        delta = abs(entry - value)
        if best_delta is None or delta < best_delta:
            best, best_delta = index, delta
    if best is None:
        raise ValueError("every table entry was forbidden")
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
    #: The frame's fields run past the end of the buffer, so it was left exactly
    #: as it was found. Converting it would rewrite the bits that fit and drop
    #: the ones that do not, which corrupts a frame that was merely incomplete.
    skipped_truncated: bool = False
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

        # A truncated frame is one whose fields ran off the end of the buffer;
        # `parse` supplied zero bits for the missing ones. Re-indexing it would
        # write back the fields that fit while the invented tail is discarded,
        # so the frame would emerge neither original nor converted. Leave it.
        if frame.truncated:
            record.skipped_truncated = True
            report.append(record)
            continue

        energy_spec = frame.fields.get("energy")
        if energy_spec is not None:
            want = source.energy[energy_spec.index]
            # 0 is silence and 15 is stop; neither is an amplitude.
            energy_spec.index = nearest_index(want, target.energy, forbid=(0, 15))
            record.fields["energy"] = energy_spec.index

        pitch_spec = frame.fields.get("pitch")
        if pitch_spec is not None and pitch_spec.index != 0:
            want_period = source.pitch[pitch_spec.index]
            record.source_f0 = source.f0_hz(pitch_spec.index)
            # Index 0 is unvoiced: a voiced frame must never convert into one.
            pitch_spec.index = nearest_index(want_period, target.pitch,
                                             forbid=(0,))
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
    for chip in (source, target):
        if (chip.pitch_bits, list(chip.k_widths)) != (PITCH_BITS, list(K_WIDTHS)):
            raise ValueError(
                "%s declares pitch_bits=%d and K widths %s, which is not the "
                "TMS52xx frame grammar (pitch_bits=6, K widths %s). This tool "
                "converts between the TMS5200 and the TMS5220 and nothing else; "
                "a table file with different widths describes a different chip "
                "family and its frames do not have this layout."
                % (chip.name, chip.pitch_bits, list(chip.k_widths),
                   list(K_WIDTHS)))
    if (list(source.energy), list(source.pitch),
            [list(v) for v in source.k]) == (list(target.energy),
                                             list(target.pitch),
                                             [list(v) for v in target.k]):
        raise ValueError(
            "%s and %s hold identical tables, so conversion would change "
            "nothing. The usual cause is passing the same file twice, or "
            "extracting both from the same variant."
            % (source.name, target.name))
    if source.pitch_bits != target.pitch_bits or \
            list(source.k_widths) != list(target.k_widths):
        raise ValueError(
            "%s and %s do not share field widths; this converter re-indexes "
            "between parts of the same family and cannot relayout frames"
            % (source.name, target.name))

    frames, stopped = parse(data, source.pitch_bits, list(source.k_widths))
    report = convert_frames(frames, source, target)
    out = rebuild(frames, len(data), base=data)
    if len(out) != len(data):
        raise AssertionError("conversion changed the stream length")
    return out, report, stopped
