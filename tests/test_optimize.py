"""The optional audio optimiser: opt-in, bounded, and structurally inert.

The optimiser moves K indexes that the ordinary conversion already chose. That
makes it the one component here able to change what a burned ROM sounds like
without changing anything a structural check looks at -- so what these tests
guard is mostly the negative space: that it does nothing at all unless asked,
that it cannot move a field further than the search that produced its data did,
and that it refuses rather than adapts when the ROM underneath it is not the one
the measurements were taken from.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic_game                                    # noqa: E402
from synthetic import original, understudy               # noqa: E402
from test_rom import stream                              # noqa: E402
from tms52xx import optimize, parse                      # noqa: E402
from tms52xx.chips import resolve                        # noqa: E402
from tms52xx.convert import convert_stream               # noqa: E402
from tms52xx.optimize import OptimizationError           # noqa: E402
from tms52xx.profiles import Profile                     # noqa: E402
from tms52xx.workflow import ConversionRefused, convert_set   # noqa: E402


def override(frames, index=0, before=9.0, after=4.0, **deltas):
    """One override for `frames[index]`, guarded by its own baseline.

    Carries a scoring pair because the applier insists on one: an override with
    no recorded improvement is refused, so a fixture without scores would be
    testing the refusal rather than the thing under test.
    """
    return {"guard": optimize.guard_for(frames, index), "delta": deltas,
            "mcd_db_before": before, "mcd_db_after": after}


def doc(phrases, source=b"", **extra):
    """A data document. `phrases` maps phrase index -> {frame index -> override}.

    Every phrase gets a source digest, because the applier requires one; the
    tests that care about it supply the bytes.
    """
    import hashlib
    wrapped = {p: {"source_sha256": hashlib.sha256(source).hexdigest(),
                   "frames": f} for p, f in phrases.items()}
    out = {"schema": optimize.SCHEMA, "profile_id": "synthgame",
           "phrases": wrapped}
    out.update(extra)
    return out


def converted_frames(src=None, dst=None):
    """Two voiced frames, converted the ordinary way, ready to optimise."""
    src = src or original()
    dst = dst or understudy()
    data = stream(src, [(7, 0, 40, list(range(10))),
                        (9, 0, 41, list(range(10))),
                        (0xF, 0, 0, [])])
    out, _report, _stopped = convert_stream(data, src, dst)
    frames, _ = parse(out, dst.pitch_bits, list(dst.k_widths))
    return out, frames, dst


class TestOptIn(unittest.TestCase):
    """(2) The optimiser is opt-in, and (1) the default output is unchanged."""

    def test_convert_stream_without_an_optimizer_is_untouched(self):
        src, dst = original(), understudy()
        data = stream(src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        plain, _r, _s = convert_stream(data, src, dst)
        same, _r, _s = convert_stream(data, src, dst, optimizer=None)
        self.assertEqual(plain, same)

    def test_a_set_conversion_defaults_to_no_optimization(self):
        dumps, raw = synthetic_game.build()
        result = convert_set(dict(dumps), Profile(copy.deepcopy(raw), "<synth>"),
                             resolve("tms5220"))
        self.assertIsNone(result.optimization)
        self.assertEqual(result.manifest["audio_optimization"],
                         {"enabled": False})

    def test_the_optimizer_is_the_only_difference(self):
        """(1) Byte-for-byte: opting in is what changes the ROM, nothing else."""
        dumps, raw = synthetic_game.build()
        profile = Profile(copy.deepcopy(raw), "<synth>")
        plain = convert_set(dict(dumps), profile, resolve("tms5220"))
        with tempfile.TemporaryDirectory() as tmp:
            self._install(tmp, doc({}, profile_version=profile.version,
                                   tables=_bundled_table_hashes()))
            opted = convert_set(dict(dumps), profile, resolve("tms5220"),
                                optimize_audio=True)
            # An empty data file changes nothing, which is the control: the
            # machinery ran and the bytes are identical.
            self.assertEqual(plain.after, opted.after)
            self.assertIsNotNone(opted.optimization)

    def _install(self, tmp, document):
        path = Path(tmp) / "synthgame.json"
        path.write_text(json.dumps(document))
        optimize.data_dir = lambda _p=Path(tmp): _p
        self.addCleanup(setattr, optimize, "data_dir", _ORIGINAL_DATA_DIR)
        return path


_ORIGINAL_DATA_DIR = optimize.data_dir


def _bundled_table_hashes():
    """The digests convert_set will compute for the bundled coefficient files."""
    import hashlib
    out = {}
    for role, chip in (("source", "tms5200"), ("target", "tms5220")):
        raw = resolve(chip).table_path.read_bytes()
        out["%s_sha256" % role] = hashlib.sha256(raw).hexdigest()
    return out


class TestBounds(unittest.TestCase):
    """(6) The search neighbourhood, and the table bounds, are enforced here."""

    def test_a_two_step_move_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": override(frames, K1=3)}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("outside the measured search", str(caught.exception))

    def test_two_steps_is_allowed_because_the_search_runs_two_passes(self):
        """The neighbourhood is +/-1; the DISPLACEMENT is not. The second pass
        steps from where the first left off, and 46 of Embryon's 1486 moves
        land two places out -- bounding this at one step drops them."""
        _out, frames, dst = converted_frames()
        was = frames[0].fields["K1"].index
        d = doc({"0": {"0": override(frames, K1=2)}})
        applied = optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertEqual(len(applied), 1)
        self.assertEqual(frames[0].fields["K1"].index, was + 2)

    def test_a_one_step_move_is_allowed(self):
        _out, frames, dst = converted_frames()
        was = frames[0].fields["K1"].index
        d = doc({"0": {"0": override(frames, K1=1)}})
        applied = optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertEqual(len(applied), 1)
        self.assertEqual(frames[0].fields["K1"].index, was + 1)

    def test_an_index_that_does_not_fit_the_field_is_refused(self):
        _out, frames, dst = converted_frames()
        width = list(dst.k_widths)[0]
        top = (1 << width) - 1
        frames[0].fields["K1"].index = top
        d = doc({"0": {"0": override(frames, K1=1)}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("leaves the", str(caught.exception))

    def test_only_k_fields_may_move(self):
        """(7) Pitch is not the optimiser's to touch, and neither is energy."""
        for field in ("pitch", "energy"):
            _out, frames, dst = converted_frames()
            d = doc({"0": {"0": {"guard": optimize.guard_for(frames, 0),
                                 "delta": {field: 1},
                                 "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
            with self.assertRaises(OptimizationError) as caught:
                optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
            self.assertIn("K coefficient", str(caught.exception))


class TestGuards(unittest.TestCase):
    """(5)/(4) A stale or mismatched measurement is refused, never adapted."""

    def test_a_baseline_that_does_not_match_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": {"guard": "0000000000000000",
                             "delta": {"K1": 1},
                             "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("was not measured on", str(caught.exception))

    def test_a_zero_delta_is_refused_rather_than_ignored(self):
        """(5) A frame the search left alone gets no entry, not a null one."""
        _out, frames, dst = converted_frames()
        was = frames[0].fields["K1"].index
        d = doc({"0": {"0": override(frames, K1=0)}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("outside the measured search", str(caught.exception))
        self.assertEqual(frames[0].fields["K1"].index, was)

    def test_a_frame_past_the_end_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"99": {"guard": "x", "delta": {"K1": 1},
                              "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        with self.assertRaises(OptimizationError):
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))

    def test_a_non_voiced_frame_is_refused(self):
        """The measured search ran on voiced frames; nothing else qualifies."""
        src, dst = original(), understudy()
        data = stream(src, [(7, 0, 0, list(range(4))), (0xF, 0, 0, [])])
        out, _r, _s = convert_stream(data, src, dst)
        frames, _ = parse(out, dst.pitch_bits, list(dst.k_widths))
        self.assertEqual(frames[0].kind, "unvoiced")
        d = doc({"0": {"0": override(frames, K1=1)}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("voiced frames only", str(caught.exception))

    def test_mismatched_expect_and_apply_are_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": {"delta": {"K1": 1},
                             "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("no `guard`", str(caught.exception))


class TestStructure(unittest.TestCase):
    """(3) Optimisation may not disturb frame structure or encoded length."""

    def test_length_and_frame_kinds_survive(self):
        src, dst = original(), understudy()
        data = stream(src, [(7, 0, 40, list(range(10))),
                            (9, 0, 41, list(range(10))),
                            (0xF, 0, 0, [])])
        plain, _r, _s = convert_stream(data, src, dst)
        before, _ = parse(plain, dst.pitch_bits, list(dst.k_widths))

        def hook(frames):
            step = -1 if frames[0].fields["K3"].index > 0 else 1
            optimize.optimise_frames(
                frames, 0, doc({"0": {"0": override(frames, K3=step)}}),
                list(dst.k_widths))

        opted, _r, _s = convert_stream(data, src, dst, optimizer=hook)
        after, _ = parse(opted, dst.pitch_bits, list(dst.k_widths))
        self.assertEqual(len(opted), len(plain))
        self.assertEqual(len(after), len(before))
        self.assertEqual([f.kind for f in after], [f.kind for f in before])
        # Pitch and energy are untouched: (7) again, through the packed bytes.
        for a, b in zip(before, after):
            if a.kind == "voiced":
                self.assertEqual(a.fields["pitch"].index, b.fields["pitch"].index)
                self.assertEqual(a.fields["energy"].index,
                                 b.fields["energy"].index)


class TestDeterminism(unittest.TestCase):
    """(10) The same input and the same data produce the same bytes."""

    def test_two_runs_agree(self):
        src, dst = original(), understudy()
        data = stream(src, [(7, 0, 40, list(range(10))), (0xF, 0, 0, [])])
        results = []
        for _ in range(2):
            def hook(frames):
                optimize.optimise_frames(
                    frames, 0, doc({"0": {"0": override(frames, K2=1)}}),
                    list(dst.k_widths))
            out, _r, _s = convert_stream(data, src, dst, optimizer=hook)
            results.append(out)
        self.assertEqual(results[0], results[1])


class TestLoading(unittest.TestCase):
    def test_an_unknown_profile_is_a_clear_refusal(self):
        with self.assertRaises(OptimizationError) as caught:
            optimize.load("no-such-game-at-all")
        self.assertIn("no audio optimisation data", str(caught.exception))

    def test_a_wrong_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.json").write_text(json.dumps(
                {"schema": "something-else", "profile_id": "x"}))
            optimize.data_dir = lambda _p=Path(tmp): _p
            self.addCleanup(setattr, optimize, "data_dir", _ORIGINAL_DATA_DIR)
            with self.assertRaises(OptimizationError) as caught:
                optimize.load("x")
            self.assertIn("schema", str(caught.exception))

    def test_data_for_another_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.json").write_text(json.dumps(
                {"schema": optimize.SCHEMA, "profile_id": "somebody-else"}))
            optimize.data_dir = lambda _p=Path(tmp): _p
            self.addCleanup(setattr, optimize, "data_dir", _ORIGINAL_DATA_DIR)
            with self.assertRaises(OptimizationError):
                optimize.load("x")


if __name__ == "__main__":
    unittest.main()


class TestScoreIsEnforced(unittest.TestCase):
    """(4) "Never chooses a worse candidate" has to be enforced HERE.

    The search accepted a candidate only when it scored strictly better, but the
    search does not run at conversion time -- so without re-checking, that
    property would belong to whatever produced the data file rather than to this
    code, and a file recording a regression would apply just as readily.
    """

    def _apply(self, before, after):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": override(frames, before=before, after=after, K1=1)}})
        return optimize.optimise_frames(frames, 0, d, list(dst.k_widths))

    def test_a_recorded_regression_is_refused(self):
        with self.assertRaises(OptimizationError) as caught:
            self._apply(1.0, 2.0)
        self.assertIn("not an improvement", str(caught.exception))

    def test_an_unchanged_score_is_refused(self):
        with self.assertRaises(OptimizationError):
            self._apply(1.0, 1.0)

    def test_a_missing_score_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": {"guard": optimize.guard_for(frames, 0),
                             "delta": {"K1": 1}}}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("not a score", str(caught.exception))

    def test_a_nan_score_is_refused(self):
        with self.assertRaises(OptimizationError):
            self._apply(1.0, float("nan"))

    def test_an_infinite_score_is_refused(self):
        with self.assertRaises(OptimizationError):
            self._apply(float("inf"), 1.0)

    def test_a_genuine_improvement_is_applied(self):
        self.assertEqual(len(self._apply(9.0, 4.0)), 1)


class TestGuardCoversWhatWasScored(unittest.TestCase):
    """(4) The score spanned the frame AND its successor, and depended on the
    frame's pitch and energy as well as its filter. A guard over this frame's K
    alone would let a correction land on audio it was never measured against."""

    def _doc_for(self, frames):
        return doc({"0": {"0": override(frames, K1=1)}})

    def test_a_changed_pitch_invalidates_the_override(self):
        _out, frames, dst = converted_frames()
        d = self._doc_for(frames)
        frames[0].fields["pitch"].index += 1
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("was not measured on", str(caught.exception))

    def test_a_changed_energy_invalidates_the_override(self):
        _out, frames, dst = converted_frames()
        d = self._doc_for(frames)
        frames[0].fields["energy"].index += 1
        with self.assertRaises(OptimizationError):
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))

    def test_a_changed_successor_invalidates_the_override(self):
        _out, frames, dst = converted_frames()
        d = self._doc_for(frames)
        frames[1].fields["K1"].index += 1
        with self.assertRaises(OptimizationError):
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))


class TestCompleteness(unittest.TestCase):
    """(8) An override that never reached a frame must not be reported as applied.

    Aliased pointers are the way this happens: identical extents are converted
    once, under the lower index, so overrides keyed to the other are skipped in
    silence while every structural check still passes."""

    def test_an_unreached_override_is_refused(self):
        d = doc({"3": {"0": {"guard": "x", "delta": {"K1": 1},
                             "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.check_all_applied(d, [])
        self.assertIn("never applied", str(caught.exception))

    def test_a_fully_applied_set_passes(self):
        d = doc({"3": {"7": {"guard": "x", "delta": {"K1": 1},
                             "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        optimize.check_all_applied(d, [optimize.FrameOptimization(
            phrase=3, frame=7, changed={"K1": (1, 2)})])


class TestTableAndProfileBinding(unittest.TestCase):
    """(4) Different coefficient tables mean different audio from identical
    indexes -- a change no index-derived guard can see."""

    def test_a_different_target_table_is_refused(self):
        d = doc({}, tables={"source_sha256": "a" * 64,
                            "target_sha256": "b" * 64})
        with self.assertRaises(OptimizationError) as caught:
            optimize.check_tables(d, "a" * 64, "c" * 64)
        self.assertIn("measured against target", str(caught.exception))

    def test_matching_tables_pass(self):
        d = doc({}, tables={"source_sha256": "a" * 64,
                            "target_sha256": "b" * 64})
        optimize.check_tables(d, "a" * 64, "b" * 64)

    def test_unrecorded_tables_are_refused(self):
        with self.assertRaises(OptimizationError):
            optimize.check_tables(doc({}), "a" * 64, "b" * 64)

    def test_a_different_profile_version_is_refused(self):
        class FakeProfile:
            id, version = "synthgame", 9
        with self.assertRaises(OptimizationError) as caught:
            optimize.check_profile(doc({}, profile_version=1), FakeProfile())
        self.assertIn("profile version", str(caught.exception))


class TestPhraseSourceBinding(unittest.TestCase):
    """Conversion is many-to-one, so the converted side cannot identify itself.

    Two different TMS5200 originals can convert to byte-identical frames while
    the TMS5200 audio each was scored against is different. Nothing derived from
    the output can tell them apart -- only the original bytes can."""

    def test_the_measured_source_is_required(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"0": override(frames, K1=1)}}, source=b"measured")
        d["phrases"]["0"].pop("source_sha256")
        with self.assertRaises(OptimizationError) as caught:
            optimize.check_phrase_source(d, 0, b"measured")
        self.assertIn("does not record which speech", str(caught.exception))

    def test_a_different_original_is_refused(self):
        _out, frames, _dst = converted_frames()
        d = doc({"0": {"0": override(frames, K1=1)}}, source=b"measured")
        with self.assertRaises(OptimizationError) as caught:
            optimize.check_phrase_source(d, 0, b"something else")
        self.assertIn("not the speech these corrections were measured on",
                      str(caught.exception))

    def test_the_measured_original_passes(self):
        _out, frames, _dst = converted_frames()
        d = doc({"0": {"0": override(frames, K1=1)}}, source=b"measured")
        optimize.check_phrase_source(d, 0, b"measured")

    def test_a_phrase_with_no_overrides_needs_no_digest(self):
        optimize.check_phrase_source(doc({}), 3, b"anything")


class TestCanonicalCoordinates(unittest.TestCase):
    """Two spellings of one coordinate let an override vanish silently.

    `int("00") == int("0")`, so a second entry addresses a frame already
    handled -- and the completeness check normalises identically, so it sees one
    override, one application, and reports that everything was applied."""

    def test_a_padded_frame_index_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"00": override(frames, K1=1)}})
        with self.assertRaises(OptimizationError) as caught:
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))
        self.assertIn("canonical", str(caught.exception))

    def test_a_signed_frame_index_is_refused(self):
        _out, frames, dst = converted_frames()
        d = doc({"0": {"+1": override(frames, K1=1)}})
        with self.assertRaises(OptimizationError):
            optimize.optimise_frames(frames, 0, d, list(dst.k_widths))

    def test_completeness_refuses_a_padded_phrase_index(self):
        d = doc({"03": {"0": {"guard": "x", "delta": {"K1": 1},
                              "mcd_db_before": 9.0, "mcd_db_after": 4.0}}})
        with self.assertRaises(OptimizationError):
            optimize.check_all_applied(d, [])

    def test_override_count_sees_every_entry(self):
        d = doc({"0": {"1": {}, "2": {}}, "3": {"4": {}}})
        self.assertEqual(optimize.override_count(d), 3)
