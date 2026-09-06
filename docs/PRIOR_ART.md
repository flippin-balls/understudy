# Prior art

This project sits in a small, well-worked field. Everything below predates it
and most of it is better at what it does. The list is here because knowing which
tool solves which problem saves more time than any of them individually.

## Encoders: audio in, LPC out

These take a recording and produce a TMS5220 bitstream. That is the harder and
more general problem, and it is **not** what this project does.

- **[QBoxPro](https://forums.atariage.com/topic/260857-introducing-bluewizard-qboxpro-replacement-speech-analysis-tms5220-tool/)**
  — the original commercial TI-era analysis tool. Windows, unsupported, and the
  reference everything since has been measured against.
- **[BlueWizard](https://github.com/patrick99e99/BlueWizard)** (Patrick Kelly) —
  macOS, Objective-C. Written explicitly as a QBoxPro replacement, and the
  ancestor of most of what follows.
- **[python_wizard](https://github.com/ptwz/python_wizard)** (Peter Turczak) — a
  Python port of BlueWizard. Command-line, scriptable, and the easiest starting
  point if you want to generate speech rather than convert it.
- **[TMS Express](https://github.com/tornupnegatives/TMS-Express)** — LPC encoder
  targeting both real TMS5220 hardware and Arduino Talkie.
- **[speakie](https://github.com/raphlinus/speakie)** (Raph Levien) — decoder plus
  an encoder inspired by BlueWizard.

## Players and emulation

- **[Talkie](https://github.com/ArminJo/Talkie)** — Arduino playback of LPC
  bitstreams, originally by Peter Knight. The reason a great deal of TMS5220
  speech data exists in hobbyist projects at all.
- **PinMAME / MAME `tms5220.c`** — the most complete public implementation of
  the chip's behaviour, including the coefficient tables and the interpolation
  and excitation logic. The pitch-ceiling result in
  [PITCH_CEILING.md](PITCH_CEILING.md) was derived against it.

## Where this project fits

All of the above either **produce** LPC from audio or **play** LPC that already
exists. None of them re-indexes existing LPC data from one chip variant's tables
into another's.

That gap is narrow and it is the only thing here. If your TMS5200 has failed and
you have its speech ROM, you do not need to re-analyse anything: the parameters
are already correct, they are simply expressed in the wrong chip's tables. This
converts them, and tells you which frames the substitute part cannot reproduce.

If you have audio and no LPC, use one of the encoders above.

## Hardware and preservation references

- Texas Instruments, *TMS5220 Voice Synthesis Processor Data Manual* — the frame
  grammar, field widths and pin-level behaviour.
- **[Stuart Conner's TI speech pages](http://www.stuartconner.me.uk/)** — the
  most careful preservation work on TI speech hardware and the surviving
  development systems around it.
- Gene Helms and Steve Petersen, "Portable speech development system creates
  linear predictive codes", *Electronics*, 8 September 1982 — contemporary
  description of how this speech data was originally produced.

## Acknowledgements

The PinMAME and MAME teams, whose reverse engineering of the TMS52xx family is
the foundation under all of the above, including this.
