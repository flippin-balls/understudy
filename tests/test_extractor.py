"""The table extractor, against a synthetic C file rather than PinMAME.

WHY A FIXTURE AND NOT THE REAL FILE. `from_pinmame.py` is the step every user
runs, and testing it against a real PinMAME checkout would mean either shipping
that file -- exactly what this project declines to do -- or a test that silently
skips for everyone who has not cloned PinMAME.

So the fixture below is written here, from scratch, with invented numbers. It is
not TMS5200 or TMS5220 data. What it reproduces is the SHAPE of the real file,
including the three features that make extraction more than a regex:

  * the tables are fields of a `struct tms5100_coeffs` instance, positional and
    unnamed, so they must be read in declaration order;
  * a superseded copy of one table sits in an `#if 0 ... #else ... #endif`, so a
    parser that ignores the preprocessor picks the dead one; and
  * the live tables are written as macro references with backslash-continued
    bodies, so a parser that does not expand macros finds an empty struct.

Each has its own test.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))

import from_pinmame                                      # noqa: E402

#: Small enough to read, shaped like the real thing. Widths are the genuine
#: TMS52xx field widths because the extractor validates against them; every
#: coefficient VALUE is invented.
K_WIDTHS = [5, 5, 4, 4, 4, 4, 4, 3, 3, 3]


def _k_table(index: int, width: int) -> str:
    values = [(index + 1) * 100 - i for i in range(1 << width)]
    return "{ " + ", ".join(str(v) for v in values) + " }"


def _k_tables() -> str:
    """Backslash-continued across lines, exactly as the real file writes it."""
    return "{ \\\n" + ", \\\n".join(_k_table(i, w)
                                     for i, w in enumerate(K_WIDTHS)) + " }"


ENERGY = [0, 1, 2, 3, 4, 6, 8, 11, 16, 23, 33, 47, 63, 85, 114, 0]
PITCH_LIVE = [0] + [15 + i for i in range(63)]
PITCH_DEAD = [0] + [900 + i for i in range(63)]      # unmistakably the wrong one


def _list(values) -> str:
    return "{ " + ", ".join(str(v) for v in values) + " }"


def fixture_source() -> str:
    """A C file with the same awkward features as the real one."""
    return """
/* A synthetic stand-in. The values here are invented and are not any real
   chip's coefficients. */

#define FIXTURE_ENERGY %(energy)s

// A macro body split across lines with backslashes, as the real file does.
#define FIXTURE_PITCH { 0, \\
%(pitch_tail)s }

#define FIXTURE_KTABLE %(ktable)s

struct tms5100_coeffs fixture_dead_coeff =
{
    /* subtype   */ 1,
    /* num_k     */ 10,
    /* energy    */ 4,
    /* pitch     */ 6,
    /* kbits     */ %(kbits)s,
    FIXTURE_ENERGY,
    %(dead_pitch)s,
    FIXTURE_KTABLE
};

#if 0
/* Superseded. A parser that ignores the preprocessor picks this one. */
struct tms5100_coeffs fixture_live_coeff =
{
    /* subtype   */ 1,
    /* num_k     */ 10,
    /* energy    */ 4,
    /* pitch     */ 6,
    /* kbits     */ %(kbits)s,
    FIXTURE_ENERGY,
    %(dead_pitch)s,
    FIXTURE_KTABLE
};
#else
struct tms5100_coeffs fixture_live_coeff =
{
    /* subtype   */ 1,
    /* num_k     */ 10,
    /* energy    */ 4,
    /* pitch     */ 6,
    /* kbits     */ %(kbits)s,
    FIXTURE_ENERGY,
    FIXTURE_PITCH,
    FIXTURE_KTABLE
};
#endif
""" % {"energy": _list(ENERGY),
       "pitch_tail": ", ".join(str(v) for v in PITCH_LIVE[1:]),
       "ktable": _k_tables(),
       "kbits": _list(K_WIDTHS),
       "dead_pitch": _list(PITCH_DEAD)}


def prepared(text: str) -> str:
    """The same preparation pipeline `main` runs, in the same order."""
    raw = from_pinmame.strip_comments(text)
    live = from_pinmame.drop_dead_blocks(raw)
    return from_pinmame.expand_macros(live, from_pinmame.collect_macros(live))


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.text = prepared(fixture_source())

    def test_extracts_every_table_exactly(self):
        got = from_pinmame.build(self.text, "fixture_live_coeff", "fixture")
        self.assertEqual(got["pitch_bits"], 6)
        self.assertEqual(got["k_widths"], K_WIDTHS)
        self.assertEqual(got["energy"], ENERGY)
        self.assertEqual(got["pitch"], PITCH_LIVE)
        self.assertEqual(len(got["k"]), 10)
        for i, width in enumerate(K_WIDTHS):
            self.assertEqual(got["k"][i],
                             [(i + 1) * 100 - j for j in range(1 << width)],
                             "K%d" % (i + 1))

    def test_takes_the_live_branch_not_the_dead_one(self):
        """The distinguishing test: the two arms differ only in the pitch table."""
        got = from_pinmame.build(self.text, "fixture_live_coeff", "fixture")
        self.assertEqual(got["pitch"], PITCH_LIVE)
        self.assertNotEqual(got["pitch"], PITCH_DEAD)

    def test_ignoring_the_preprocessor_would_pick_the_wrong_table(self):
        """The previous test's counterpart: the dead branch really is a trap.

        Without `drop_dead_blocks` the `#if 0` copy is still in the text, and
        because it is declared first it is what a brace-matching search finds.
        """
        no_preprocessor = from_pinmame.expand_macros(
            from_pinmame.strip_comments(fixture_source()),
            from_pinmame.collect_macros(fixture_source()))
        got = from_pinmame.build(no_preprocessor, "fixture_live_coeff", "fixture")
        self.assertEqual(got["pitch"], PITCH_DEAD)

    def test_macros_are_expanded(self):
        """Without expansion the struct's fields are bare identifiers."""
        unexpanded = from_pinmame.drop_dead_blocks(
            from_pinmame.strip_comments(fixture_source()))
        self.assertIn("FIXTURE_KTABLE", unexpanded)
        with self.assertRaises(SystemExit):
            from_pinmame.build(unexpanded, "fixture_live_coeff", "fixture")

    def test_multi_line_macro_bodies_survive(self):
        """The pitch macro is backslash-continued; all 64 entries must arrive."""
        got = from_pinmame.build(self.text, "fixture_live_coeff", "fixture")
        self.assertEqual(len(got["pitch"]), 64)
        self.assertEqual(got["pitch"][-1], PITCH_LIVE[-1])

    def test_comments_do_not_become_data(self):
        """Field comments contain digits -- `/* num_k */ 10` -- and must not count."""
        got = from_pinmame.build(self.text, "fixture_live_coeff", "fixture")
        self.assertEqual(len(got["energy"]), 16)
        self.assertEqual(len(got["k_widths"]), 10)


class TestExtractorRefusals(unittest.TestCase):
    """A changed source shape must fail loudly, not produce a plausible table.

    This is the claim `docs/PROVENANCE.md` makes about later PinMAME revisions,
    so it needs to be demonstrated rather than asserted.
    """

    def _mangled(self, old: str, new: str) -> str:
        text = fixture_source()
        self.assertIn(old, text)
        return prepared(text.replace(old, new))

    def test_a_missing_struct_is_an_error(self):
        with self.assertRaises(SystemExit):
            from_pinmame.build(prepared(fixture_source()), "no_such_coeff", "x")

    def test_a_short_energy_table_is_rejected(self):
        text = self._mangled(_list(ENERGY), _list(ENERGY[:-1]))
        with self.assertRaises(SystemExit) as caught:
            from_pinmame.build(text, "fixture_live_coeff", "fixture")
        self.assertIn("energy table", str(caught.exception))

    def test_a_short_pitch_table_is_rejected(self):
        text = self._mangled(", ".join(str(v) for v in PITCH_LIVE[1:]),
                             ", ".join(str(v) for v in PITCH_LIVE[1:-1]))
        with self.assertRaises(SystemExit) as caught:
            from_pinmame.build(text, "fixture_live_coeff", "fixture")
        self.assertIn("pitch table", str(caught.exception))

    def test_a_k_table_of_the_wrong_length_is_rejected(self):
        good = _k_table(0, K_WIDTHS[0])
        text = self._mangled(good, good.replace("{ ", "{ 0, ", 1))
        with self.assertRaises(SystemExit) as caught:
            from_pinmame.build(text, "fixture_live_coeff", "fixture")
        self.assertIn("K1", str(caught.exception))

    def test_a_changed_k_count_is_rejected(self):
        text = self._mangled("/* num_k     */ 10", "/* num_k     */ 9")
        with self.assertRaises(SystemExit) as caught:
            from_pinmame.build(text, "fixture_live_coeff", "fixture")
        self.assertIn("10 K tables", str(caught.exception))

    def test_unexpected_energy_bits_are_rejected(self):
        text = self._mangled("/* energy    */ 4", "/* energy    */ 5")
        with self.assertRaises(SystemExit) as caught:
            from_pinmame.build(text, "fixture_live_coeff", "fixture")
        self.assertIn("energy_bits", str(caught.exception))

    def test_unbalanced_braces_are_an_error(self):
        text = prepared(fixture_source()).replace("fixture_live_coeff =\n{",
                                                  "fixture_live_coeff =\n{ {", 1)
        with self.assertRaises(SystemExit):
            from_pinmame.build(text, "fixture_live_coeff", "fixture")


class TestExtractorEndToEnd(unittest.TestCase):
    """`main` writes JSON that `ChipTables` will actually load."""

    def test_writes_loadable_json(self):
        sys.path.insert(0, str(ROOT / "src"))
        from tms52xx.tables import ChipTables

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fake-pinmame"
            (root / "src" / "sound").mkdir(parents=True)
            (root / "src" / "sound" / "tms5220r.c").write_text(
                fixture_source().replace("fixture_live_coeff", "tms5220_coeff")
                                .replace("fixture_dead_coeff", "tms5200_coeff"))
            out = Path(tmp) / "tables"
            # main() reports to stdout; capture it so `unittest discover` output
            # stays readable.
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(
                    from_pinmame.main(["from_pinmame.py", str(root), str(out)]), 0)
            self.assertIn("Check the licence header", buffer.getvalue())

            for name in ("tms5200", "tms5220"):
                table = ChipTables.from_json(out / ("%s.json" % name))
                self.assertEqual(table.name, name)
                self.assertEqual(table.pitch_bits, 6)
                self.assertEqual(len(table.pitch), 64)

    def test_an_unverified_source_revision_is_flagged(self):
        """The fixture is not the pinned file, so the note must appear."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fake-pinmame"
            (root / "src" / "sound").mkdir(parents=True)
            (root / "src" / "sound" / "tms5220r.c").write_text(
                fixture_source().replace("fixture_live_coeff", "tms5220_coeff")
                                .replace("fixture_dead_coeff", "tms5200_coeff"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                from_pinmame.main(["x", str(root), str(Path(tmp) / "out")])
            self.assertIn("not the revision this extractor was verified",
                          buffer.getvalue())

    def test_neither_table_is_written_if_the_second_fails(self):
        """A stale file beside a fresh one is worse than neither."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fake-pinmame"
            (root / "src" / "sound").mkdir(parents=True)
            # tms5200_coeff parses; tms5220_coeff has a short energy table.
            text = (fixture_source().replace("fixture_dead_coeff",
                                             "tms5200_coeff")
                    .replace("fixture_live_coeff", "tms5220_coeff"))
            broken = text.replace(_list(ENERGY), _list(ENERGY[:-1]), 1)
            (root / "src" / "sound" / "tms5220r.c").write_text(broken)
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    from_pinmame.main(["x", str(root), str(out)])
            written = sorted(p.name for p in out.iterdir()) if out.exists() else []
            self.assertEqual(written, [], "a partial pair was left behind")

    def test_missing_checkout_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as caught:
                from_pinmame.main(["from_pinmame.py", tmp, tmp])
            self.assertIn("point this at a PinMAME checkout",
                          str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
