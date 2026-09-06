# understudy

Convert TMS5200 LPC speech data so it plays correctly on a TMS5220.

The TMS5200 has been out of production for decades. Machines that shipped with
one still need to talk, and the TMS5220 — a later part from the same family — is
what this project targets as a substitute.

The two are close enough to be tempting and different enough to be wrong. They
share the frame grammar and every field width, so a TMS5200 stream fed to a
TMS5220 parses perfectly — and then sounds wrong, because the coefficient tables
behind the indexes are not the same. Nothing errors; the speech is just off.

This library re-indexes the data into the substitute chip's tables. Because no
field changes width, a converted stream is **exactly as long as the original**,
so a speech ROM can be patched in place with no pointer table, phrase boundary
or timing changed.


## The constraint worth knowing before you start

The two chips do not cover the same pitch range. The TMS5220's excitation
period table stops shorter than the TMS5200's, so the lowest-pitched frames in a
TMS5200 stream have no destination to map to and must be clamped upward.

Reading PinMAME's `src/sound/tms5220r.c`, the longest period a TMS5220 can be
driven to is 159 samples against the TMS5200's 211 — about 50.3 Hz against
37.9 Hz at the 8 kHz sample rate. Nine candidate workarounds were built and
rendered; none moved the fundamental below the table's floor.

So conversion preserves the frame structure and timing exactly, maps each
coefficient to the nearest entry in the substitute chip's tables, and raises the
pitch of frames below that chip's floor. `FrameConversion` reports
`pitch_clamped` per frame, so you can see where and how often rather than
discovering it by ear.

**Nothing here has been confirmed on silicon.** The ceiling follows from the
coefficient table and the counter comparison, both documented chip behaviour, so
it should transfer — but that is an expectation, not a measurement, and it is
the only caveat of its kind stated in this file.
[docs/PITCH_CEILING.md](docs/PITCH_CEILING.md) has the detail and
[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) the rest.

## Installing

Pure Python, standard library only, no dependencies. Python 3.9 or newer.

```
git clone https://github.com/flippin-balls/understudy
cd understudy
PYTHONPATH=src python -m unittest discover -s tests    # all offline, no fixtures
```

Either install it, which gives you an `understudy` command:

```
pip install .
understudy --help
```

or run it in place without installing anything:

```
PYTHONPATH=src python -m tms52xx.cli --help
```

The examples below use the second form. If you installed it, replace
`python -m tms52xx.cli` with `understudy`.

## Converting a ROM

You need the ROM you already own, chip tables you have supplied
([docs/PROVENANCE.md](docs/PROVENANCE.md)), and the phrase layout for your title
([docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md)).

```
python -m tms52xx.cli inspect speech.bin --table-offset 0x40 --phrases 20 \
    --source-tables tables/tms5200.json

python -m tms52xx.cli convert speech.bin -o speech-5220.bin \
    --source-tables tables/tms5200.json \
    --target-tables tables/tms5220.json \
    --table-offset 0x40 --phrases 20 --dry-run
```

`inspect` writes nothing. With `--source-tables` it also parses each phrase and
reports whether its final ROM byte is `required` or `spare`, which is what
decides whether `--truncate-last-byte` is safe for that phrase — the convention
is per stream, so the flag takes phrase indexes.

The dry run reports how many frames had to be pitch-clamped before anything is
written. Drop `--dry-run` to produce the file.

**Convert the original, once.** The input must be the unmodified TMS5200 image.
Running the same conversion on a ROM that has already been converted re-reads
its indexes as though they were TMS5200 indexes and moves them a second time —
the file stays valid, the same length, and structurally correct, and the speech
degrades. Nothing detects this for you: a converted ROM carries no marker, and
the tool cannot tell one from an original. Keep the original, and use the
manifest's `input.sha256` to confirm what you are feeding it.

**What it refuses to do.** The input ROM is never modified, and `--force` will
not write over it even if you name it as the output — it only permits replacing
an existing output file. A phrase that does not end in a stop frame stops the
conversion outright rather than warning, because the usual cause is a wrong
layout aimed at code or data, and the result would be a plausible-looking file
that is silently wrong (`--allow-unterminated` if you are sure). A frame whose
fields run past the end of its phrase is left exactly as found rather than
half-rewritten. Before writing, the tool re-reads its own output and refuses to
emit the file if anything outside the declared phrase extents changed.

Output and manifest are each written through a temporary file and renamed, so an
interrupted run cannot leave a half-written ROM in place of a good one. The two
renames are not a single transaction: the manifest is committed first, so an
interruption between them leaves a manifest describing a ROM that was not
written. Compare the manifest's `output.sha256` against the file before
trusting a pair you did not watch complete.

The manifest records the hashes of the input, the output and both table files,
the layout you declared, the per-phrase results and the exact byte ranges that
changed.

## Has it been run on a real ROM?

Yes, though not yet on real silicon. The tool was run end to end against a
Squawk & Talk speech image assembled from an original Bally *Embryon* ROM set
(a 2716 in U4, a 2532 in U5, mapped at `$E000` and `$F000`). No ROM data from
that set appears in this repository.

All 21 phrases parsed and every one ended in a stop frame. That is a necessary
consistency check rather than proof: a 4-bit `0xF` can occur by chance in
arbitrary data, so clean termination across every phrase is evidence the layout
is right, not a demonstration of it. Converting them:

| | |
|---|---|
| frames converted | 871 |
| frame kinds preserved (voiced/unvoiced/silence/stop) | 871 of 871 |
| frames at the TMS5220 pitch floor | 17 (2.0%) |
| f0 error on the rest | median 1.07 Hz, max 3.40 Hz |
| bytes changed outside the phrase extents | 0 |
| pointer table modified | no |

Every one of those numbers is printed by `convert` itself and recorded in the
manifest it writes, so the same table can be produced from any ROM — including
yours. The manifest from that run is checked in as
[examples/embryon.manifest.json](examples/embryon.manifest.json): 21 phrases,
899 changed byte ranges, and the input's SHA-256, so you can confirm you have
the same image before comparing. It records offsets, counts and hashes only.

What you cannot do without that ROM set is reproduce this particular row. The
ROM is not included and is not ours to distribute.

The f0 figures are the difference between the source period decoded on a
TMS5200 and the converted period decoded on a TMS5220 — that is, what the
substitute part will actually excite at. The 17 clamped frames are the pitch
floor described above and are the one thing conversion cannot fix.

What this does **not** show is how it sounds on a real TMS5220 in a real
machine. That measurement has not been made.

## As a library

```python
from tms52xx import ChipTables, convert_stream

src = ChipTables.from_json("tables/tms5200.json")
dst = ChipTables.from_json("tables/tms5220.json")

converted, report, stopped = convert_stream(open("speech.bin", "rb").read(), src, dst)

clamped = [r for r in report if r.pitch_clamped]
print(f"{len(clamped)} of {len(report)} frames could not keep their pitch")
```

`parse` and `rebuild` are available separately if you only want to read a stream.
Rebuilding an untouched parse reproduces the input byte for byte, which is what
makes the bit map testable rather than merely plausible.

## Chip tables are not included

You supply them. Every convenient machine-readable copy we located traces back
to an emulator source tree, and PinMAME is mid-migration from the old MAME
licence to 3-Clause BSD on a per-file basis; bundling a generated copy would
push that ambiguity onto everyone downstream to save them one command.
[docs/PROVENANCE.md](docs/PROVENANCE.md) sets out the position, its limits, and
an extractor.

The test suite ships synthetic tables, so it runs with nothing supplied.

## Scope

One board, two chips: Bally Squawk & Talk, TMS5200 to TMS5220.

It does not analyse audio into LPC. That is a different and harder problem and
several good tools already solve it — see [docs/PRIOR_ART.md](docs/PRIOR_ART.md),
and start there if you have a recording rather than a ROM.

It does not handle the TMS5100, TMS5110 or TMS5220C. It does not discover the
phrase layout for you. It does not update ROM checksums. It runs no emulator:
each converted phrase is re-parsed with the target tables and checked frame by
frame, which is a structural check and not an acoustic one. [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) is the full
list.

## Licence

Zero-Clause BSD. Use it for anything, no attribution required. A link back is
welcome and not expected.

---

Built by [Flashback Fleet LLC](https://github.com/flippin-balls).
