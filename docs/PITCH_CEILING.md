# The pitch floor

A TMS5220 cannot reproduce the lowest pitches available on a TMS5200. This page
records the limit and the workaround experiments run during development.

## The limit

The TMS5220's largest pitch-period table entry is **159 samples**. At an 8 kHz
sample rate, that corresponds to about **50.31 Hz**.

The TMS5200 table reaches **211 samples**, or about **37.9 Hz**.

A source frame below the TMS5220 floor therefore has no equivalent target-table
entry. Understudy clamps it to the lowest reachable TMS5220 pitch and records the
clamp in the conversion report.

This is a target-chip limit rather than a mapping error: changing which table
index is chosen cannot create a pitch period the target table does not contain.

## Workarounds that were tried

The following experiments were built as real bitstreams, rendered through the
PinMAME speech core, and measured in a separate development harness:

- maximum period plus interpolation between frames;
- alternating pitch values;
- repeat-frame stretching;
- energy modulation at a difference frequency;
- voiced/unvoiced alternation;
- interpolation ramps across frame boundaries;
- three subharmonic constructions.

None produced the missing lower fundamental. Some subharmonic tests improved
whole-signal metrics without moving the actual fundamental, so they were not
useful as a pitch fix.

The experimental harness is not shipped in this repository. The table-derived
floor itself is reproducible here through `ChipTables.lowest_f0_hz`.

## Confidence and scope

The 50.31 Hz figure depends on the TMS5220 table bundled with Understudy, whose
provenance is documented in [PROVENANCE.md](PROVENANCE.md). The workaround
comparisons depend additionally on the fidelity of the PinMAME synthesizer.

The first real-board Embryon test did not make its 17 clamped frames audibly
stand out to the listener, but that is one title and one board. A game with more
low-pitch material may behave differently.

## Library behavior

`convert_frames` maps an unreachable source pitch to the nearest reachable target
period and sets `pitch_clamped` on the frame's `FrameConversion`. The report also
records the source and target fundamentals so callers can see how much of a ROM
was affected before burning it.
