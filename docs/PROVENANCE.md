# Where the chip tables come from

This project ships no TMS5200 or TMS5220 coefficient data. You supply it.

## Why

The values themselves are technical facts about the silicon — an index-to-period
mapping is not anyone's creative work — so this is a practical constraint rather
than a legal one.

The practical problem is provenance. Every convenient machine-readable copy of
these tables traces back to an emulator source tree. The most complete of those,
PinMAME, is part-way through migrating from the old MAME licence to 3-Clause
BSD, per file, and files that have not been converted remain under terms that
restrict commercial use. Vendoring a generated copy would carry that ambiguity
into every project that depends on this one, permanently, in exchange for saving
each user a single command.

So the extraction is a step you run, against a source you have chosen, with the
licence position you have decided is right for your use.

## Format

Two files, `tms5200.json` and `tms5220.json`:

```json
{
  "name": "tms5220",
  "pitch_bits": 6,
  "k_widths": [5, 5, 4, 4, 4, 4, 4, 3, 3, 3],
  "energy": [ ... 16 entries ... ],
  "pitch":  [ ... 32 or 64 entries; index 0 is unvoiced ... ],
  "k":      [ [ ... ], ... ten tables ... ]
}
```

`pitch` entries are **periods in samples**, not frequencies:
`f0 = 8000 / period`. `ChipTables` validates that every table length matches its
declared field width, so a mis-sized table fails at load rather than producing
quiet nonsense downstream.

## Getting them

**From a PinMAME checkout.** `from_pinmame.py` in this directory reads the
coefficient tables out of `src/sound/tms5220r.c` and writes both JSON files.
Check the licence header on that specific file in your checkout and satisfy
yourself it suits your use before you rely on the output.

```
python docs/from_pinmame.py /path/to/pinmame tables/
```

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
pitch and K1–K10 — and matched exactly. That is a check on the extractor, not on
PinMAME: it says two different readers agree about what the file says.

`from_pinmame.py` validates every table against the width its own struct
declares, so if a later revision changes the file's shape you should get an
error rather than a quiet misparse. If you do get one, the parser is what needs
fixing.

**From the datasheet.** Texas Instruments' *TMS5220 Voice Synthesis Processor
Data Manual* documents the frame format and the tables. Transcribing by hand is
tedious and error-prone, but it is the cleanest provenance available and the
validation in `ChipTables` will catch a mis-keyed table length.

**From your own measurements.** If you have working silicon and the patience,
this is the only route that owes nothing to anyone else's transcription.

## Verifying what you loaded

```python
from tms52xx import ChipTables
t = ChipTables.from_json("tables/tms5220.json")
print(t.lowest_f0_hz)      # expect roughly 50.3 for a TMS5220
```

If that number is not close to 50.3 Hz for a TMS5220 or 37.9 Hz for a TMS5200,
something is wrong with the tables — most likely the pitch column has been read
as frequencies rather than periods.
