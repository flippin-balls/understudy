# understudy

**A replacement TMS5220 can speak the ROM data from a Bally Squawk & Talk, but
not correctly. Understudy fixes the ROM data.**

It converts TMS5200 speech parameters to the tables used by the TMS5220,
TMS5220C and TSP5220C without changing phrase timing or ROM layout. The result
is a set of files you can burn into replacement EPROMs.

Understudy is an open-source preservation project from
[Flashback Fleet LLC](https://flashbackfleet.com), who run these machines on
location and would rather they kept talking.

**Hear it first.** [examples/audio/](examples/audio/) has ten Embryon phrases in
three versions: the original TMS5200, a TMS5220 with unconverted ROMs, and a
TMS5220 with converted ROMs.

> **Pre-1.0:** Embryon is the only profile tested on real hardware. The other 16
> profiles have passed structural and board-simulation checks but have not been
> heard on a real board. See [VALIDATION.md](docs/VALIDATION.md).

## Fixing a board

If you have never used a command line, start with the
[step-by-step repair walkthrough](docs/REPAIR_WALKTHROUGH.md).

### What you need

- the sound ROMs from your machine, read as files;
- a blank EPROM of the right type for each speech device;
- a TMS5220, TMS5220C or TSP5220C;
- Python 3.9 or newer.

The three replacement parts use the same converted speech data. Electrical
compatibility is a separate question; see [CHIPS.md](docs/CHIPS.md).

No Python packages, MAME install, or coefficient-table setup is required for a
supported game.

### Get Understudy

Click the green **Code** button on GitHub, choose **Download ZIP**, and unzip it.
There is nothing to install. If you use git:

```text
git clone https://github.com/flippin-balls/understudy
cd understudy
```

On Windows:

```text
py understudy.py --version
```

On macOS or Linux, use `python3 understudy.py --version`. The examples below use
`python`; use whichever command works on your machine.

### Convert a ROM set

Point `convert-set` at a folder, zip file, or the individual dumps:

```text
python understudy.py convert-set my-roms/
python understudy.py convert-set embryon.zip
python understudy.py convert-set 841-01_4.716 841-02_5.532
```

Understudy identifies the set by hash, assigns each dump to its socket, defaults
to a TMS5220 target, and writes the result to `understudy-out/`. Extra files in
a folder or zip are ignored.

To identify a set without converting it:

```text
python understudy.py identify my-roms/
```

Your input dumps are never modified. Add `--dry-run` to run the checks without
writing output files.

### Before you burn anything

`convert-set` finishes with a report like this:

```text
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

The lines under **output devices** tell you the socket, the EPROM type to select
in your programmer, and the file to burn. Program the file as raw binary and
verify it afterward.

Keep the original EPROMs and the generated manifest. The manifest records the
input hashes, conversion settings, and output files without containing ROM data.

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
| Bally Midway **Midnight Marauders** (1984) | `board-simulated` | 20 | 1 |
| Bally **Big Bat** (1984) | `board-simulated` | 24 | 1 |
| Bally **Beat the Clock** (1985) | `board-simulated` | 62 | 2 |
| Bally **Eight Ball Champ** (1985) | `board-simulated` | 62 | 1 |

These 17 profiles cover 45 of the 49 Squawk & Talk **pinball** revisions known
to PinMAME, plus Midnight Marauders, a Bally Midway gun game that uses the same
AS-2518-61 sound board.

Midnight Marauders has the highest pitch-floor clamp rate in the library at
**7.5% of frames**, compared with 2.0% for Embryon. Its converted ROMs have
passed board simulation, but nobody has listened to them on real hardware yet.

The remaining sets are unusual:

- **Rapid Fire** does not use the TMS speech path in the traced command set; it
  makes its sound through the DAC.
- **Cosmic Flash** needs a confirmed dump before a profile can be built.
- **Black Belt** (`blackbl2`) has no hash-identified sound dump available to the
  project.

If you have a Cosmic Flash or Black Belt dump, see
[CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md). Do not post ROM data
in an issue or pull request.

Run this to list the profiles in your copy:

```text
python understudy.py profiles
```

## When Understudy refuses a set

`convert-set` stops rather than write a questionable ROM. Common reasons include
an unknown or mismatched dump, an invalid phrase layout, speech leaving the
expected device, changed-byte totals that do not reconcile, or an output path
that would overwrite an input.

It also rejects an already converted set because its hashes no longer match the
original profile. The manual `convert` command does not have that protection.

See [VALIDATION.md](docs/VALIDATION.md) and
[KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the checks and their limits.

## Bench notes

- **2532 and 2732 are not pin-compatible.** Select the device type actually
  fitted when reading and burning, and check the board jumpers.
- **Read each original twice and compare the files** before converting it.
- A **2 KB device can be mirrored in a 4 KB socket**. `convert-set` handles this
  for supported profiles; manual ROM work must account for it.
- **Keep the originals.** Do not erase them after a successful conversion.

The [Squawk & Talk notes](docs/SQUAWK_AND_TALK.md) cover board layout, mirroring,
pointer tables, and profile research.

## Optional audio optimization

The default converter maps each parameter to the nearest value available on the
replacement chip. `--optimize-audio` applies measured, per-frame K-coefficient
corrections on games for which optimization data has been generated.

```text
python understudy.py convert-set . --optimize-audio
```

Across the sixteen measured games the search examined 10,580 eligible voiced
frames and found a better-scoring local choice for 10,184 of them. Rendering the
finished phrases as wholes, 389 of 461 improved and 70 were worse.

Current limits:

- the optimizer is opt-in; the default conversion is unchanged;
- sixteen of the seventeen profiles have data; `bigbat` has none, and a profile
  without data refuses the flag rather than silently ignoring it;
- **the whole-phrase result varies a lot by game.** Embryon's worst phrase is
  0.67 dB worse; Elektra's is +12.13 dB, and seven other titles exceed 2 dB.
  Check the coverage table in
  [AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md) for your game before
  trusting it;
- no optimized ROM has yet been tested on real hardware;
- the optimizer changes K indexes only and does not address the pitch floor;
- the manifest records whether optimization was used and which measured data was
  applied.

The original 40-frame study improved 39 of 40 frames on the same scoring metric.
The full method, guards, and phrase-level results are in
[AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md).

## Pitch limitation

A TMS5220 cannot reproduce the lowest TMS5200 pitches. At an 8 kHz sample rate,
the lowest table value is about 50.3 Hz instead of 37.9 Hz. Frames below the
TMS5220 floor are raised, and `convert-set` reports how many were affected.

Embryon has 17 affected frames out of 850 (2.0%). They were not noticed in the
first real-board listening test. See [PITCH_CEILING.md](docs/PITCH_CEILING.md).

## How the conversion works

The TMS5200 and TMS5220 use the same speech-frame grammar and field widths, but
the lookup tables behind those fields differ. A TMS5200 stream therefore parses
correctly on a TMS5220 while selecting the wrong values.

Understudy reads each TMS5200 frame and re-indexes its parameters into the target
chip's tables. Because the field widths do not change, the converted stream has
the same length and can be patched back into the same ROM locations without
moving phrase pointers.

The default mapping is deterministic and nearest-value. The optional optimizer
changes only measured K indexes after that baseline conversion. In both modes,
the finished stream is re-parsed and checked before output is written.

See [CHIPS.md](docs/CHIPS.md) for the chip variants,
[PROVENANCE.md](docs/PROVENANCE.md) for the bundled tables, and
[VALIDATION.md](docs/VALIDATION.md) for the profile checks.

## Research and unsupported games

The normal repair path is `convert-set`. The lower-level `inspect` and `convert`
commands are for research and new profiles. They require you to supply the ROM
layout yourself.

```text
python understudy.py inspect speech.bin --table-offset 0xNNNN --phrases N \
    --base-address 0xC000 --command-ordered

python understudy.py convert speech.bin -o speech-5220.bin \
    --table-offset 0xNNNN --phrases N --base-address 0xC000 \
    --command-ordered --dry-run
```

The values above are placeholders. See
[SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) for the layout procedure and
[CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) for turning a verified
layout into a profile.

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
| [CHIPS.md](docs/CHIPS.md) | replacement parts and what is known about them |
| [AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md) | optional optimizer method and results |
| [VALIDATION.md](docs/VALIDATION.md) | profile evidence and earlier failure cases |
| [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | known technical limits |
| [SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) | board and ROM research notes |
| [PROVENANCE.md](docs/PROVENANCE.md) | coefficient-table sources and format |
| [PITCH_CEILING.md](docs/PITCH_CEILING.md) | low-pitch limitation and experiments |
| [PRIOR_ART.md](docs/PRIOR_ART.md) | related projects and prior work |
| [HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) | reporting a real-board test |
| [CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) | adding support for a game |
| [CONTRIBUTING.md](CONTRIBUTING.md) | working on the project |

## Tests

```text
PYTHONPATH=src python -m unittest discover -s tests
python tools/check_docs.py
```

The code uses the Python standard library only. Tests need no network access or
ROM data.

## Licence

Understudy's code and documentation are **Zero-Clause BSD**.

The bundled coefficient tables come from MAME and are BSD-3-Clause. Their notice
and provenance are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). No ROM
images are included or distributed.
