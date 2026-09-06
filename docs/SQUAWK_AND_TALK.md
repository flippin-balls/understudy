# Finding the phrases in a Squawk & Talk ROM

The converter needs to know which bytes are speech. This page is what we have
established about that, and — more usefully — which parts of it do not
generalise.

### Where this comes from, and how far to trust it

This is our own analysis, not a citation of a datasheet, and no ROM data is
reproduced. The sample is the **49 Squawk & Talk ROM sets PinMAME ships** — the
count `snt_common.discover_games()` returns from its driver — examined with a
private toolkit that is not part of this repository. So "most tables", "at least
one set" and "everywhere we have looked" all mean *within those 49*, read
statically. They are observations at that sample size, not verified facts about
every board Bally built, and only **Embryon has been taken end to end**, through
conversion and rendering. Where a claim rests on something you can check
yourself, the check is given alongside it.

Board details below are read from PinMAME's driver sources and the board's own
documentation, both public.

## The board

Bally AS-2518-61. An M6802 sound CPU, no banking, four fixed 4 KB ROM sockets,
and a TMS5200 for speech.

One correction worth recording because it costs time: the header comment in
PinMAME's `src/wpc/by35snd.h` (line 25) calls this board's CPU an M6809. The
driver beside it does not — `src/wpc/by35snd.c` line 469 reads
`MDRV_CPU_ADD(M6802, 3579545./4.)`, and `src/cpu/m6800/m6800.c` line 161 is
`#define m6802 m6800`. So it is a plain 6800, and the board's own documentation
agrees. Trust the driver, not the comment. (Line numbers are from the PinMAME
revision pinned in [PROVENANCE.md](PROVENANCE.md).)

## What generalises

Phrases are addressed through a table of **16-bit big-endian pointers**. That
much holds everywhere we have looked. Where the table SITS does not generalise:
it may lie below the speech it points at or above it, and Embryon's is above.

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

## From socket dumps to a converted set

You start with one file per ROM device and you need to end with one file per ROM
device. The converter works on a single image, because a phrase can begin in one
socket and the pointers are CPU addresses, so the middle of this is a 16 KB view
of `$C000-$FFFF`.

**1. Assemble the CPU's view.** Fill unpopulated sockets with `0xFF`, the erased
state, so it is obvious they are not data. A 2 KB device in a 4 KB socket is
mirrored into the upper half, and that mirror matters: Embryon's firmware
addresses all of U4's speech through it, so pointers land at `$E800`, not
`$E000`.

```python
import sys

image = bytearray(b"\xFF" * 0x4000)          # $C000-$FFFF

def place(path, cpu_addr):
    data = open(path, "rb").read()
    at = cpu_addr - 0xC000
    image[at:at + len(data)] = data
    if len(data) == 0x800:                    # 2 KB device in a 4 KB socket
        image[at + 0x800:at + 0x1000] = data  # mirrored into the upper half

place("841-01_4.716", 0xE000)                 # U4, 2716
place("841-02_5.532", 0xF000)                 # U5, 2532
open("embryon_snt.bin", "wb").write(bytes(image))
```

**2. Convert it.** Use the layout from the section below.

**3. Split it back into devices — and mind the mirror.** This is the step with
a trap in it, and it is not obvious.

Conversion rewrites the bytes the *pointers* address. When a 2 KB device is
mirrored into a 4 KB socket and the firmware addresses its speech through the
mirror, only the mirror gets converted. The lower copy is left exactly as it
was. On Embryon that is precisely what happens:

```
U4 lower copy  $E000-$E7FF      0 bytes changed     <- stale
U4 mirror      $E800-$EFFF   1560 bytes changed     <- the converted data
U5             $F000-$FFFF   1960 bytes changed
```

So "take the lower half of a mirrored device" gives you an unconverted ROM that
looks plausible and burns fine. Take the half that actually changed:

```python
import sys

before = open(sys.argv[1], "rb").read()      # the image you converted FROM
after = open(sys.argv[2], "rb").read()       # the image convert produced

def extract(path, cpu_addr, size):
    at = cpu_addr - 0xC000
    halves = [(at, at + size)]
    if size == 0x800:                        # 2 KB device in a 4 KB socket
        halves.append((at + 0x800, at + 0x1000))

    changed = [(lo, hi) for lo, hi in halves if after[lo:hi] != before[lo:hi]]
    if len(changed) > 1:
        raise SystemExit("%s: both mirror halves changed; the layout puts "
                         "phrases in both, which cannot be burned to one device"
                         % path)
    lo, hi = changed[0] if changed else halves[0]
    open(path, "wb").write(after[lo:hi])
    return (hi - lo), len(changed)

for path, addr, size in (("841-01_4_5220.716", 0xE000, 0x800),
                         ("841-02_5_5220.532", 0xF000, 0x1000)):
    wrote, touched = extract(path, addr, size)
    print("%-22s %5d bytes  %s" % (path, wrote,
                                   "converted" if touched else "unchanged"))
```

A device reported as `unchanged` holds no speech, and you do not need to reburn
it. If the script stops because both halves changed, your layout has phrases at
both the real and mirrored addresses, which a single device cannot represent —
the layout is wrong.

**Check before you burn.** Each output must be exactly the size of the original,
and the differing byte counts must add up to what conversion reported:

```
$ ls -l 841-01_4.716 841-01_4_5220.716            # sizes must match
$ cmp -l 841-01_4.716 841-01_4_5220.716 | wc -l   # 1560
$ cmp -l 841-02_5.532 841-02_5_5220.532 | wc -l   # 1960
```

1560 + 1960 = 3520, which is the `bytes changed` the conversion printed. If the
totals do not reconcile, or a socket that holds no speech has changed, stop.

Re-assembling step 1 from the new devices reproduces the converted image exactly
across every address the board reads speech from. It differs only in U4's
`$E000-$E7FF` window, which now carries converted data rather than the stale
copy — the device holds 2 KB and appears twice, so this is the correct outcome
rather than a discrepancy.

**Checksums.** This tool does not compute or update any ROM checksum. If your
board verifies one, that is a separate step and it is on you.

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
the ROM's address window and mostly increase. That shape is distinctive enough
to scan for. This reports each maximal run rather than every window that starts
inside one, so the output is a short list rather than a page of near-duplicates:

```python
import sys

data = open(sys.argv[1], "rb").read()
base = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
least = 6                       # shortest run worth reporting

def word(at):
    return int.from_bytes(data[at:at + 2], "big")

def plausible(at):
    return at + 2 <= len(data) and base <= word(at) < base + len(data)

seen = set()
for start in range(len(data) - 1):
    if start in seen or not plausible(start):
        continue
    end = start
    while plausible(end + 2) and word(end + 2) > word(end):
        end += 2
    run = (end - start) // 2 + 1
    if run >= least:
        seen.update(range(start, end + 2))
        print("0x%04X  %2d entries  0x%04X..0x%04X"
              % (start, run, word(start), word(end)))
```

It scans every offset, not every even one: nothing guarantees these tables are
aligned, and assuming they are will hide half of them. On the Embryon image it
prints two candidates:

```
0x3C1C  21 entries  0xE800..0xF9DA
0x3EA1  18 entries  0xFEC5..0xFFED
```

The first is the speech table, and the run length has already told you the entry
count. The second is not: its entries are evenly spaced 0x11 apart, which is a
fixed-stride table of something else. Evenly spaced entries are a reliable
giveaway — real phrases are not all the same length. Relax `word(end + 2) >
word(end)` to a majority if you suspect command order.

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
