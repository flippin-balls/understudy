# Where the chip tables come from

**Understudy bundles the TMS5200 and TMS5220 coefficient tables.** You do not
need to extract anything to convert a ROM. They live in `src/tms52xx/data/`,
ship inside the installed package, and each file records where it came from.

This page explains what that data is, how to check it yourself, and what else
exists. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) is the licence
record; this is the research one.

## What is bundled, and why that source

| | |
|---|---|
| Upstream | MAME, `src/devices/sound/tms5110r.hxx` |
| Licence | BSD-3-Clause, by that file's own header |
| Verification | decap and PROMOUT, stated upstream per table |

Two things had to be true before bundling anything. Both are checkable:

**The file is BSD-3-Clause.** Its header reads `// license:BSD-3-Clause`, and
MAME's `COPYING` says individual files may be under less restrictive licences
than MAME as a whole, as noted in their header comments. So the notice travels
with the data — that is what `THIRD_PARTY_NOTICES.md` and
`LICENSES/BSD-3-Clause.txt` are, and both ship inside the package.

**The values are decap-verified, not transcribed.** Upstream records, for the
TMS5200, "decapped and imaged by digshadow in March, 2013 […] The LPC table is
verified to match the decap. (It was previously dumped with PROMOUT which
matches as well)"; and for the TMS5220 and 5220C the same, with the 5220C's
table "verified to match the decap and exactly matches TMS5220NL".

This is our reading of the licensing, offered so you can check it rather than
take it on trust. It is not legal advice.

## Checking the bundled data yourself

```
git clone https://github.com/mamedev/mame
python tools/extract_tables.py mame src/tms52xx/data/
git diff --stat src/tms52xx/data/
```

A clean diff means what ships is exactly what upstream holds. The extractor
prints the source file's SHA-256 and licence header, and says so plainly if the
file is not a revision it has been checked against.

It also reads PinMAME's `src/sound/tms5220r.c`, whose tables are identical for
these two parts. That path is for comparison. PinMAME is mid-migration to
per-file BSD-3-Clause and not every file has been converted, which is why the
bundled copy comes from MAME.

## Using your own tables instead

Every command takes `--source-tables` and `--target-tables`. That is the
research path, and the route for a variant these tables do not cover. Understand
what you give up: the manifest records that custom tables were used and hashes
them, but nothing checks that a file you supply describes the part you named.

## A note on extracting data yourself

Extracting values from a file is **not a licence workaround**. Output generated
from a file may carry that file's terms with it. If you build tables from some
other source, you are responsible for complying with whatever governs it.

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

## Where else these tables exist

A reasonable question during this work was whether some other project
publishes these tables under a friendlier licence than MAME's old terms.
Several carry them. What is in each is worth recording, because the answer is
not the one you would hope for — and because it is why the bundled copy comes
from MAME rather than from a downstream repackaging.

| project | licence | has 5200 *and* 5220? | values |
|---|---|---|---|
| PinMAME `src/sound/tms5220r.c` | per-file, mid-migration | yes | the reference here |
| [Talkie](https://github.com/ArminJo/Talkie) `src/TalkieLPC.h` | GPL-3.0 | 5220 only | identical to PinMAME's |
| [python_wizard](https://github.com/ptwz/python_wizard) `lpcplayer/tables.py` | repo says MIT | yes | identical to PinMAME's |
| [BlueWizard](https://github.com/patrick99e99/BlueWizard) `CodingTable.m` | MIT | 5220 only | **differs** |
| [TMS Express](https://github.com/tornupnegatives/TMS-Express) | GPL-3.0 | 5220 only | — |

Two things follow.

**A permissive tag downstream does not launder the ancestry.** python_wizard's
`lpcplayer/tables.py` is the closest thing to a drop-in: it is Python, it has
both variants, and every value in it is identical to what `tools/extract_tables.py`
extracts — energy, pitch and K1–K10, both parts, checked field by field. Its
repository declares MIT. But its own README says `lpcplayer` is "based on
talkie", Talkie is GPL-3.0, and Talkie's `TalkieLPC.h` header says where the
numbers came from in as many words:

> Values can be found on
> https://github.com/mamedev/mame/blob/master/src/devices/sound/tms5110r.hxx

So that route is an MIT tag over a file derived from a GPL-3.0 project over data
from MAME. That is more ambiguity than going to the upstream and reading its
licence header yourself, not less. Nothing here is an accusation against those
projects — they are all doing something legitimate and useful, and Talkie in
particular is scrupulous about saying where its values came from.

**The copies do not all agree, which is the more practical hazard.**
BlueWizard's tables are not a copy of MAME's at all. Its pitch table differs
from PinMAME's TMS5220 in **21 of its 64 entries**, and it matches **none of the
eight variants** MAME defines — not the 5200, 5220 or 5220C, and not the
5100/5110 or patent tables either. It also holds normalised floats rather than
integer periods, and carries no second variant. So it is a genuinely separate
transcription, and it disagrees. Neither set is self-evidently "the right one",
and a conversion done with one is not the conversion the other would have
produced.

That is why this tool takes tables as *input* rather than baking a set in, and
why every manifest records the SHA-256 of both table files. A conversion is
reproducible and attributable to the exact tables that produced it, whichever
set you decided to trust.

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
