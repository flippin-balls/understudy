# Finding the phrases in a Squawk & Talk ROM

The converter needs to know which bytes are speech. This page is what we have
established about that, and — more usefully — which parts of it do not
generalise.

Everything here is our own analysis of ROM structure. No ROM data is reproduced.

## The board

Bally AS-2518-61. An M6802 sound CPU, no banking, four fixed 4 KB ROM sockets,
and a TMS5200 for speech.

One correction worth recording because it costs time: the header comment in
PinMAME's `by35snd.h` describes this board's CPU as an M6809. The instruction
decoding in the emulated ROM behaves as an M6802/6800, and the board's own
documentation agrees. Trust the decode, not the comment.

## What generalises

Phrases are addressed through a table of **16-bit big-endian pointers** that
precedes the speech data. That much holds everywhere we have looked.

## What does not generalise

Three properties vary between titles. None of them changes what conversion does
to the bits, but each changes *which bytes are a phrase*, so getting one wrong
converts the wrong region.

**Ordering.** Most tables list phrases in address order, so consecutive entries
are consecutive in memory and the difference between neighbours is a phrase
length. Some list them in *command* order instead, where entry N is the phrase
that command N plays and neighbouring entries are unrelated addresses. At least
one set duplicates every entry. Differencing a command-ordered table produces
negative or absurd extents; `PhraseTable.from_pointers` raises rather than
proceeding, and `--command-ordered` sorts the pointers first.

**End bound.** Most tables carry N+1 entries for N phrases, the last being the
end of the final phrase. At least one carries exactly N, leaving the final
phrase's end implicit — pass `--no-end-bound` and it is taken to run to the end
of the image.

**The final byte.** Some players stream a phrase verbatim. Others send
`rom[start:end-1]` and substitute a zero for the last byte, so a phrase's final
ROM byte is never transmitted. This is a property of the individual stream, not
of the board or even of the game: single ROM sets are known to use both
conventions across different phrases.

`--truncate-last-byte` therefore takes phrase indexes — `--truncate-last-byte
3,7,12` — and leaves those phrases' final bytes untouched in the output. The
bare flag applies it to every phrase.

Which phrases need it is partly readable from the data. `inspect
--source-tables` parses each phrase both ways and reports whether its final byte
is `required` (it carries part of the stop frame, so truncating would remove the
terminator) or `spare` (the phrase already terminates before it). What it cannot
tell you is which convention your player uses: that is firmware behaviour and is
not recorded in the speech data. The diagnostic tells you where truncation is
*safe*, not where it is *needed*.

There is no terminator byte, no length field and no checksum. A phrase's end is
positional: it is wherever the next phrase begins.

## A worked layout: Bally Embryon

Layout facts, not ROM contents. They are here because the hardest part of using
this tool is discovering these five numbers, and one worked example makes the
next one much easier to find.

Embryon's Squawk & Talk carries a 2716 in U4 and a 2532 in U5. Assemble the
CPU's view of them — a 16 KB image covering `$C000-$FFFF`, with U4 at `$E000`
mirrored into `$E800` and U5 at `$F000` — and the layout is:

| | |
|---|---|
| pointer table | CPU `$FC1C` (file `0x3C1C` at base `$C000`) |
| entries | 21, each a 16-bit big-endian CPU address |
| order | command order, not address order |
| end bound | none; the table is 21 entries for 21 phrases |
| speech | starts at CPU `$E800`, i.e. through U4's mirror |

```
understudy inspect embryon_snt.bin \
    --table-offset 0x3C1C --phrases 21 --base-address 0xC000 \
    --no-end-bound --command-ordered \
    --source-tables tables/tms5200.json
```

Two features of this layout are worth noticing because they are easy to get
wrong and neither is unusual:

* **the table sits ABOVE the speech.** It is in U5 at `$FC1C`; the phrases are
  in U4 from `$E800`. A phrase starting at a lower address than its own pointer
  table is normal.
* **the last phrase is bounded by the table, not by the end of the image.** With
  no end-bound entry the final phrase's end is implicit, and taking it as
  "the end of the ROM" would swallow the pointer table. `from_pointers` stops it
  at the table instead.

## Working out the layout for your ROM

`understudy inspect` reports size and hash. Given `--table-offset` and
`--phrases` it interprets the table and prints the extents it derives, without
writing anything.

A layout is probably right when:

- every phrase extent is positive and they tile the speech region without gaps
  or overlaps;
- `understudy convert --dry-run` reports a stop frame found in every phrase
  (`phrases with no stop frame: 0`);
- phrase lengths are plausible — a few dozen to a few hundred bytes for a word
  or a short sentence at roughly 1.8 kbit/s.

A layout is wrong when extents overlap, when lengths are wildly uneven, or when
phrases decode without ever reaching a stop frame. The dry run is there to be
used before anything is written.

## What we have not solved

Automatic discovery of the table offset. Locating candidate tables by scanning
for plausible ascending 16-bit sequences is possible and we have not implemented
it, so for now the offset is something you determine and pass in.
