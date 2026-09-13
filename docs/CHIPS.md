# Which chip can replace which

Understudy produces the same converted bytes for the **TMS5220, TMS5220C and
TSP5220C** because they use the same LPC coefficient tables.

The converted ROMs are for the replacement chip named in the conversion report.
The normal `convert-set` target is the TMS5220 family. **Do not use those
converted ROMs with the original TMS5200.** A TMS5200 should use the original
ROM data; feeding it data re-indexed for TMS5220 tables makes it select the wrong
values in the opposite direction.

That only answers the data question. Check the pinout, supply, clock and output
requirements of the part you intend to fit against the board schematic. One
TMS5220 has been fitted to an Embryon Squawk & Talk for this project and worked
without a board change; the other parts have not been electrically tested here.

```
python understudy.py chips
```

lists the parts the tool accepts.

## The parts

| id | markings you may see | role |
|---|---|---|
| `tms5200` | TMS5200, TMS5200NL, CD2501E, TMC0285 | original |
| `tms5220` | TMS5220, TMS5220NL | replacement |
| `tms5220c` | TMS5220C, TMS5220CNL | replacement |
| `tsp5220c` | TSP5220C | replacement |

MAME's decap notes identify the CD2501E/TMC0285 with the TMS5200; it is also the
part used in the TI 99/4A speech module.

## Why the replacement targets produce the same data

The coefficient tables bundled with Understudy come from MAME's
`tms5110r.hxx`. MAME records the TMS5220C table as an exact match for the
TMS5220NL and notes that the TMS5220C may also be marked TSP5220C. MAME uses one
table structure for the three parts, and Understudy does the same.

The important behavioral difference is **SET RATE**. On a TMS5200 or TMS5220,
the `0x00`/`0x20` opcode group is a NOP. On a TMS5220C it controls variable frame
rate. A board that sends those commands can therefore behave differently with a
5220C even though the speech tables are the same.

Bundled profiles record the chip commands observed from their board firmware.
Understudy uses that evidence when deciding whether a C-family target is safe;
a profile without the required evidence is not automatically cleared for the
rate-controlled parts.

## Pitch range

The TMS5220 family cannot reach the lowest TMS5200 pitches. Its longest
excitation period is 159 samples rather than 211, about 50.3 Hz versus 37.9 Hz
at an 8 kHz sample rate. Understudy raises frames below the target's floor and
reports the count before you burn anything.

Embryon has 17 affected frames out of 850 (2.0%). They were not noticed in the
first real-board listening test. [PITCH_CEILING.md](PITCH_CEILING.md) covers the
experiments and the alternatives that were tried.

## Custom tables

The research commands accept `--source-tables` and `--target-tables` JSON files
instead of the bundled data. [PROVENANCE.md](PROVENANCE.md) documents the format
and sources.
