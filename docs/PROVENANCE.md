# Where the chip tables come from

This project ships no TMS5200 or TMS5220 coefficient data. You supply it.

## Why

This is a practical decision about provenance, and the paragraphs below are not
legal advice. Individual values in these tables are measurements of silicon, but
that observation does not by itself settle anything: selection, transcription
and arrangement can matter, and so can the licence of whatever file you extract
from. The position taken here is to keep that decision with you rather than make
it for you.

The practical problem is provenance. Every convenient machine-readable copy we
located traces back to an emulator source tree. The most complete of those,
PinMAME, is part-way through migrating from the old MAME licence to 3-Clause
BSD, per file, and files that have not been converted remain under terms that
restrict commercial use. Vendoring a generated copy would carry that ambiguity
into every project that depends on this one, permanently, in exchange for saving
each user a single command.

So the extraction is a step you run, against a source you have chosen, under a
licence you have read. To be plain about what that does and does not achieve:
extracting the values yourself is **not a licence workaround**. Output generated
from a file may carry that file's terms with it. You are responsible for
complying with whatever governs the source you use; this project simply declines
to make that choice on your behalf and then hide it in a data file.

## Format

Two files, `tms5200.json` and `tms5220.json`:

```json
{
  "name": "tms5220",
  "pitch_bits": 6,
  "k_widths": [5, 5, 4, 4, 4, 4, 4, 3, 3, 3],
  "energy": [ ... 16 entries ... ],
  "pitch":  [ ... 64 entries; index 0 is unvoiced ... ],
  "k":      [ [ ... ], ... ten tables ... ]
}
```

`pitch` entries are **periods in samples**, not frequencies:
`f0 = 8000 / period`. `ChipTables` validates that every table length matches its
declared field width, so a mis-sized table fails at load rather than producing
quiet nonsense downstream.

## Getting them

**From a PinMAME checkout.** The most practical route. Clone the source and run
the extractor; you need only the source tree, not a built emulator.

```
git clone https://github.com/vpinball/pinmame
python docs/from_pinmame.py pinmame tables/
```

That writes `tables/tms5200.json` and `tables/tms5220.json`, which is what the
`--source-tables` and `--target-tables` options take. The file it reads is
`src/sound/tms5220r.c` — **read the licence header on that specific file in your
own checkout** and satisfy yourself it suits your use before relying on the
output. The clone is a few hundred megabytes; `--depth 1` is enough if you only
want the tables, though the pinned revision below will then not be in it.

### The revision this was last verified against

PinMAME moves, and `tms5220r.c` is hand-maintained C rather than a data file, so
an extractor that reads it is a parser against a moving target. The last
revision this was run against:

| | |
|---|---|
| repository | <https://github.com/vpinball/pinmame> |
| commit | `9ac98e75ade3ce9efc967fa3082cddec8c5ab869` |
| `src/sound/tms5220r.c` sha256 | `21e3e4c16f044f2a380dbbb630ed375061218936256d413802c3f73883afbdc0` |

At that revision the extracted tables were compared value-for-value against an
independently written parser of the same file — 12 tables per part, energy,
pitch and K1–K10 — and matched exactly. That second parser lives in a private
repository and is **not included here**, so the comparison is an assertion about
work done elsewhere, not something you can re-run from this checkout. It is also
only a check on the extractor: it says two readers agree about what the file
says, and nothing about whether PinMAME is right.

What you CAN reproduce here is `tests/test_extractor.py`, which runs the
extractor against a synthetic C file with the same awkward shape as the real one
— positional struct fields, a dead `#if 0` branch holding a decoy table, and
backslash-continued macro bodies — and asserts both the extracted values and
that a changed source shape is refused rather than misparsed.

It writes both tables only after extracting and validating both, so a failure
on the second cannot leave a fresh file beside a stale one. Two renames are
still two renames: a filesystem failure between them could leave one new table
and one old, which is why conversion manifests record the SHA-256 of both table
files.

`from_pinmame.py` checks the source file's SHA-256 against the revision above
and says so if it differs, and it validates every extracted table against the
width its own struct declares. That catches a changed table *shape*. It does not
prove semantic correctness: a reordering of the struct's fields, or a
preprocessor construct the parser does not model — it handles literal `#if 0`
blocks and nothing more — could produce a table of the right size and the wrong
contents. If the hash note appears, compare a few values by eye before relying
on the result.

**From the datasheet.** Texas Instruments' *TMS5220 Voice Synthesis Processor
Data Manual* documents the frame format and the tables. Scanned copies are
mirrored publicly:

* archive.org, [the June 1981 preliminary manual](https://archive.org/details/bitsavers_tidataBooksisProcessorDataManualpreliminaryJun81_7901308)
* archive.org, [an IC datasheet copy](https://archive.org/details/TMS5220)
* [bitsavers](http://bitsavers.org/components/ti/), under `components/ti`

Transcribing by hand is tedious and error-prone, but it is the cleanest
provenance available, and `ChipTables` will catch a mis-keyed table length. Note
that the manual is the TMS5220's: a TMS5200 table transcribed from it would be
the wrong chip, which is the entire problem this project exists to solve.

**From your own measurements.** If you have working silicon and the patience,
this is the only route that owes nothing to anyone else's transcription.

**Sanity-check whatever you get.** A TMS5200 table should report a lowest
reachable f0 near 37.9 Hz and a TMS5220 near 50.3 Hz — see *Verifying what you
loaded* below. If the two files give the same number, you have extracted the
same variant twice, and `convert` will refuse the pair.

## Verifying what you loaded

```python
from tms52xx import ChipTables
t = ChipTables.from_json("tables/tms5220.json")
print(t.lowest_f0_hz)      # expect roughly 50.3 for a TMS5220
```

If that number is not close to 50.3 Hz for a TMS5220 or 37.9 Hz for a TMS5200,
something is wrong with the tables — most likely the pitch column has been read
as frequencies rather than periods.
