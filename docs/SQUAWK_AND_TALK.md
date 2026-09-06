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
conventions across different phrases. `--truncate-last-byte` applies the second
convention, and leaves that byte untouched in the output.

There is no terminator byte, no length field and no checksum. A phrase's end is
positional: it is wherever the next phrase begins.

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
