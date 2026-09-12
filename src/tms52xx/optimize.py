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

That makes this a lookup, and lookups go stale silently. A lookup is only worth
as much as its key, and the key here has to cover everything the score depended
on -- which is more than the frame being corrected:

  * `guard` fingerprints the frame AND its successor, every field, because the
    score was measured over both, and because pitch and energy shape that audio
    just as the filter does;
  * `tables` pins the coefficient files, because different tables mean different
    audio from identical indexes -- a change no index-derived guard can see;
  * `profile_version` pins the layout, because phrase and frame numbers are
    coordinates in it;
  * and each override carries the before/after score that justified it, which is
    re-checked here rather than trusted. The search accepted a candidate only
    when it scored strictly better; that rule lived in the search, so it is
    re-stated at the point of use or it is not enforced at all.

Any of those failing stops the conversion. None of them degrades to "apply it
anyway": the failure mode this guards against is a ROM that passes every
structural check while sounding wrong, which nothing downstream would catch.

WHY DIGESTS AND DELTAS. The obvious shape for this file is "field X was 15, make
it 14". That shape cannot be shipped: the "was" half is real coefficient data
out of a copyrighted ROM, and enough of it is a redistribution of the speech
this project is careful never to redistribute. So an override stores no absolute
index -- only which way to step, and digests to check against.

A step is `+1` or `-1` per pass and the search runs two passes, so a coefficient
may end up to two places from the nearest mapping. See `MAX_STEP`.
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


def guard_for(frames: Sequence, index: int) -> str:
    """A fingerprint of everything the measurement's score depended on.

    NOT just the frame's K indexes. The score was mel-cepstral distortion over
    the frame AND ITS SUCCESSOR, rendered -- so the audio it judged was a
    function of this frame's energy and pitch as well as its filter, and of the
    next frame in full. A guard covering only this frame's K would apply a
    correction to a frame whose pitch, energy or successor had moved, and the
    recorded gain would simply not be about the audio produced.

    So both frames go in, every field, with the frame kind alongside: a frame
    that changed kind carries different fields entirely, and its absence from
    the digest would let that pass. The end of the phrase is its own marker,
    because "there is no successor" is part of what was rendered.

    Carries no recoverable coefficient value. That is not a security claim --
    the index space is small -- but the file ships steps and digests rather than
    the values themselves, which is what keeps ROM data out of this repository.
    """
    parts = []
    for i in (index, index + 1):
        if i >= len(frames):
            parts.append("end")
            continue
        frame = frames[i]
        fields = ",".join("%s=%d" % (name, frame.fields[name].index)
                          for name in sorted(frame.fields))
        parts.append("%s|%s" % (frame.kind, fields))
    return hashlib.sha256(";".join(parts).encode("ascii")
                          ).hexdigest()[:GUARD_CHARS]


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
    #: Fingerprint of the override set applied, so a manifest identifies the
    #: measurements and not merely the fact that some ran.
    digest: str = ""

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


def table_digest(tables) -> str:
    """Fingerprint a coefficient table by its CONTENT, not its file.

    Hashing the file's bytes was the obvious thing and it was wrong. Git
    normalises line endings on checkout, so the same table file hashes
    differently on Windows than on Linux -- and a check built on that digest
    refuses every game on one platform and passes on the other. CI caught it;
    a technician on Windows would have met it as "cannot optimise" on a
    perfectly good ROM.

    What the measurements actually depend on is the numbers: every index the
    chip can be asked for, and the field widths that decide what an index even
    means. Those are what get hashed, in a fixed order, so the digest describes
    the coefficients rather than the encoding of the file that carried them.
    """
    canonical = json.dumps({
        "energy": list(tables.energy),
        "pitch": list(tables.pitch),
        "k": [list(row) for row in tables.k],
        "pitch_bits": tables.pitch_bits,
        "k_widths": list(tables.k_widths),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def check_tables(doc: dict, source_sha: str, target_sha: str) -> None:
    """The measurements are only about the tables they were rendered through.

    Both chips' tables shape the audio that was scored: the source decides what
    the baseline mapping reads, the target decides what every candidate index
    means. Supplying a different table file changes the sound without changing
    a single index, so the guards -- which are computed from indexes -- cannot
    notice. This is the check that does.

    Digests come from `table_digest`, over the coefficients themselves. See
    there for why the file's bytes are the wrong thing to hash.
    """
    declared = doc.get("tables") or {}
    for name, got in (("source_sha256", source_sha), ("target_sha256", target_sha)):
        want = declared.get(name)
        if not want:
            raise OptimizationError(
                "optimisation data for %s does not record which %s it was "
                "measured through, so nothing establishes that it describes "
                "this conversion." % (doc.get("profile_id"), name[:-7]))
        if want != got:
            raise OptimizationError(
                "optimisation data for %s was measured against %s %s, but this "
                "run is using %s. The measurements describe audio produced by "
                "different coefficients; refusing to apply them."
                % (doc.get("profile_id"), name[:-7], want[:16], got[:16]))


def check_profile(doc: dict, profile) -> None:
    """The measurements are tied to the layout that produced their coordinates.

    Overrides are addressed by phrase index and frame number. Both are products
    of the profile's layout -- move a pointer table, change a phrase count, and
    the same coordinates name different speech. The guards would catch most of
    that, but only frame by frame, and "most" is not the standard for something
    that gets burned into an EPROM.
    """
    want = doc.get("profile_version")
    if want is None:
        raise OptimizationError(
            "optimisation data for %s does not record which profile version it "
            "was measured against" % doc.get("profile_id"))
    if want != profile.version:
        raise OptimizationError(
            "optimisation data for %s was measured against profile version %s, "
            "and this is version %s. Phrase and frame numbers come from the "
            "layout, so measurements from another version may not describe the "
            "same speech." % (profile.id, want, profile.version))


def digest(doc: dict) -> str:
    """A stable fingerprint of the overrides themselves, for the manifest.

    Over the decisions only, not the surrounding prose: what a later reader
    needs to answer is "were these the corrections applied to my ROM", and
    reformatting the method text should not change the answer.
    """
    canonical = json.dumps(doc.get("phrases") or {}, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def override_count(doc: dict) -> int:
    """How many frame overrides the data file contains, in total."""
    return sum(len(entry.get("frames") or {})
               for entry in (doc.get("phrases") or {}).values())


def check_all_applied(doc: dict, applied: Sequence[FrameOptimization]) -> None:
    """Every override in the file must have reached a frame.

    Shared by both conversion paths on purpose. The way this fails is an alias:
    two pointers naming the same bytes are converted once, under the first
    phrase's index, so an override keyed to the second is never offered a frame
    to act on. Nothing else notices -- the ROM is structurally perfect, every
    check passes, and the manifest says optimisation ran. It would simply not
    have been applied where it was measured.
    """
    reached = {(f.phrase, f.frame) for f in applied}
    missed = []
    for p, entry in sorted((doc.get("phrases") or {}).items(),
                           key=lambda kv: _canonical_index(kv[0], "phrase")):
        phrase = _canonical_index(p, "phrase")
        for f in sorted((entry.get("frames") or {}),
                        key=lambda k: _canonical_index(k, "frame")):
            frame = _canonical_index(f, "frame")
            if (phrase, frame) not in reached:
                missed.append((phrase, frame))
    if missed:
        raise OptimizationError(
            "%d optimisation override(s) were never applied, first phrase %d "
            "frame %d. Usually two pointers name the same bytes, so the phrase "
            "is converted once under the lower index and the other's overrides "
            "never reach a frame. Refusing to report an optimisation that did "
            "not happen." % (len(missed), missed[0][0], missed[0][1]))


def _canonical_index(key, what: str) -> int:
    """A coordinate key, rejected unless it is written the one canonical way.

    `int("00")` and `int("0")` are both 0, so two entries written differently
    address the same frame -- and every downstream count, including the
    completeness check, normalises them the same way and sees one. The result is
    an override that is quietly discarded while the run reports that every
    override was applied. Non-negative, no sign, no padding, no whitespace.
    """
    if not isinstance(key, str) or not key.isdigit() or \
            (len(key) > 1 and key[0] == "0"):
        raise OptimizationError(
            "%s %r is not a canonical index. Coordinates must be written as "
            "plain non-negative decimals with no padding or sign, so that two "
            "spellings cannot name one frame." % (what, key))
    return int(key)


def _phrase_entry(doc: dict, phrase_index: int) -> Optional[dict]:
    phrases = doc.get("phrases") or {}
    return phrases.get(str(phrase_index))


def _overrides_for(doc: dict, phrase_index: int) -> Dict[int, dict]:
    entry = _phrase_entry(doc, phrase_index)
    if not entry:
        return {}
    out: Dict[int, dict] = {}
    for key, value in (entry.get("frames") or {}).items():
        index = _canonical_index(key, "frame")
        if index in out:
            raise OptimizationError(
                "phrase %d names frame %d twice" % (phrase_index, index))
        out[index] = value
    return out


def check_phrase_source(doc: dict, phrase_index: int, original: bytes) -> None:
    """The phrase being corrected must be the phrase that was measured.

    THE PER-FRAME GUARD IS NOT ENOUGH, for two reasons that both come back to it
    being computed from CONVERTED frames.

    Filter state. The score was taken on rendered audio, and what the chip
    sounds like entering a frame depends on where its filter and excitation
    already were -- which is a product of the speech BEFORE it. Change frame 0's
    energy and frame 7's rendered audio changes too, while frame 7 and its
    successor hash exactly as before.

    Collapsed sources. Conversion is many-to-one: two different TMS5200 pitch
    indexes can both map to the same TMS5220 index. Two genuinely different
    original phrases can therefore convert to identical bytes -- identical
    frames, identical guards -- while the TMS5200 REFERENCE they were each
    measured against is different audio. Nothing derived from the converted side
    can see that, by construction.

    Hashing the original phrase closes both. It is also the only check here that
    works on the manual path, where there is no profile to pin a layout with.
    """
    entry = _phrase_entry(doc, phrase_index)
    if not entry:
        return
    want = entry.get("source_sha256")
    if not want:
        raise OptimizationError(
            "phrase %d's optimisation data does not record which speech it was "
            "measured on" % phrase_index)
    got = hashlib.sha256(original).hexdigest()
    if got != want:
        raise OptimizationError(
            "phrase %d is not the speech these corrections were measured on "
            "(%s, expected %s). Two different originals can convert to the same "
            "bytes, and the audio they were scored against is not the same; "
            "refusing to apply them." % (phrase_index, got[:16], want[:16]))


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
        # AN OVERRIDE MUST CARRY A SCORE, AND THE SCORE MUST BE AN IMPROVEMENT.
        #
        # The search accepted a candidate only when it scored strictly better.
        # That rule lived in the search, which does not run here -- so without
        # this, "never chooses a worse candidate" would be a property of the
        # process that produced the file rather than of anything this code does,
        # and a file recording a regression would be applied as readily as a
        # gain. Re-stating the acceptance rule at the point of use is what makes
        # it enforceable.
        before, after = override.get("mcd_db_before"), override.get("mcd_db_after")
        for name, value in (("mcd_db_before", before), ("mcd_db_after", after)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or value != value or value in (float("inf"), float("-inf")):
                raise OptimizationError(
                    "phrase %d frame %d: %s is %r, which is not a score. Every "
                    "override must record the measurement that justified it."
                    % (phrase_index, frame_index, name, value))
        if not after < before:
            raise OptimizationError(
                "phrase %d frame %d: recorded score %.4f -> %.4f is not an "
                "improvement. The search accepted a candidate only when it "
                "scored strictly better; this override does not, so applying "
                "it would make the speech measurably worse."
                % (phrase_index, frame_index, before, after))

        got_guard = guard_for(frames, frame_index)
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
