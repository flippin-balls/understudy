# Listening examples

Short comparison clips, so you can hear what this tool does before committing a
chip to it.

Each folder is one phrase from one game, in three versions. Play them in order:

| File | What it is |
|---|---|
| `1-original-on-TMS5200.mp3` | the original ROM through the chip the board shipped with — the target |
| `2-unconverted-on-TMS5220.mp3` | the **same unmodified ROM** through a TMS5220. This is what a straight chip swap sounds like |
| `3-converted-on-TMS5220.mp3` | the ROM **converted by Understudy**, through a TMS5220 |
| `0-ALL-THREE-in-order.mp3` | the three above back to back, with a gap, for A/B/C |

Track 2 is the one worth hearing. A TMS5220 dropped into a TMS5200 socket reads
the same index numbers against different coefficient tables, so the speech comes
out recognisably wrong rather than merely different. Track 3 is the same chip
with the numbers re-indexed.

## What these are and are not

- They are **renders**, produced by a hardware-accurate emulation of each part,
  not recordings from a machine. They isolate the chip: no amplifier, no
  cabinet, no speaker.
- They show the **default conversion** — the deterministic nearest-value
  mapping. None of them was produced with `--optimize-audio`, so nothing here
  is evidence for or against that option.
- They are lossy MP3 at 64 kbit/s. That is well above transparent for 8 kHz
  speech, but it is not the bit-exact output of the tool.
- Levels are matched **within** each folder: one gain was applied to all three
  versions of a phrase, so the comparison is fair. Levels are not matched
  between folders.

## Provenance

This project does not redistribute ROM data, and its `.gitignore` refuses the
formats that would carry it. These clips are a deliberate, narrow exception:
they are short lossy excerpts, published as documentation of what the tool does,
and approved for that use by the project owner. They are not a source of speech
data — nothing here can be converted back into ROM bytes, and no ROM images,
LPC parameter dumps or coefficient streams are published with them.

The games themselves remain the property of their respective rights holders.
