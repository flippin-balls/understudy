# understudy

**A replacement TMS5220 can speak the ROM data from a Bally Squawk & Talk, but
not correctly. Understudy fixes the ROM data.**

It converts TMS5200 speech parameters to the coefficient tables used by the
TMS5220, TMS5220C and TSP5220C while keeping the ROM layout and phrase timing
intact. The result is a set of files you can burn into replacement EPROMs.

Understudy is an open-source preservation project from
[Flashback Fleet LLC](https://github.com/flippin-balls), who run these machines
on location and would rather they kept talking.

> **Pre-1.0:** Embryon has been converted and played on a real Squawk & Talk with
> a TMS5220. The other 15 bundled profiles have passed structural and board
> simulation checks but have not been heard on hardware. See
> [validation](docs/VALIDATION.md) for exactly what has and has not been tested.

## Fixing a board

If you have never used a command line, use the
[step-by-step repair walkthrough](docs/REPAIR_WALKTHROUGH.md). It starts with
checking whether Python is installed and ends with burning and fitting the
EPROMs.

### What you need

- the sound ROMs from your machine, read as files;
- a blank EPROM of the right type for each speech device;
- a TMS5220, TMS5220C or TSP5220C;
- Python 3.9 or newer.

The three replacement parts use the same converted data. Whether a particular
part is electrically suitable for your board is a separate question; see
[CHIPS.md](docs/CHIPS.md).

You do not need MAME, PinMAME, coefficient tables, or Python packages. Everything
needed for a supported game is in the repository.

### Get Understudy

Click the green **Code** button on GitHub, choose **Download ZIP**, and unzip it.
There is nothing to install. If you use git:

```
git clone https://github.com/flippin-balls/understudy
cd understudy
```

On Windows, open PowerShell in that folder and check it with:

```
py understudy.py --version
```

On macOS or Linux, use `python3 understudy.py --version`. The examples below use
`python`; use whichever command works on your machine.

### Convert a ROM set

Point `convert-set` at a folder, zip file, or the individual dumps:

```
python understudy.py convert-set my-roms/
python understudy.py convert-set embryon.zip
python understudy.py convert-set 841-01_4.716 841-02_5.532
```

Understudy identifies the game by hash, works out which dump belongs in each
socket, defaults to a TMS5220 target, and writes the result to
`understudy-out/`. Extra files in a folder or zip are ignored.

If you only want to identify the set first:

```
python understudy.py identify my-roms/
```

Your input dumps are never modified. To check a conversion without writing any
files, add `--dry-run`.

### Before you burn anything

`convert-set` finishes with a report like this:

```
====================================================================
  CHECK THIS BEFORE YOU BURN ANYTHING
====================================================================
profile      Bally Embryon (1981)  (embryon v4, status silicon-verified)
chips        tms5200  ->  tms5220

input dumps
  U4   2716       2048 bytes  sha256 8495958b46c73f98840adff7
  U5   2532       4096 bytes  sha256 f24559ad001b4cbb1ef4442a

conversion
  phrases                20
  frames                 850
  frame kinds preserved  850 of 850
  clamped to pitch floor 17 (2.0%)

output devices
  U4   2716       2048 bytes  1560 changed  100% converted
       burn into 2716: understudy-out/841-01_4_U4_2716_tms5220.716
  U5   2532       4096 bytes  1948 changed  61% converted
       burn into 2532: understudy-out/841-02_5_U5_2532_tms5220.532
====================================================================
```

The important lines are under **output devices**. They tell you the socket, the
EPROM type to select in your programmer, and the file to burn. Program each file
as raw binary and verify it after programming.

Keep the original EPROMs. Also keep the generated manifest; it records hashes,
conversion details, and output filenames without containing ROM data.

## Supported games

| game | status | phrases | revisions covered |
|---|---|---:|---:|
| Bally **Centaur** (1981) | `board-simulated` | 37 | 3 |
| Bally **Eight Ball Deluxe** (1981) | `board-simulated` | 42 | 6 |
| Bally **Elektra** (1981) | `board-simulated` | 16 | 2 |
| Bally **Embryon** (1981) | `silicon-verified` | 20 | 6 |
| Bally **Fathom** (1981) | `board-simulated` | 26 | 3 |
| Bally **Fireball II** (1981) | `board-simulated` | 16 | 2 |
| Bally **Flash Gordon** (1981) | `board-simulated` | 24 | 2 |
| Bally **Flash Gordon (French)** (1981) | `board-simulated` | 24 | 2 |
| Bally **Medusa** (1981) | `board-simulated` | 27 | 3 |
| Bally **Mr. & Mrs. Pac-Man** (1982) | `board-simulated` | 26 | 3 |
| Bally **Mysterian** (prototype, 1982) | `board-simulated` | 36 | 1 |
| Bally **Spectrum** (1982) | `board-simulated` | 31 | 4 |
| Bally **Vector** (1982) | `board-simulated` | 50 | 4 |
| Bally **Big Bat** (1984) | `board-simulated` | 24 | 1 |
| Bally **Beat the Clock** (1985) | `board-simulated` | 62 | 2 |
| Bally **Eight Ball Champ** (1985) | `board-simulated` | 62 | 1 |

These 16 profiles cover 45 of the 49 Squawk & Talk game revisions known to
PinMAME. Many revisions share the same sound ROM set, so there are 19 distinct
sets rather than 49.

The remaining sets are unusual:

- **Rapid Fire** does not use the TMS speech path in the traced command set; it
  makes its sound through the DAC.
- **Cosmic Flash** needs a confirmed dump before a profile can be built.
- **Black Belt** (`blackbl2`) has no hash-identified sound dump available to the
  project.

If you have a Cosmic Flash or Black Belt dump, see
[contributing profiles](docs/CONTRIBUTING_PROFILES.md). Do not post ROM data in
an issue or pull request.

Run this to see the profiles in your copy:

```
python understudy.py profiles
```

## When Understudy refuses a set

That is usually useful information, not something to work around. `convert-set`
stops if the dumps do not exactly match a known profile, a phrase layout is
inconsistent, speech runs outside the expected device, changed bytes do not
reconcile, or an output would overwrite an input.

It also rejects an already converted set because its hashes no longer match the
original profile. The manual `convert` command cannot provide that protection,
so keep your original dumps.

For detailed failure cases and the checks behind them, see
[VALIDATION.md](docs/VALIDATION.md) and
[KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Bench notes worth knowing

- **2532 and 2732 are not pin-compatible.** A Squawk & Talk socket may accept
  either depending on its jumpers. Select the device type actually fitted when
  reading and burning.
- **Read each original twice and compare the files** before converting it.
- A **2 KB device can be mirrored in a 4 KB socket**. `convert-set` knows about
  this for supported profiles; manual ROM work needs to account for it.
- **Keep the originals.** Do not erase them after a successful conversion.

The [Squawk & Talk notes](docs/SQUAWK_AND_TALK.md) cover board layout, mirroring,
pointer tables, and the details behind these warnings.

## Pitch limitation

A TMS5220 cannot reproduce the lowest TMS5200 pitches. At an 8 kHz sample rate,
the practical floor is about 50.3 Hz instead of 37.9 Hz. Frames below the
TMS5220 floor are raised, and `convert-set` reports how many were affected.

Embryon has 17 affected frames out of 850 (2.0%). They were not noticed in the
first real-board listening test. [PITCH_CEILING.md](docs/PITCH_CEILING.md)
contains the analysis and experiments.

## Research and unsupported games

The normal repair path is `convert-set`. The lower-level `inspect` and `convert`
commands exist for research and for building a new profile. They require you to
supply the ROM layout yourself, which means they can convert the wrong bytes if
the layout is wrong.

A typical research run looks like this:

```
python understudy.py inspect speech.bin --table-offset 0xNNNN --phrases N \
    --base-address 0xC000 --command-ordered

python understudy.py convert speech.bin -o speech-5220.bin \
    --table-offset 0xNNNN --phrases N --base-address 0xC000 \
    --command-ordered --dry-run
```

The numbers above are placeholders. Do not copy them into a real conversion.
[SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) explains how to establish a layout,
and [CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) explains how to
turn one into a safe `convert-set` profile.

## How the conversion works

The TMS5200 and TMS5220 use the same speech frame grammar and field widths, but
the index tables behind those fields differ. Understudy parses each TMS5200
frame and maps its parameters to the nearest entries in the target chip's tables.
Because the field widths do not change, the converted stream is the same length
as the original and can be patched back into the same ROM locations.

Each conversion is re-parsed afterward and its frame types are compared with the
source. The set workflow adds profile, device, coverage, and changed-byte checks.
See [VALIDATION.md](docs/VALIDATION.md) for why those checks exist.

### As a library

```python
from tms52xx import convert_stream
from tms52xx.chips import resolve

src = resolve("tms5200").tables()
dst = resolve("tsp5220c").tables()

converted, report, stopped = convert_stream(
    open("speech.bin", "rb").read(), src, dst
)
```

## Documentation

| document | what it is for |
|---|---|
| [REPAIR_WALKTHROUGH.md](docs/REPAIR_WALKTHROUGH.md) | first conversion, step by step |
| [CHIPS.md](docs/CHIPS.md) | replacement parts and what is actually known about them |
| [VALIDATION.md](docs/VALIDATION.md) | test coverage, profile evidence, and earlier failures |
| [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | known technical limitations |
| [SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) | board and ROM research notes |
| [PROVENANCE.md](docs/PROVENANCE.md) | coefficient-table format and sources |
| [PITCH_CEILING.md](docs/PITCH_CEILING.md) | the low-pitch limitation and experiments |
| [PRIOR_ART.md](docs/PRIOR_ART.md) | related projects and prior work |
| [HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) | reporting a real-board test |
| [CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) | adding support for a game |
| [CONTRIBUTING.md](CONTRIBUTING.md) | working on the project |

## Tests

```
PYTHONPATH=src python -m unittest discover -s tests
python tools/check_docs.py
```

The code uses the Python standard library only. Tests need no network access or
ROM data.

## Licence

Understudy's code and documentation are **Zero-Clause BSD**.

The bundled coefficient tables come from MAME and are BSD-3-Clause. Their notice
and exact provenance are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
No ROM images are included or distributed.
