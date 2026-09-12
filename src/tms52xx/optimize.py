"""Optional audio optimisation: better-sounding K indexes, chosen by listening.

WHAT THE DEFAULT CONVERTER DOES, AND WHY IT IS NOT THE WHOLE STORY. The ordinary
conversion maps each parameter independently to the numerically nearest entry in
the destination chip's table. That is deterministic, explainable, and right in
the sense that nothing closer exists -- per coefficient. It is not the best the
chip can sound, because the ten K coefficients are not ten independent knobs:
they are the reflection coefficients of one filter, and rounding each to its own
nearest value lands somewhere the filter as a whole need not be nearest at all.

An experiment measured how much that costs. Around each nearest-mapped K index
it searched the immediate neighbours, one step either way, by coordinate descent
-- and scored every candidate by RENDERING it and comparing the audio against
the same speech played through a real TMS5200's tables. Frame length, frame
type, energy and pitch were held fixed, so any gain is attributable to joint K
selection alone. On a 40-frame stratified sample of Embryon, 39 frames improved
and 1 was already optimal. Notably, typical frames gained MORE in percentage
terms than the worst ones, so the gain is a property of ordinary speech rather
than of a damaged tail.

WHY THE SEARCH IS NOT IN THIS FILE. Scoring a candidate means synthesising it.
The experiment did that through a real speech core's arithmetic, and compared
spectra with a signal-processing library. Understudy is one folder of Python
with nothing to install; it has no synthesiser and no FFT, and writing
approximations of both would mean this tool selected frames by a different
measure than the one that was actually validated -- while reporting the
validated result. So the search stays where it can be run honestly, and what
ships here is its OUTCOME: per frame, which way it stepped each coefficient.

That makes this a lookup, and lookups go stale silently. Hence `guard`: every
override carries a hash of the ten baseline K indexes of the frame it was
measured on, and is applied only if this run produced exactly those. A profile
revision, a different dump, an edited coefficient table -- anything that moves
the baseline -- stops the override instead of shifting it onto a frame it was
not measured for.

WHY A HASH, AND WHY DELTAS. The obvious shape for this file is "field X was 15,
make it 14". That shape cannot be shipped: the "was" half is the real
coefficient data out of a copyrighted ROM, and enough of it is a redistribution
of the speech this project is careful never to redistribute. So an override
stores no absolute index at all -- only which way to step (`delta`, always +1 or
-1) and an opaque hash to check the frame against. The hash covers all ten K
indexes rather than only the ones that move, which makes the check STRICTER than
naming values would have been: a frame differing anywhere in its filter is
refused, not just one differing where the optimiser happened to act.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import reads
from .bitstream import K_FIELDS

#: Data shipped alongside the profiles, one file per profile id.
SCHEMA = "understudy-audio-optimization/1"

#: How far from the baseline a coefficient may end up.
#:
#: The search offers each index only its immediate neighbours, +1 and -1 -- but
#: it runs TWO passes, and the second pass steps from wherever the first left
#: off. So a coefficient the search moved twice ends two places from where the
#: nearest mapping put it, and the neighbourhood being +/-1 does not make the
#: displacement +/-1. Getting this wrong is not academic: bounding it at one
#: step silently discarded 40 of Embryon's 456 optimised frames, because 46 of
#: the 1486 index moves are two.
#:
#: Checked rather than trusted. A data file is just a file, and one claiming a
#: jump of five would otherwise be applied as readily as a legitimate one.
SEARCH_PASSES = 2
MAX_STEP = SEARCH_PASSES

#: How much of the guard digest is stored. A frame's ten K indexes are a small
#: space, so this is a staleness check and not a security boundary; 16 hex
#: characters is far more than enough to catch a baseline that moved, and keeps
#: the data file readable.
GUARD_CHARS = 16


def guard_for(frame) -> str:
    """An opaque fingerprint of one frame's baseline K indexes.

    Covers every K field the frame carries, in field order, so a frame whose
    filter differs anywhere fails the check. Carries no recoverable coefficient
    value: a digest of ten small integers is not a way to ship them.
    """
    present = [n for n in K_FIELDS if n in frame.fields]
    joined = ",".join("%s=%d" % (n, frame.fields[n].index) for n in present)
    return hashlib.sha256(joined.encode("ascii")).hexdigest()[:GUARD_CHARS]


class OptimizationError(ValueError):
    """Optimisation data does not fit the ROM it was asked to optimise."""


def data_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "optimizations"


@dataclass
class FrameOptimization:
    """One frame the optimiser moved, and by how much."""

    phrase: int
    frame: int
    #: field name -> (baseline index, chosen index)
    changed: Dict[str, Tuple[int, int]]
    mcd_db_before: Optional[float] = None
    mcd_db_after: Optional[float] = None

    @property
    def mcd_db_gain(self) -> Optional[float]:
        if self.mcd_db_before is None or self.mcd_db_after is None:
            return None
        return self.mcd_db_before - self.mcd_db_after


@dataclass
class OptimizationReport:
    """What optimisation did to one ROM set, in enough detail to audit it."""

    profile_id: str
    #: Frames the shipped search examined (from the data file, not this run).
    frames_considered: int = 0
    #: Frames where a better-scoring candidate was found and is applied here.
    frames_changed: int = 0
    #: Frames the search examined and left on the baseline choice.
    frames_baseline_retained: int = 0
    frames: List[FrameOptimization] = field(default_factory=list)
    method: Dict = field(default_factory=dict)

    @property
    def k_indexes_changed(self) -> int:
        return sum(len(f.changed) for f in self.frames)

    @property
    def mean_mcd_db_gain(self) -> Optional[float]:
        gains = [f.mcd_db_gain for f in self.frames if f.mcd_db_gain is not None]
        if not gains:
            return None
        return sum(gains) / len(gains)


def available(profile_id: str) -> bool:
    """Is there optimisation data for this profile?"""
    return (data_dir() / ("%s.json" % profile_id)).exists()


def load(profile_id: str) -> dict:
    """Read and validate one profile's optimisation data."""
    path = data_dir() / ("%s.json" % profile_id)
    if not path.exists():
        raise OptimizationError(
            "there is no audio optimisation data for %s. Optimisation is "
            "measured per game by rendering candidate frames and comparing "
            "them against the original chip, so it exists only for sets that "
            "measurement has been run on. Convert without --optimize-audio."
            % profile_id)
    try:
        doc = json.loads(reads.read_text(path))
    except ValueError as exc:
        raise OptimizationError("%s is not readable JSON: %s" % (path, exc))
    if doc.get("schema") != SCHEMA:
        raise OptimizationError(
            "%s declares schema %r, but this build understands %r"
            % (path, doc.get("schema"), SCHEMA))
    if doc.get("profile_id") != profile_id:
        raise OptimizationError(
            "%s is optimisation data for %r, not %r"
            % (path, doc.get("profile_id"), profile_id))
    return doc


def _overrides_for(doc: dict, phrase_index: int) -> Dict[int, dict]:
    phrases = doc.get("phrases") or {}
    entry = phrases.get(str(phrase_index))
    if not entry:
        return {}
    return {int(k): v for k, v in entry.items()}


def optimise_frames(frames: Sequence, phrase_index: int, doc: dict,
                    k_widths: Sequence[int]) -> List[FrameOptimization]:
    """Apply this phrase's overrides to already-converted frames, in place.

    `frames` must be the output of the ordinary conversion: the overrides were
    measured against exactly that, and every one of them says so. Returns what
    was changed. Raises rather than skipping -- an override that does not fit is
    evidence the data and the ROM disagree, and quietly converting without it
    would produce a ROM whose manifest claims an optimisation it did not get.
    """
    applied: List[FrameOptimization] = []
    for frame_index, override in sorted(_overrides_for(doc, phrase_index).items()):
        if frame_index >= len(frames):
            raise OptimizationError(
                "optimisation data names frame %d of phrase %d, which has only "
                "%d frames" % (frame_index, phrase_index, len(frames)))
        frame = frames[frame_index]
        delta = override.get("delta") or {}
        if not delta:
            raise OptimizationError(
                "phrase %d frame %d: optimisation data carries no `delta`"
                % (phrase_index, frame_index))

        # The tested search ran on voiced frames and moved K only. A data file
        # naming anything else is not describing that search.
        if frame.kind != "voiced":
            raise OptimizationError(
                "phrase %d frame %d is a %s frame; audio optimisation was "
                "measured on voiced frames only"
                % (phrase_index, frame_index, frame.kind))

        # Checked BEFORE anything moves, and over the whole filter. Once a
        # single index has been stepped the frame no longer hashes to what was
        # measured, so a guard applied afterwards could never be made to agree.
        want_guard = override.get("guard")
        if not want_guard:
            raise OptimizationError(
                "phrase %d frame %d: optimisation data carries no `guard`. "
                "Without it there is nothing to establish that this frame is "
                "the one the measurement was taken on."
                % (phrase_index, frame_index))
        got_guard = guard_for(frame)
        if got_guard != want_guard:
            raise OptimizationError(
                "phrase %d frame %d: this conversion produced a filter the "
                "optimisation data was not measured on (%s, expected %s). The "
                "data does not describe this ROM -- refusing to apply it."
                % (phrase_index, frame_index, got_guard, want_guard))

        changed: Dict[str, Tuple[int, int]] = {}
        for name in sorted(delta, key=lambda n: K_FIELDS.index(n)
                           if n in K_FIELDS else -1):
            if name not in K_FIELDS:
                raise OptimizationError(
                    "phrase %d frame %d: %s is not a K coefficient. Audio "
                    "optimisation moves K indexes only -- energy, pitch and "
                    "frame length are held fixed."
                    % (phrase_index, frame_index, name))
            spec = frame.fields.get(name)
            if spec is None:
                raise OptimizationError(
                    "phrase %d frame %d does not carry %s"
                    % (phrase_index, frame_index, name))
            step = delta[name]
            if not isinstance(step, int) or isinstance(step, bool) \
                    or abs(step) > MAX_STEP or step == 0:
                raise OptimizationError(
                    "phrase %d frame %d %s: delta %r is outside the measured "
                    "search. It offers each index its neighbours over %d "
                    "passes, so a coefficient may end at most %d place(s) from "
                    "the nearest mapping, and never zero places."
                    % (phrase_index, frame_index, name, step, SEARCH_PASSES,
                       MAX_STEP))
            was = spec.index
            want = was + step
            width = k_widths[K_FIELDS.index(name)]
            if not 0 <= want < (1 << width):
                raise OptimizationError(
                    "phrase %d frame %d %s: stepping %+d from %d leaves the "
                    "%d-bit field. The search that produced this data could "
                    "not have chosen it."
                    % (phrase_index, frame_index, name, step, was, width))
            spec.index = want
            changed[name] = (was, want)

        if changed:
            applied.append(FrameOptimization(
                phrase=phrase_index, frame=frame_index, changed=changed,
                mcd_db_before=override.get("mcd_db_before"),
                mcd_db_after=override.get("mcd_db_after")))
    return applied
