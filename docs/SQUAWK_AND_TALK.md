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

Several properties vary between titles. None of them changes what conversion
does to the bits, but each changes *which bytes are a phrase*, so getting one
wrong converts the wrong region.

**What an entry IS.** Most tables are a list of phrase *starts*: each phrase
ends where the next begins. Some store **both bounds of every phrase**, as a
four-byte record — start high, start low, end high, end low. Centaur, Medusa,
Eight Ball Deluxe, Fireball II and Vector are all built this way.

The two are hard to tell apart, and the failure is quiet. Read a pair table as a
list of starts and every *end* pointer becomes a phrase too. Where the phrases
happen to be contiguous, each end equals the next start and you get a plausible
list with every entry duplicated. Where they are not, the invented phrases cover
whatever lies between the real ones — fill, padding, or code. Nothing raises,
because every other pointer really is a phrase start.

What gives it away is the shape. In a pair table, entries come in couples whose
second element is slightly above the first, and across a contiguous run you see
`A A B B C C` rather than `A B C`. Set `entry_form` to `start_end_pairs` in the
profile; ordering and an end bound then have no meaning, and stating either is
refused rather than ignored.

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

**Deliberate silence.** A few sets have a "say nothing" entry: a run of silence
frames and nothing else, played by real commands. That is byte-for-byte what a
pointer aimed at padding looks like, which is why Understudy refuses unexplained
silence — the Embryon defect was exactly a pointer into padding. So the profile
must *name* the phrases it claims are silent, in `silent_phrases`, and the claim
is then checked: a named phrase that turns out to carry speech is refused. Flash
Gordon has two such entries, both pointing at the same 35 zero bytes.

**Phrases that never terminate.** Almost every phrase ends in a stop frame. In
at least one set — Mr. and Mrs. Pac-Man — exactly one phrase does not, and the
player supplies the terminator instead of the ROM. An unterminated phrase is
also what a layout aimed at code looks like, so this too stays refused unless
the profile names it in `unterminated_phrases`, and a named phrase that *does*
terminate is refused in turn. Name only the phrases you have checked: the point
of the list is that every other phrase must still stop.

There is no terminator byte, no length field and no checksum. A phrase's end is
positional: it is wherever the next phrase begins.

## Where the ROMs come from

This tool operates on speech ROMs you already possess. It distributes none, and
none are included here. Game ROM images are the manufacturer's or rights
holder's copyrighted code — owning the machine is not the same as being licensed
to redistribute its ROMs, and PinMAME does not ship them either. Three routes:

**Read your own board.** This is the normal one, and it is also the only one
that gives you a dump of *your* machine rather than someone's idea of what it
should contain — revisions differ, and boards get modified in the field. You
need an EPROM programmer that can read the devices in the sound board's sockets.
Pull each device, read it, and save one file per socket. Label the files with
the socket, because the CPU address a device maps to is what makes the layout
work and nothing in the file records it.

**The Internet Pinball Database.** [ipdb.org](https://www.ipdb.org/) is the
community's reference catalogue: an entry per machine, with manuals, schematics
and flyers, and ROM images for many titles. It is the first place to look, and
the manual and schematic are worth having even when you dump your own devices —
the schematic tells you which socket is which and what device type it expects,
which is exactly what the assembly step below needs. Check the notes on the page
for the terms attached to a particular download.

**Buy licensed reproduction ROMs.** Several pinball parts vendors sell
reproduction sets under licence, and some rights holders publish updated
firmware for their own titles. If you go this way you have a file already and
can skip to assembling the image.

### Device types, and the trap in them

A Squawk & Talk socket is nominally 4 KB but may hold a 2 KB device, and the
board carries jumper options for **either a 2532 or a 2732**. Both are 4Kx8
EPROMs and they are *not* pin-compatible — that is exactly why the jumper
options exist. Embryon's own documentation lists two jumper sets for this
reason:

```
2532: C,E,D,G,Q,S,U,X,Y,AA
2732: C,E,F,P,R,T,U,X,Z,BB
```

So before reading or burning anything:

* **identify the device actually fitted**, from its own part number, not from
  what a ROM list says should be there;
* **tell your programmer the right device type** — reading a 2532 as a 2732 or
  the reverse gives you a file of the right size and the wrong contents; and
* **if you change device type when you reburn, move the jumpers to match.**

Embryon, as a worked example, has a 2716 (2 KB) in U4 and a 2532 (4 KB) in U5.

### Check what you read before you trust it

A speech ROM is mostly high-entropy LPC data. A dump that is all `0xFF`, all
`0x00`, or visibly repeating at a small period was not read correctly — usually
the wrong device type or a socket that needed reseating. Read each device twice
and compare the files; if they differ, fix the read before going any further.
Once you have an image assembled, `inspect --source-tables` gives you a stronger
check: a wrong dump does not produce phrases that all end in stop frames.

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

WINDOW = 0xC000                                # CPU address the image starts at
SIZE = 0x4000                                  # $C000-$FFFF
image = bytearray(b"\xFF" * SIZE)              # 0xFF = erased, so gaps show

def place(path, cpu_addr, size):
    data = open(path, "rb").read()
    if len(data) != size:
        raise SystemExit("%s is %d bytes, expected %d" % (path, len(data), size))
    at = cpu_addr - WINDOW
    if at < 0 or at + size > SIZE:
        raise SystemExit("%s at 0x%04X does not fit the window" % (path, cpu_addr))
    image[at:at + size] = data
    if size == 0x800:                          # 2 KB device in a 4 KB socket
        image[at + 0x800:at + 0x1000] = data   # mirrored into the upper half

place("841-01_4.716", 0xE000, 0x800)           # U4, 2716
place("841-02_5.532", 0xF000, 0x1000)          # U5, 2532
assert len(image) == SIZE                      # slice assignment can resize
open(sys.argv[1], "wb").write(bytes(image))
```

The size and range checks are not ceremony. Python slice assignment silently
*resizes* a `bytearray` when the slice and the data disagree, so an oversized or
misplaced dump would produce a longer-than-16 KB image with every subsequent
address shifted, and nothing would say so.

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

WINDOW = 0xC000
before = open(sys.argv[1], "rb").read()      # the image you converted FROM
after = open(sys.argv[2], "rb").read()       # the image convert produced
if len(before) != len(after):
    raise SystemExit("the two images are different sizes")

def extract(path, cpu_addr, size, holds_speech):
    at = cpu_addr - WINDOW
    halves = [(at, at + size)]
    if size == 0x800:                        # 2 KB device in a 4 KB socket
        halves.append((at + 0x800, at + 0x1000))

    changed = [(lo, hi) for lo, hi in halves if after[lo:hi] != before[lo:hi]]
    if len(changed) > 1:
        # Both halves changed. That is allowed: the two windows are the same
        # 2 KB device, and a set may reach some phrases through one and some
        # through the other. Merge them, and refuse only where they DISAGREE
        # about a byte, because that is one physical byte with two values.
        (alo, _), (blo, _) = halves
        merged = bytearray(before[alo:alo + size])
        for i in range(size):
            a, b, was = after[alo + i], after[blo + i], before[alo + i]
            if a != was and b != was and a != b:
                raise SystemExit(
                    "%s: offset 0x%X converts to 0x%02X through one mirror "
                    "window and 0x%02X through the other; one device cannot "
                    "hold both" % (path, i, a, b))
            merged[i] = a if a != was else b
        open(path, "wb").write(bytes(merged))
        return size
    if holds_speech and not changed:
        raise SystemExit("%s: declared as holding speech but nothing in it "
                         "changed -- the layout is probably wrong" % path)
    if changed and not holds_speech:
        raise SystemExit("%s: declared as holding no speech but it changed"
                         % path)

    lo, hi = changed[0] if changed else halves[0]
    open(path, "wb").write(after[lo:hi])
    return hi - lo

# Declare which devices you expect to carry speech.
DEVICES = [("841-01_4_5220.716", 0xE000, 0x800, True),
           ("841-02_5_5220.532", 0xF000, 0x1000, True)]

for path, addr, size, speech in DEVICES:
    print("%-22s %5d bytes" % (path, extract(path, addr, size, speech)))
```

**Declare the speech-bearing devices, and mean it.** A device that simply comes
out `unchanged` is ambiguous: it might hold no speech, or the layout might have
missed its phrases entirely, and those look identical from here. Saying which
devices you expect to change turns that ambiguity into an error.

**Both mirror halves changing is not by itself an error.** The two windows are
one 2 KB device answering at two addresses, and a set may reach some phrases
through each — Eight Ball Deluxe does. The halves merge. What cannot be merged
is one offset converted two different ways through the two windows: that is a
single physical byte with two values, so only one conversion could survive into
the burned device and the other phrase would be read as corrupt.

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
| phrases | **20** -- the 21st entry is an END BOUND, not a phrase |
| order | command order, not address order |
| end bound | yes, the final entry at `$F9DA` |
| speech | starts at CPU `$E800`, i.e. through U4's mirror |

```
python -m tms52xx.cli inspect embryon_snt.bin \
    --table-offset 0x3C1C --phrases 20 --base-address 0xC000 \
    --command-ordered
```

**That last entry cost real time, so it is worth the warning.** Reading the
table as 21 phrases looks right: the pointers are all plausible and ascending,
and every "phrase" including the 21st parses and ends in a stop frame. But the
21st points at six zero bytes followed by `8E 00 7F` (`LDS #$007F`) and
`BD FA 5F` (`JSR $FA5F`) -- the board's own code. The zeros read as silence
frames and the parser ran on until a byte in the code happened to carry a `0xF`
nibble. Converting that stretch rewrote instructions, and the board stopped
booting in simulation.

A pointer aimed at padding gives itself away by a long run of leading silence
frames: across Embryon's 20 real phrases every one begins with none, and that
entry begins with twelve. Understudy refuses a phrase like that now and suggests
trying one fewer with an end bound.

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
  reported as `no stop` has not terminated. Treat one that does not as a wrong
  layout until you have evidence otherwise; the rare alternative, a ROM whose
  player supplies the terminator, is covered under "Phrases that never
  terminate" above;
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
table, or when phrases decode without reaching a stop frame and you cannot show
the player supplies one. `convert` refuses
all three rather than writing a file, and `--dry-run` is there to be used before
anything is written.

### 6. The step that actually settles it

Everything above is the ROM describing itself. A wrong layout that reads real
pointers produces real phrases, so all of those checks can pass on a layout that
is simply reading the wrong part of the table — and they have, three times in
this project. Two of those wrong layouts also booted the board correctly.

The check that separates a plausible layout from a right one has to come from
outside the ROM's own description of itself:

1. run the board's own firmware against the **original** ROMs;
2. issue every command the MPU can send, and capture the byte stream the
   firmware feeds the TMS;
3. find each captured stream back in the ROM.

That gives a list of phrase addresses derived from **execution**. A layout is
right when every stream the firmware plays falls inside a phrase the layout
converts. Two details matter when comparing:

- **Trim each captured stream at its own stop frame.** The player keeps reading
  past the terminator until the chip stops asking, so a captured stream runs a
  few bytes into whatever follows it — erased `0xFF` in most sets, an ASCII
  build stamp in Eight Ball Champ. Those bytes are not speech.
- **Compare in device offsets, not CPU addresses.** A 2 KB part answers at two
  addresses, and a set may reach some phrases through the lower window and
  others through the mirror. Embryon addresses its speech entirely through the
  upper one; Eight Ball Deluxe uses both.

Phrase *starts* may legitimately disagree: a set can enter a phrase part-way
through, so the firmware plays from an address the table never lists. Mysterian
does this ten times. What may not happen is a played **byte** going unconverted,
because that byte is still read with the old tables.

This project runs that check with a private research toolkit that is not in this
repository, because it needs ROM images. If you are working out a layout without
it, the honest position is that your layout is a hypothesis — say so when you
contribute it, and it will ship as `draft` rather than `board-simulated`.

## What we have not solved

Automatic discovery of the table offset. Locating candidate tables by scanning
for plausible ascending 16-bit sequences is possible and we have not implemented
it, so for now the offset is something you determine and pass in.
