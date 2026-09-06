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
phrase's end implicit — pass `--no-end-bound`.

The implicit end is then the first of these that lies above the phrase's start:
**the pointer table, or the end of the image.** The table is included because
its own bytes cannot be speech, and on this board it very often sits *above* the
phrases it points at (Embryon's is at `$FC1C` in U5 while its speech starts at
`$E800` in U4), so "run to the end of the image" would swallow it. When the
table is below the speech, as it is on some sets, the implicit end is simply the
end of the image.

That rule handles the table, and nothing else. If anything other than speech and
the pointer table sits above your last phrase — code, sound effect data, a
checksum — the implicit end will run into it. Give the table an explicit end
bound if you can; otherwise check the reported extent of the last phrase before
converting.

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
python -m tms52xx.cli inspect embryon_snt.bin \
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

There are five things to find: where the pointer table is, how many entries it
has, what base address its pointers are relative to, whether it is in address or
command order, and whether it carries an end bound. `inspect` writes nothing, so
this is safe to iterate on.

### 1. Find the pointer table

A speech pointer table is a run of 16-bit big-endian values that all land inside
the ROM's address window and are mostly increasing. That is a distinctive enough
shape to scan for:

```python
import sys
data = open(sys.argv[1], "rb").read()
base, count = 0xC000, 8          # CPU base, and how many entries to require
for offset in range(0, len(data) - 2 * count, 2):
    values = [int.from_bytes(data[offset + 2 * i:offset + 2 * i + 2], "big")
              for i in range(count)]
    if all(base <= v < base + len(data) for v in values) and \
            all(b > a for a, b in zip(values, values[1:])):
        print("0x%04X  %s" % (offset, ["0x%04X" % v for v in values]))
```

Run it over the whole image. Real tables show up as a short list of candidates;
most are false positives from ordinary code, which the next steps eliminate.
Relax `all(b > a ...)` to a majority if you suspect command order.

### 2. Confirm it by where it points

Take a candidate and look at what the first pointer addresses. Speech data is
dense and high-entropy; code is not. A run of bytes with no long zero fills, no
obvious ASCII, and no repeating 6800 opcodes is a good sign.

### 3. Find the base address

The pointers are CPU addresses; the file is a socket image or a window over
several. Subtract the address the socket is mapped at. If the pointers are in
the `$Exxx`/`$Fxxx` range and your file is a 16 KB window over `$C000-$FFFF`,
the base is `$C000`. Get this wrong by a socket and every extent lands in the
wrong place, which the next step catches immediately.

### 4. Find the count and the end bound

Extend the run until the values stop looking like addresses. If the last
plausible value is one more than the number of phrases you expect, that last one
is an end bound; otherwise pass `--no-end-bound`. Bally command handlers often
make the count visible as a range check on the command byte before the table
lookup, if you are disassembling.

### 5. Check it, and know what the check is worth

```
python -m tms52xx.cli inspect speech.bin \
    --table-offset 0x3C1C --phrases 21 --base-address 0xC000 \
    --no-end-bound --command-ordered --source-tables tables/tms5200.json
```

A layout is probably right when:

- every extent is positive, and they tile the speech region without gaps;
- **every phrase ends in a stop frame** — with `--source-tables`, any phrase
  reported as `no stop` has not terminated;
- phrase lengths are plausible: a word or short sentence is typically a few
  dozen to a few hundred bytes.

**What the stop-frame check is worth.** A stop frame is four bits of `0xF`, and
that pattern occurs by chance in arbitrary data, so a single phrase terminating
proves very little. What carries weight is *every* phrase in a table terminating
and doing so at its own end rather than somewhere in the middle — a wrong
offset would have to be lucky repeatedly. Treat it as a strong consistency
check, not a proof. If some phrases terminate and others do not, the offset or
the count is wrong; if all of them do but the lengths are wildly uneven, suspect
the ordering or the base address.

A layout is wrong when extents overlap, when a phrase runs into the pointer
table, or when phrases decode without reaching a stop frame. `convert` refuses
all three rather than writing a file, and `--dry-run` is there to be used before
anything is written.

## What we have not solved

Automatic discovery of the table offset. Locating candidate tables by scanning
for plausible ascending 16-bit sequences is possible and we have not implemented
it, so for now the offset is something you determine and pass in.
