# Where the chip tables come from

Understudy bundles the TMS5200 and TMS5220 coefficient tables in
`src/tms52xx/data/`. Supported conversions need no separate extraction step.

This page records the source and verification path for that data.
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) is the license record.

## Bundled source

| | |
|---|---|
| Upstream | MAME, `src/devices/sound/tms5110r.hxx` |
| License | BSD-3-Clause, from the file header |
| Verification | decap/PROMOUT notes recorded upstream |

MAME records the TMS5200 table as decap-verified and also matching an earlier
PROMOUT dump. Its notes likewise state that the TMS5220C decap matches the
TMS5220NL table exactly.

The bundled BSD-3-Clause notice is included in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and
`LICENSES/BSD-3-Clause.txt`.

This is the project's reading of the source and license metadata, not legal
advice.

## Reproduce the extraction

```text
git clone https://github.com/mamedev/mame
python tools/extract_tables.py mame src/tms52xx/data/
git diff --stat src/tms52xx/data/
```

A clean diff means the generated files match the bundled copies. The extractor
also prints the upstream file hash and license header.

It can compare PinMAME's `src/sound/tms5220r.c` as well. The bundled data comes
from MAME because the relevant MAME source file carries an explicit
BSD-3-Clause header.

## Using custom tables

The research commands accept `--source-tables` and `--target-tables`. The
manifest records and hashes custom files, but Understudy cannot establish that a
file you supply actually describes the chip name you gave it.

Changing the tables also steps outside the evidence attached to bundled profile
and optimizer data.

## File format

The bundled files are `tms5200.json` and `tms5220.json`:

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

Pitch entries are periods in samples rather than frequencies:

```text
f0 = 8000 / period
```

`ChipTables` validates table lengths against their declared field widths when a
file is loaded.

## Other published copies

Several speech projects carry related tables:

| project | license | 5200 and 5220? | relationship |
|---|---|---|---|
| PinMAME `src/sound/tms5220r.c` | per-file, mid-migration | yes | matches the reference values used here |
| [Talkie](https://github.com/ArminJo/Talkie) `src/TalkieLPC.h` | GPL-3.0 | 5220 only | matches MAME/PinMAME and cites MAME |
| [python_wizard](https://github.com/ptwz/python_wizard) `lpcplayer/tables.py` | repo says MIT | yes | values match MAME/PinMAME |
| [BlueWizard](https://github.com/patrick99e99/BlueWizard) `CodingTable.m` | MIT | 5220 only | differs from MAME/PinMAME |
| [TMS Express](https://github.com/tornupnegatives/TMS-Express) | GPL-3.0 | 5220 only | 5220-oriented tooling |

The downstream copies are useful cross-checks, but their repository license does
not by itself establish the provenance of copied table values. Using the
upstream MAME file with its own license header keeps the source and terms
explicit.

BlueWizard is also a useful reminder that not every published TMS5220 table is
identical. Its pitch table differs from the MAME/PinMAME TMS5220 table in 21 of
64 entries and uses normalized floating-point values. A conversion made with
those values would not be the same conversion produced by the bundled tables.

That is why Understudy treats coefficient tables as explicit inputs and records
their SHA-256 hashes in every manifest.

## Quick sanity check

```python
from tms52xx import ChipTables

t = ChipTables.from_json("tables/tms5220.json")
print(t.lowest_f0_hz)  # roughly 50.3 for the bundled TMS5220 table
```

The bundled TMS5200 table reports roughly 37.9 Hz. If a supposed TMS5200 and
TMS5220 table report the same pitch floor, check that you did not load the same
variant twice or interpret pitch periods as frequencies.
