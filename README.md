# understudy

Convert TMS5200 LPC speech data so it plays correctly on a TMS5220.

The TMS5200 has been out of production for decades. Machines that shipped with
one still need to talk, and the TMS5220 is the part you can still buy.

The two are close enough to be tempting and different enough to be wrong. They
share the frame grammar and every field width, so a TMS5200 stream fed to a
TMS5220 parses perfectly — and then sounds wrong, because the coefficient tables
behind the indexes are not the same. Nothing errors; the speech is just off.

This library re-indexes the data into the substitute chip's tables. Because no
field changes width, a converted stream is **exactly as long as the original**,
so a speech ROM can be patched in place with no pointer table, phrase boundary
or timing changed.

It is also explicit about the part of the job that cannot be done, which is the
more useful half of the answer.

## The constraint worth knowing before you start

The two chips do not cover the same pitch range. The TMS5220's excitation
period table stops shorter than the TMS5200's, so the lowest-pitched frames in a
TMS5200 stream have no destination to map to and must be clamped upward.

Working from the coefficient tables as implemented in PinMAME's `tms5220.c`,
the longest period a TMS5220 can be driven to is 159 samples against the
TMS5200's 211 — about 50.3 Hz against 37.9 Hz at the 8 kHz frame rate. Nine
candidate workarounds were each built as a real bitstream and rendered; none
moved the fundamental below the table's floor, which is the threshold they were
judged against.

**This is an emulator-derived result and has not been confirmed on silicon.**
It follows from the coefficient table and the counter comparison, both of which
are documented chip behaviour rather than emulator artefacts, so it should
transfer — but that is an expectation, not a measurement. Treat it accordingly.

Conversion therefore reproduces the timbre and the timing, and raises the pitch
of frames that sit below the substitute chip's floor. `FrameConversion` reports
`pitch_clamped` per frame so you can see exactly where and how often that
happened rather than discovering it by ear.

## Converting a ROM

You need the ROM you already own, chip tables you have supplied
([docs/PROVENANCE.md](docs/PROVENANCE.md)), and the phrase layout for your title
([docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md)).

```
understudy inspect speech.bin --table-offset 0x40 --phrases 20

understudy convert speech.bin -o speech-5220.bin \
    --source-tables tables/tms5200.json \
    --target-tables tables/tms5220.json \
    --table-offset 0x40 --phrases 20 --dry-run
```

The dry run reports how many frames had to be pitch-clamped before anything is
written. Drop `--dry-run` to produce the file; the input is never modified, an
existing output is not overwritten without `--force`, and a manifest is written
alongside recording the hashes, the layout you declared, the per-phrase results
and the exact byte ranges that changed.

Before writing, the tool re-checks its own output and refuses to emit a file if
anything outside the declared phrase extents changed.

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

You supply them. See [docs/PROVENANCE.md](docs/PROVENANCE.md), which explains
why and includes an extractor.

Briefly: the values are technical facts about the silicon, but every convenient
machine-readable copy traces back to an emulator source tree, and PinMAME — the
most complete of those — is mid-migration from the old MAME licence to 3-Clause
BSD on a per-file basis. Bundling a generated copy would push that ambiguity
onto everyone downstream to save them one command.

The test suite ships synthetic tables so it runs with nothing supplied.

## Scope

One board, two chips: Bally Squawk & Talk, TMS5200 to TMS5220.

It does not analyse audio into LPC. That is a different and harder problem and
several good tools already solve it — see [docs/PRIOR_ART.md](docs/PRIOR_ART.md),
and start there if you have a recording rather than a ROM.

It does not handle the TMS5100, TMS5110 or TMS5220C. It does not discover the
phrase layout for you. It does not update ROM checksums. Its outputs are
structurally valid and emulator-checked; no physical chip has been measured for
this project. [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) is the full
list and is maintained rather than decorative.

## Licence

Zero-Clause BSD. Use it for anything, no attribution required. A link back is
welcome and not expected.

---

Built by [Flashback Fleet LLC](https://github.com/flippin-balls), who operate
pinball machines on location and would rather the speech boards kept working.
