# Prior art

Everything below predates this project. The list is here because knowing which
tool solves which problem saves more time than any single one of them.

## Encoders: audio in, LPC out

These take a recording and produce a TMS5220 bitstream. That is the harder and
more general problem, and it is **not** what this project does.

- **[QBoxPro](https://forums.atariage.com/topic/260857-introducing-bluewizard-qboxpro-replacement-speech-analysis-tms5220-tool/)**
  — a commercial Windows LPC analysis tool. Named here because the projects below
  describe themselves as replacements for it.
- **[BlueWizard](https://github.com/patrick99e99/BlueWizard)** (Patrick Kelly) —
  macOS, Objective-C. Describes itself as a QBoxPro replacement. Its
  `CodingTable.m` carries a TMS5220 table matching none of MAME's eight
  variants — 21 of its 64 pitch entries differ from the TMS5220's — which makes
  it the one genuinely separate transcription we found.
- **[python_wizard](https://github.com/ptwz/python_wizard)** (Peter Turczak) — a
  Python port of BlueWizard. Command-line and scriptable. Its `lpcplayer`
  package carries coefficient tables for both the TMS5200 and the TMS5220; see
  [PROVENANCE.md](PROVENANCE.md#where-else-these-tables-exist)
  for what is in them and where they came from.
- **[TMS Express](https://github.com/tornupnegatives/TMS-Express)** — LPC encoder
  targeting both real TMS5220 hardware and Arduino Talkie.
- **[speakie](https://github.com/raphlinus/speakie)** (Raph Levien) — decoder plus
  an encoder inspired by BlueWizard.

## Players and emulation

- **[Talkie](https://github.com/ArminJo/Talkie)** — Arduino playback of LPC
  bitstreams, originally by Peter Knight. The reason a great deal of TMS5220
  speech data exists in hobbyist projects at all. Its `src/TalkieLPC.h` carries
  a TMS5220 table identical to MAME's and cites MAME as its source, which is
  what makes that lineage traceable at all.
- **PinMAME / MAME TMS52xx** — an open implementation of the chip's behaviour: `src/sound/tms5220.c` holds the interpolation and excitation
  logic, `src/sound/tms5220r.c` the per-variant coefficient tables. The
  pitch-ceiling result in [PITCH_CEILING.md](PITCH_CEILING.md) was derived
  against it, and it is where `tools/extract_tables.py` reads the tables from.

## Where this project fits

All of the above either **produce** LPC from audio or **play** LPC that already
exists. This one re-indexes existing LPC data from one 52xx variant's tables
into another's. We did not find such a tool among the projects reviewed here;
that is not a claim of novelty, and if one exists we would rather link to it
than duplicate it — please open an issue.

That gap is narrow and it is the only thing here. If your TMS5200 has failed and
you have its speech ROM, you do not need to re-analyse anything: the parameters
are already correct, they are simply expressed in the wrong chip's tables. This
converts them, and tells you which frames the substitute part cannot reproduce.

If you have audio and no LPC, use one of the encoders above.

## Hardware and preservation references

- Texas Instruments, *TMS5220 Voice Synthesis Processor Data Manual* — the frame
  grammar, field widths and pin-level behaviour.
- **Stuart Conner's TI speech pages** —
  [stuartconner.me.uk](https://www.stuartconner.me.uk/), preservation work on TI
  speech hardware and the surviving development systems around it. The site is
  intermittently unavailable; if it 502s, try the
  [Wayback Machine copy](https://web.archive.org/web/2024/http://www.stuartconner.me.uk/).
- Gene Helms and Steve Petersen, "Portable speech development system creates
  linear predictive codes", *Electronics*, 8 September 1982 — contemporary
  description of how this speech data was originally produced.

## Acknowledgements

The PinMAME and MAME teams, whose reverse engineering of the TMS52xx family is
the foundation under all of the above, including this.
