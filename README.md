# understudy

**A replacement TMS5220 can speak the ROM data from a Bally Squawk & Talk, but
not correctly. Understudy fixes the ROM data.**

It converts TMS5200 speech parameters to the coefficient tables used by the
TMS5220, TMS5220C and TSP5220C while keeping the ROM layout and phrase timing
intact. The result is a set of files you can burn into replacement EPROMs.

Understudy is an open-source preservation project from
[Flashback Fleet LLC](https://flashbackfleet.com), who run these machines
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

## What the chips actually differ by, and why the result sounds right

### The chip does not store the voice

A TMS5200 contains no recordings. It is a small electronic model of a human
vocal tract — a buzz or a hiss for the sound a voice makes, and an adjustable
filter that shapes that sound into vowels and consonants the way a mouth and
throat do. The chip cannot say anything on its own. The ROM tells it what shape
to be, twenty-five times a second.

Each of those updates is called a **frame**. A frame is not a piece of audio. It
is a short list of settings, roughly: how loud, whether this is a buzz or a hiss,
how low or high the buzz is, and ten numbers describing the shape of the filter.
Play the frames in order and the chip talks.

### The ROM stores lookup numbers, not the settings themselves

Here is the part everything else follows from. A frame does not contain the
actual filter settings. There is not enough room. Instead it contains a **lookup
number** for each setting — a position in a table that is built into the chip
itself.

An analogy: the ROM does not say "paint it sky blue". It says "use colour 14",
and the chip has a paint chart with colour 14 on it. The ROM is a list of chart
positions. The chart lives in the chip.

Each setting has its own chart, and they are small:

| setting in a frame | positions on its chart |
|---|---|
| how loud (**energy**) | 16 |
| how low or high the buzz is (**pitch**) | 64 |
| filter shape, first number | 32 |
| filter shape, second number | 32 |
| filter shape, numbers 3–7 | 16 each |
| filter shape, numbers 8–10 | 8 each |

Those ten filter numbers have a proper name, **reflection coefficients**, and
together they are what makes an "ee" sound different from an "oh".

### What is different between the chips

**The frames are laid out identically.** A TMS5200 frame and a TMS5220 frame have
the same fields, in the same order, using the same number of bits each. Feed a
TMS5200's speech to a TMS5220 and it reads it perfectly happily. Nothing jams,
nothing desynchronises, the phrases start and stop in the right places.

**The charts inside are different.** Same number of positions, different values
at those positions. Position 14 is simply a different colour on the two chips.
Measured against the actual tables this project ships:

- **Loudness: identical.** All 16 positions match exactly on both chips.
- **Filter shape: almost entirely different.** Of the 32 positions on the first
  filter chart, 30 hold different values. On several of the smaller charts,
  *every* position differs.
- **Pitch: 62 of 64 positions differ**, and the range is different too — more on
  that below.

So a TMS5200 ROM played through a TMS5220 is a set of perfectly valid
instructions being carried out against the wrong chart. The result is
intelligible-ish, wrong-sounding speech: recognisably the same rhythm and the
same phrases, with the voice mangled. That is the fault this tool fixes.

### The other chips

**TMS5220, TMS5220C and TSP5220C all have the same charts as each other.** They
were physically examined — the silicon decapped and read — and the tables are
identical. So a conversion aimed at any one of them produces *byte-for-byte the
same file*, and it does not matter which of the three you can find. They differ
in control details that have nothing to do with the speech data: the C versions
understand one extra command that the plain TMS5220 ignores.

The TMS5200 also appears under the names **CD2501E** and **TMC0285**. Those are
the same part with a different label, and this tool treats them as the original
to convert *from*.

### How the fix works

If the ROM says "colour 14" and the two chips disagree about colour 14, the
answer is to look up what colour 14 *actually was* on the original chip, then
find the position on the new chip's chart that is closest to that same real
colour, and write that position number into the ROM instead.

That is the whole conversion. For every setting in every frame, replace the
lookup number with the one that means the same thing on the replacement chip.

The critical property is that a **position number is the same size as any other
position number**. Changing "14" to "11" does not make the frame longer. So the
converted ROM is exactly the same length as the original, every phrase still
begins and ends at the same address, and the table of phrase addresses elsewhere
in the ROM stays correct without being touched. The ROM is edited in place, and
nothing about its structure moves.

### Why it comes out sounding right

Three reasons, in order of how much they matter.

**The charts are dense enough that "closest" is very close.** The replacement's
chart has as many positions as the original's, covering the same kind of range.
When the tool looks for the nearest value it is not settling for something
roughly similar — on the largest filter chart, the worst case across every
position is off by under **4% of the chart's full span**, and most are far
closer than that. The ear does not hear a difference that small in a filter
setting.

**Loudness needs no conversion at all.** Those tables are identical, so the
volume shape of every word is carried across untouched. Loudness is a large part
of what makes speech sound natural, and none of it is approximated.

**Nothing about the timing or structure changes.** Frames stay the same length,
in the same order, of the same type — a buzzed frame stays buzzed, a hissed
frame stays hissed, a silence stays silence. On the reference conversion all
**850 frames kept their type**, verified by re-reading the finished file. Speech
that is slightly off in filter shape still sounds like speech; speech with the
timing disturbed does not.

The measured result on that conversion: the pitch of the converted frames lands
a **median of about 1 Hz** away from the original, with the worst frame about
3.4 Hz out. For comparison, the difference between two people saying the same
word is tens of hertz.

### The one part that cannot be fixed

The two chips disagree about how *low* a voice can go, and this is a real limit
rather than a shortcoming of the method.

The lowest note a TMS5200 can produce is about **38 Hz**. The lowest a TMS5220
can produce is about **50 Hz**. The 5220's chart simply does not go down that
far — there is no position on it meaning "38 Hz", so there is nothing to point
at. Any frame written below roughly 50 Hz has to be raised to the lowest note
the replacement can actually make.

This is not something a cleverer conversion could route around. The limit is in
the destination chip's chart, not in how the numbers are chosen. Nine different
workarounds were built as real speech data and measured, including several
attempts to fake a lower note by alternating between two higher ones; all nine
failed.

In practice it is a small effect. On the reference conversion **17 frames out of
850 — two percent** — sat below the floor and were raised. Those frames are in
five of the twenty phrases, and the prediction was that they would sound
noticeably higher-pitched. When the conversion was finally played on a real
machine, the person listening did not pick them out.


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
