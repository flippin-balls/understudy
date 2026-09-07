# Which chip can replace which

**What this project can tell you:** the converted speech data is identical for
a TMS5220, a TMS5220C and a TSP5220C, because their LPC coefficient tables are
identical. Pick whichever you can get; the conversion does not change.

**What it cannot tell you:** whether the part you buy drops into your board.
No physical chip has been fitted or measured for this project. Pinout, supply
current, clock and output level are between you, the datasheet and the
schematic. Everything below is about the data.

```
understudy chips
```

lists what the tool accepts.

## The parts

| id | markings you will see | role |
|---|---|---|
| `tms5200` | TMS5200, TMS5200NL, CD2501E, TMC0285 | the original |
| `tms5220` | TMS5220, TMS5220NL | replacement |
| `tms5220c` | TMS5220C, TMS5220CNL | replacement |
| `tsp5220c` | TSP5220C | replacement |

The CD2501E/TMC0285 is the same part as the TMS5200 — MAME's decap notes record
them as equivalent, and it is the chip in the TI 99/4A speech module.

## Why the three replacements are one conversion target

Because the silicon says so. The coefficient tables Understudy bundles come from
MAME's `tms5110r.hxx`, and the comment above them reads:

> The TMS5220CNL was decapped and imaged by digshadow in April, 2013.
> The LPC table table is verified to match the decap and **exactly matches
> TMS5220NL**.

with the section headed "TMS5220/5220C (1983 era for 5220, 1986-1992 era for
5220C; **5220C may also be called TSP5220C**)". MAME keeps one table struct for
all three, and so does Understudy. A conversion targeting `tsp5220c` is
byte-for-byte the conversion targeting `tms5220`.

## What that does *not* mean

**The parts are not interchangeable in every respect.** The claim above is about
the LPC coefficient tables and nothing else.

The concrete difference that matters here is a command. On a TMS5200 or TMS5220,
the opcode in the `0x00`/`0x20` group is a **NOP**. On a TMS5220C it is
**SET RATE**, taking a variable frame rate from the low nibble
(MAME `tms5220.cpp`, `TMS5220_HAS_RATE_CONTROL`). A board that sent it would get
different speech timing from a 5220C than from a 5220.

At reset the rate is 0, and MAME's comment beside the reload table says
"5200 and 5220 always reload with 0" — so a 5220C that is never sent that
command behaves like a 5220.

**So the question for any given game is whether its firmware ever sends it.**
That is measurable, and Understudy records the answer per profile rather than
assuming it for the family. For Embryon, the board's own firmware was driven
through all 64 commands its MPU can send; it issues exactly one TMS command
byte, `0x60` SPEAK EXTERNAL, and never anything in the SET RATE range. The
profile records that as `chip_commands_observed`.

For a game with no profile, this has not been checked. It is very likely fine —
a board designed around a TMS5200 has no reason to send a command that part
treats as a NOP — but "likely" is the honest word.

Nothing here says anything about **pinout, supply current, clock, or output
level**. Check the datasheet for the part you actually intend to fit, and the
schematic for the board you are fitting it to.

## The one thing conversion cannot fix

The TMS5220 family cannot reach as low a pitch as the TMS5200. Its longest
excitation period is 159 samples against the TMS5200's 211 — about 50.3 Hz
against 37.9 Hz at the 8 kHz sample rate. Frames below the substitute's floor
are raised, and will sound higher than the original.

On Embryon that is 17 frames of 850, or 2.0%. `convert-set` reports the figure
for your ROM before it writes anything.
[PITCH_CEILING.md](PITCH_CEILING.md) covers what was tried and why none of it
worked.

## Using tables the tool does not bundle

`--source-tables` and `--target-tables` take a JSON file on both `convert` and
`convert-set`, overriding the bundled data. That is the research path, and the
route for a variant these tables do not cover.
[PROVENANCE.md](PROVENANCE.md) describes the format and where to get more.
