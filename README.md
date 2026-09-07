# understudy

**Your Bally Squawk & Talk has a dead TMS5200 and you cannot get another one.**
This converts the speech data in its ROMs into the coefficient tables a
TMS5220, TMS5220C or TSP5220C uses, so the data means the same thing to the
replacement part that it meant to the original.

What that does *not* do is establish that any of those parts drops into your
board electrically. Nobody has yet run a converted ROM on real hardware — see
[Silicon validation](#silicon-validation) — and pinout, supply and clock are
yours to check against the datasheet.

An open-source preservation project from
[Flashback Fleet LLC](https://github.com/flippin-balls), who run these machines
on location and would rather they kept talking.

> **Status: pre-1.0.** The reference Embryon conversion was checked against
> real ROM data and rendered through an emulator during development. Each
> conversion you run is **structurally checked** — the output is re-parsed and
> every frame's kind compared — but no emulator runs, and
> **no converted ROM from this tool has ever been played on a real Squawk &
> Talk board.** Until that happens this is a research preview: see
> [Silicon validation](#silicon-validation).

---

# I'm fixing a board

## What you need

- your machine's sound ROMs, read out of their sockets (one file per device);
- a blank EPROM of the same type for each device that holds speech;
- a replacement chip. All three targets produce identical converted bytes,
  because their LPC tables are identical; the TSP5220C is usually the easiest
  to find. Electrical substitution is **not** something this project has
  verified — see [docs/CHIPS.md](docs/CHIPS.md);
- Python 3.9 or newer.

You do **not** need MAME, PinMAME, coefficient tables, or any knowledge of how
the speech data is laid out. Those are bundled or worked out for you.

## Install

```
pip install understudy
```

or run it straight from a clone with `PYTHONPATH=src python -m tms52xx.cli`.

## Two commands

```
understudy identify 841-01_4.716 841-02_5.532
```

```
understudy convert-set 841-01_4.716 841-02_5.532 --target tsp5220c -o out/
```

That is the whole job. `identify` tells you which game and revision you have.
`convert-set` assembles the CPU's view of the sockets, converts every phrase,
splits the result back into device-sized files, and tells you which chip to burn
each one into.

Your original dumps are never modified, and `convert-set` refuses to write over
them even if you ask it to.

## What it prints before you burn anything

```
====================================================================
  CHECK THIS BEFORE YOU BURN ANYTHING
====================================================================
profile      Bally Embryon (1981)  (embryon v1, status emulator-verified)
chips        tms5200  ->  tsp5220c
tables       source b52952638192 / target f15418abad1b  (bundled)

input dumps
  U4   2716       2048 bytes  sha256 8495958b46c73f98840adff7
  U5   2532       4096 bytes  sha256 f24559ad001b4cbb1ef4442a

conversion
  phrases                21
  frames                 871
  frame kinds preserved  871 of 871
  clamped to pitch floor 17 (2.0%)
  f0 error, unclamped    median 1.07 Hz, max 3.40 Hz
  bytes changed          3520

output devices
  U4   2716       2048 bytes  1560 changed  (taken from the mirror half)
       burn into 2716: out/841-01_4_U4_2716_tsp5220c.716
  U5   2532       4096 bytes  1960 changed
       burn into 2532: out/841-02_5_U5_2532_tsp5220c.532

  reconciliation         3520 changed across devices == 3520 in the image

warnings
  - 17 frame(s) (2.0%) sit below the tsp5220c pitch floor and were raised
  - profile status is 'emulator-verified': no converted ROM from this profile
    has been played on a real board
====================================================================
```

Read the reconciliation line. It is the arithmetic check that the bytes changed
in the image are exactly the bytes changed in the files you are about to burn.

Output filenames carry the socket **and the device type**, because those are the
two things you need at the programmer.

Nothing is written until every destination has been checked, and then the files
are written as a set: each is staged and flushed to disk before any of them is
renamed into place, and if a rename fails the ones already done are rolled back.
So an ordinary failure — a full disk, a permission change, a drive pulled —
leaves the directory as it was rather than a mixture of new and stale images.
A power loss during the renames is not covered by that; if the machine dies
mid-run, check the hashes in the manifest against the files before burning.

## Supported games

| game | status | notes |
|---|---|---|
| Bally **Embryon** (1981) | `emulator-verified` | 21 phrases, U4 (2716) + U5 (2532) |

`understudy profiles` lists what your copy has. A game not in that list is not
unsupported — it just has no profile yet, so it needs the
[manual path](#i-want-to-understand-or-extend-the-research). If you work one
out, please [contribute it](docs/CONTRIBUTING_PROFILES.md); it needs no ROM
data.

## What it will refuse to do

Understudy stops rather than write a ROM that might be wrong. It refuses when:

- **your dumps do not match a profile exactly.** Identification is by SHA-256:
  every speech-bearing device must match for a set to be recognised, and every
  device the profile emits must be hashed before it will convert at all. A
  near-miss is a different revision or a bad read, and either way this layout is
  not the right one for it;
- **more than one profile matches**, or none does;
- **a phrase does not end in a stop frame** — the usual sign that the layout is
  aimed at something that is not speech;
- **a socket the profile says holds speech did not change**, or one it says
  holds none did;
- **the changed-byte totals do not reconcile** between the image and the
  devices;
- **the output path is one of your input dumps.**

It also catches **double conversion**. A converted ROM carries no marker saying
so — there is nowhere in a TMS52xx stream to put one — but it no longer matches
the profile's hashes, so `convert-set` refuses it whether you let it identify
the set or force `--game`. The manual `convert` path has no such protection, so
keep your originals.

## Things that will bite you at the bench

- **2532 and 2732 are not pin-compatible**, and a Squawk & Talk socket takes
  either by jumper. Read and burn as the type actually fitted, or you will get a
  file of the right size and the wrong contents.
- **A 2 KB device in a 4 KB socket is mirrored**, and on Embryon the firmware
  reads its speech through the *mirror*. `convert-set` handles this; if you do
  it by hand, taking the lower half gives you an unconverted ROM that burns
  fine.
- **Read each device twice and compare** before converting anything.
- **Keep the originals.** Converting an already-converted ROM moves every index
  a second time, and nothing in the file marks it as converted.

[docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) covers all of this properly,
including where to get ROMs for a machine you own.

## The one thing it cannot fix

A TMS5220 cannot go as low as a TMS5200: 50.3 Hz against 37.9 Hz. Frames below
that floor are raised and will sound higher than the original. On Embryon that
is 2.0% of frames. [docs/PITCH_CEILING.md](docs/PITCH_CEILING.md) explains why,
and what was tried.

## Silicon validation

**None yet.** No physical TMS5200, TMS5220 or TSP5220C has been fitted or
measured for this project, and no converted ROM has been played on a board.

Be precise about what has been done, because the three are different things:

| | |
|---|---|
| every conversion you run | re-parsed and checked frame by frame — **structural only** |
| the Embryon reference conversion | additionally rendered through PinMAME during development |
| any conversion, on hardware | **never** |

If you fit a converted set to a real board, please tell us how it went:
[docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) is a template for
recording it, and it is the single most useful thing anyone can contribute.

---

# I want to understand or extend the research

## How the conversion works

The TMS5200 and TMS5220 share the frame grammar and **every field width**; only
the coefficient tables behind the indexes differ. So a TMS5200 stream played on
a TMS5220 parses perfectly and sounds wrong. Re-indexing the parameters into the
substitute's tables is therefore length-preserving, which is what makes patching
a ROM in place possible: no pointer table, phrase boundary or timing changes.

Each parameter maps to the nearest entry in the destination table. That is not
optimal — the reflection coefficients interact — but it is the mapping the frame
grammar guarantees is safe to patch in place, and it is auditable frame by frame
from the manifest.

## The manual path

For a revision no profile covers:

```
understudy inspect speech.bin --table-offset 0x3C1C --phrases 21 \
    --base-address 0xC000 --no-end-bound --command-ordered

understudy convert speech.bin -o speech-5220.bin \
    --table-offset 0x3C1C --phrases 21 --base-address 0xC000 \
    --no-end-bound --command-ordered --dry-run
```

These take a single assembled image rather than socket dumps, and default to the
bundled tables. [docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) has a
five-step procedure for finding a layout, with a worked example.

## As a library

```python
from tms52xx import ChipTables, convert_stream
from tms52xx.chips import resolve

src = resolve("tms5200").tables()
dst = resolve("tsp5220c").tables()

converted, report, stopped = convert_stream(open("speech.bin", "rb").read(),
                                            src, dst)
clamped = [r for r in report if r.pitch_clamped]
print(f"{len(clamped)} of {len(report)} frames could not keep their pitch")
```

`patch_rom` fails closed on an unterminated phrase unless you pass
`allow_unterminated=True`, so a library caller gets the same protection as a
command-line one.

## Where the numbers come from

Conversion of the real Embryon set — assembled from an original ROM set, no ROM
data from which appears in this repository:

| | |
|---|---|
| phrases / frames | 21 / 871 |
| frame kinds preserved | 871 of 871 |
| frames at the TMS5220 pitch floor | 17 (2.0%) |
| f0 error on the rest | median 1.07 Hz, max 3.40 Hz |
| bytes changed outside the phrase extents | 0 |

Every figure is printed by the tool and recorded in its manifest, so the same
table can be produced from any ROM. The manifest from that run is checked in at
[examples/embryon.manifest.json](examples/embryon.manifest.json); it holds
offsets, counts and hashes only.

## Documentation

| | |
|---|---|
| [docs/CHIPS.md](docs/CHIPS.md) | which parts substitute for which, and the limits of that claim |
| [docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md) | the board, finding a layout, ROM sourcing, device handling |
| [docs/PITCH_CEILING.md](docs/PITCH_CEILING.md) | the one unfixable limitation |
| [docs/PROVENANCE.md](docs/PROVENANCE.md) | the coefficient tables: format, sources, and what is in each |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | everything else we know is imperfect |
| [docs/PRIOR_ART.md](docs/PRIOR_ART.md) | the projects this builds on and sits beside |
| [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) | how to report a real-board test |
| [docs/CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) | adding a game, without sending ROM data |
| [CONTRIBUTING.md](CONTRIBUTING.md) | working on the code |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | the bundled tables' licence and provenance |

## Tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

Standard library only, no fixtures, no network, no ROM data.

## Licence

Understudy's code and documentation are **Zero-Clause BSD** — use them for
anything, no attribution required.

The **bundled coefficient tables are not ours**: they are BSD-3-Clause, from
MAME, and that licence requires its notice to travel with them. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

No ROM images are included or distributed.
