# The pitch ceiling

The one thing conversion cannot fix, why, and how confident to be about it.

## The finding

A TMS5220's excitation period is loaded from its internal coefficient table.
The largest entry in that table is **159 samples**. The synthesiser counts up to
`current_pitch` and resets; interpolation moves that value *between* two table
entries, so it can never exceed the larger of them.

At the 8 kHz frame rate that puts the lowest reachable fundamental at
8000 / 159 = **50.31 Hz**.

The TMS5200's table reaches **211 samples**, i.e. **37.9 Hz**.

A TMS5200 stream containing frames below about 50 Hz therefore has no
destination on a TMS5220. Those frames must be clamped upward, and they will
sound higher-pitched than the original. No re-indexing scheme fixes this,
because the constraint is the destination table, not the mapping.

## What was tried

Nine candidate workarounds were each constructed as a real bitstream, rendered,
and measured rather than reasoned about:

- driving the period field to its maximum and relying on interpolation between
  frames to average lower;
- alternating between two period values to produce a lower perceived rate;
- exploiting the repeat-frame mechanism to stretch a period across frames;
- amplitude modulation of the energy field at the difference frequency;
- deliberate voiced/unvoiced alternation;
- interpolation ramps across frame boundaries;
- and three subharmonic constructions.

All failed. The subharmonic approach was rejected on measurement rather than on
principle: whole-signal metrics improved slightly while the fundamental did not
move, which is the signature of adding energy at the right frequency without
changing the excitation rate.

## How much to trust this

**It is an emulator-derived result. It has not been confirmed on silicon.**

The measurements were made against PinMAME's unmodified synthesiser
(`src/sound/tms5220.c`) reading the tables in `src/sound/tms5220r.c`. Two things
argue that the conclusion transfers:

1. it follows from the coefficient table and the counter comparison, both of
   which are documented chip behaviour rather than emulator conveniences; and
2. it is a statement about what the table *contains*, which is not a modelling
   choice.

Two things argue for caution:

1. no real TMS5220 has been measured for this project; and
2. finer-grained claims — how a particular conversion strategy compares to
   another — depend on the emulator's interpolation and lattice arithmetic being
   faithful, which is a stronger assumption than the ceiling itself needs.

In summary: the ceiling is very likely real, and the exact figure of 50.31 Hz is
contingent on the emulator's table being correct.

## What the library does about it

Nothing clever, deliberately. `convert_frames` clamps to the nearest reachable
period and records `pitch_clamped` on the frame's `FrameConversion`, along with
the source and target fundamentals.

That way a caller can report how much of a given stream is affected before
deciding whether the substitution is acceptable for that machine, rather than
finding out from a customer.
