# understudy

**A replacement TMS5220 can speak the ROM data from a Bally Squawk & Talk, but
not correctly. Understudy fixes the ROM data.**

It converts TMS5200 speech parameters to the coefficient tables used by the
TMS5220, TMS5220C and TSP5220C while keeping the ROM layout and phrase timing
intact. The result is a set of files you can burn into replacement EPROMs.

Understudy is an open-source preservation project from
[Flashback Fleet LLC](https://flashbackfleet.com), who run these machines
on location and would rather they kept talking.

**Hear it first.** [examples/audio/](examples/audio/) has short clips of ten
phrases, each in three versions: the original chip, a TMS5220 fed the
unconverted ROM, and a TMS5220 fed the converted one. The middle one is what a
straight chip swap sounds like.

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

## Optional: `--optimize-audio`

The default conversion picks, for each coefficient, the nearest value the
replacement chip offers. But the ten coefficients per frame are one filter, not
ten separate settings, and rounding each on its own is not always where the
filter as a whole lands closest.

`--optimize-audio` applies per-frame corrections that were measured for that
game by rendering the alternatives and comparing them against the original chip.
In that experiment, **39 of 40 representative Embryon frames improved** and one
was already the best choice.

```
python understudy.py convert-set . --optimize-audio
```

Read that as a measurement, not a promise:

- it was measured on one game's frames — yours may gain less, or nothing;
- **no optimised ROM has been played on real hardware by anyone yet**;
- it does **not** help the pitch limitation below, and does not try to;
- it exists only for games it has been measured on, and says so if yours is not
  one.

The default remains the plain nearest-value conversion, and the manifest records
which mode produced your ROM either way.
[AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md) has the method, the controls
and the checks.

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

### Two mistakes the conversion refuses to make

Picking the nearest value is right for a filter setting, where every position on
the chart means "this much of this thing". It is wrong in two places, because
some positions are not measurements at all — they are instructions.

**Loudness position 0 means silence, and position 15 means stop.** Neither is a
volume. "Stop" is how a phrase ends: the chip sees it and stops talking. If a
quiet frame were converted by picking the numerically nearest position and that
turned out to be 15, the phrase would end there — and every word after it in
that phrase would simply never be spoken. Not quieter. Gone.

**Pitch position 0 means "this frame is a hiss, not a buzz".** It is not a low
note; it is a different kind of sound, the one used for `s` and `f` and `sh`. A
buzzed frame that converted into it would turn part of a vowel into noise.

So those three positions are excluded from the search. The conversion will take
a slightly worse number over a number that changes what the frame *is*. On the
real tables the excluded positions never happen to be the closest match anyway —
but the rule is enforced rather than assumed, because someone can supply their
own tables, and the failure it prevents is silent and total rather than subtle.

There is a third, smaller rule: when two positions are equally close, the lower
one always wins. That choice is arbitrary, but fixing it means converting the
same ROM twice gives the same file, so two conversions can be compared.

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

### What is checked every single time, on your own ROM

The measurements above were done once, during development. These run on every
conversion you do, on your files, and the tool refuses to write anything if one
of them fails.

**The converted file is read back and re-interpreted from scratch**, as if the
tool had never seen it — then every frame is compared with the original. Not the
settings, which are supposed to have changed, but the *kind* of each frame: a
buzz must still be a buzz, a hiss still a hiss, a silence still a silence, and
the frame that ends a phrase must still end it. This is the check that would
catch a conversion which quietly turned speech into a stop and truncated a
phrase. On the reference conversion it reports `850 of 850`.

**The length must be identical.** If the output is even one byte longer or
shorter than the input, something has gone badly wrong in a way that would move
every phrase after it, and nothing is written.

**Every changed byte must lie inside a phrase.** The tool knows where the
phrases are, and compares the whole file before and after. If a single byte
changed anywhere else — in the program the sound board runs, in the table of
phrase addresses, in unused space — it refuses.

Be clear about what that does and does not cover, because it is the difference
between two real incidents in this project. It catches a conversion that strays
outside the phrases **as the tool understands them**. It cannot catch the
description of where the phrases are being *wrong in the first place*: if a
game's description claims a phrase exists where the board's own program actually
lives, then rewriting that program is, as far as this check can tell, working on
a phrase. That is exactly what happened twice — one game's description read past
the end of its phrase table into program code and rewrote 31 bytes of it, and
another treated the table's end marker as a 21st phrase. Every check listed here
passed both of them.

What caught those was not a check on the file. It was loading the converted ROMs
into a simulation of the sound board and letting the board's own program run
against them. The second one stopped the simulated board booting at all. The
first still booted, because the commands that machine sends never reach the code
that had been damaged — which is why the game descriptions this tool ships are
also driven through every command the board can be sent, rather than merely
started.

**The arithmetic has to reconcile.** The number of bytes changed in the assembled
image must equal the number changed across the individual chips it gets split
back into. If those disagree, a change landed somewhere that is not on any chip,
and the run stops.

None of this listens to the audio — no computer here can tell you whether the
speech sounds right. What it can tell you is that nothing outside the speech was
touched, that the structure survived, and exactly which frames were approximated
and by how much. The listening is still yours to do.

### The one part that cannot be fixed

The two chips disagree about how *low* a voice can go, and this is a real limit
rather than a shortcoming of the method.

The lowest note a TMS5200 can produce is about **38 Hz**. The lowest a TMS5220
can produce is about **50 Hz**. The 5220's chart simply does not go down that
far — there is no position on it meaning "38 Hz", so there is nothing to point
at. Any frame written below roughly 50 Hz has to be raised to the lowest note
the replacement can actually make.

**What the tool does here is deliberately unclever: it uses the lowest note the
replacement chip has, and writes down that it did.** Every raised frame is
recorded, with the note the original asked for and the note it actually got, so
you can see exactly how much of a given ROM is affected *before* you burn
anything rather than discovering it from a customer.

That restraint was not an assumption. Nine different ways of faking a lower note
were tried first, and this is what they were:

- set the note field to the lowest available and rely on the chip smoothing
  between one frame and the next to average out lower;
- alternate between two different notes so the ear hears the slower pattern
  rather than either note;
- use the chip's repeat-frame feature to stretch one buzz across several frames;
- vary the loudness rhythmically at the difference between the note you have and
  the note you want, so the beat itself suggests the missing pitch;
- alternate deliberately between buzz and hiss;
- shape the smoothing ramps across frame boundaries;
- and three different attempts to build a **subharmonic** — a note an octave or
  more below the one actually being produced, out of the harmonics of the notes
  that are available.

**None of them was argued about. Each was built as real speech data, played
through a faithful software model of the chip, and the result measured.** All
nine failed. The subharmonic attempts are the instructive ones: the overall
measurements *improved slightly*, which looks like progress, but the actual
fundamental — the pitch you hear as the voice's note — had not moved at all.
That is the signature of adding energy at roughly the right frequency without
changing the rate the chip is actually buzzing at. It sounded no lower. Had the
whole-signal numbers been trusted instead of the fundamental, one of these would
have shipped as an improvement while changing nothing.

So the limit is genuinely in the destination chip's chart rather than in how the
numbers are chosen, and no cleverness in this tool can move it. One honest
caveat: those nine measurements were made against a software model of the chip,
not against silicon. The *ceiling* itself does not depend on the model being
perfect — it is a statement about what the chip's chart contains — but the
finer comparisons between one workaround and another do.

In practice the effect is small. On the reference conversion **17 frames out of
850 — two percent** — sat below the floor and were raised. Those frames fall in
five of the twenty phrases. The prediction was that those five would sound
noticeably higher-pitched.

When the conversion was finally played on a real machine, through a real
TMS5220, against the original chip playing the same phrases on the same board,
the person listening did not pick them out. Their summary was that it sounded
"very close" to the original. That does not repeal the ceiling — those frames
really are higher, and a different ROM with more of them would be a different
story — but at two percent it turned out to be below the threshold of notice.


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
