# Audio optimisation (`--optimize-audio`)

An optional conversion mode. The default is unchanged, and if you do nothing
differently you get exactly the ROM Understudy has always produced.

## What the default does, and where it gives something up

A speech frame does not store a sound. It stores ten index numbers that select
**reflection coefficients** — the settings of the filter that shapes the chip's
buzz into a vowel. The TMS5200 and TMS5220 hold different values at those
indexes, so the ordinary conversion looks up what the original asked for and
picks the nearest available number on the replacement chip, one coefficient at
a time.

Per coefficient, nothing is closer. The catch is that the ten are not ten
independent knobs — they are one filter. Rounding each to its own nearest value
does not necessarily land where the filter *as a whole* is nearest, in the same
way that rounding every ingredient in a recipe to the nearest spoon does not
give you the nearest-tasting dish.

## What was measured

Around each nearest-mapped K index, a search tried the immediate neighbours —
one step up, one step down — by coordinate descent. Crucially, it did not judge
candidates by how close the *numbers* were. It **rendered** each one and
compared the resulting audio against the same speech played through a TMS5200's
tables, scoring the difference in spectral envelope over the frame and the one
after it.

Frame length, frame type, energy and pitch were held fixed throughout, so any
improvement is attributable to joint K selection alone.

On a 40-frame stratified sample of Embryon:

| Sample | n | Mean gain | Improved |
|---|---|---|---|
| worst frames | 10 | 2.77 dB (8.0 %) | 10/10 |
| median frames | 10 | 2.41 dB (19.2 %) | 10/10 |
| random frames | 20 | 1.72 dB (14.2 %) | 19/20 |

**39 of 40 improved; the nearest-value choice was already optimal in 1.**

The controls are the point. An improvement measured only on the worst frames
could not be generalised — but typical frames gained *more* in percentage terms
than the worst ones did, so the gain is a property of ordinary speech rather
than of a damaged tail. Corroborating metrics agree on typical frames (LSD 8/10,
NRMSE 8/10 on the median sample) and are mixed on the worst ones, which are
pitch-limited frames that K changes cannot fix.

## What this is not

- **It is not a hardware result.** One converted Embryon set has been played on
  a real board, and that was the *ordinary* conversion, not this one. No
  optimised ROM has been listened to on real silicon by anyone. See
  [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), and please report what you
  hear.
- **It does not fix the pitch floor.** The TMS5220's excitation table stops
  shorter than the TMS5200's, so frames asking for a period below the floor are
  clamped upward and no amount of K optimisation changes that. Pitch is held
  fixed here precisely so this mode cannot be mistaken for a fix for it.
  [PITCH_CEILING.md](PITCH_CEILING.md) covers the real limitation.
- **It is not a promise about your game.** The measurement was made on one
  title's frames. A different game's speech could gain less, or nothing.
- **It is not available everywhere.** Data exists only for games the
  measurement has been run on. Asking for it elsewhere stops the run with a
  message saying so, rather than converting quietly without it.

## How it is applied, and why it is a data file

Scoring a candidate means synthesising it. The experiment did that through a
real speech core's arithmetic and compared spectra with a signal-processing
library. Understudy is one folder of Python with nothing to install — it has no
synthesiser and no FFT. Writing approximations of both would mean this tool
picked frames by a *different* measure than the validated one, while citing the
validated result.

So the search is not run at conversion time. What ships is its outcome: per
frame, which direction it stepped each coefficient.

That data deliberately contains **no coefficient values**. Storing "this was 15,
make it 14" would put real LPC data from a copyrighted ROM in this repository,
which the project does not do. An override stores only the step (`+1` or `-1`)
and an opaque hash of the frame's ten baseline indexes.

The hash is the safety check, and it is stricter than naming values would have
been. Before anything moves, the frame's own baseline is hashed and compared: if
the filter differs *anywhere* — a different dump, a revised profile, an edited
coefficient table — the override is refused and the run stops. A stale
measurement cannot be shifted onto a frame it was not taken on.

## What still gets checked

Optimisation happens between conversion and packing, so every existing check
runs against the optimised bytes, not the unoptimised ones:

- the stream is still the same length;
- the output is re-parsed and every frame's type must be unchanged;
- every phrase must still end in a stop frame;
- only bytes inside declared phrase extents may differ, and only in
  speech-bearing devices;
- the profile still authenticates the dumps by hash.

Beyond those, the optimiser may move **K indexes only**, by **one step**, on
**voiced frames**, and never outside a field's bit width. Each of those is
enforced when the data is applied rather than assumed of the file, and a
violation stops the conversion instead of being skipped.

## Auditing a run

The manifest records the mode on every conversion, including when it was off.
When it ran, it lists each frame that moved, which coefficients changed, and the
before/after score that justified the move — enough to trace "phrase 12 sounds
wrong" back to the exact indexes involved.

```
audio optimization
  frames considered      475
  frames improved        431
  baseline retained       44
  K indexes moved       1524
  mean spectral gain    1.83 dB
```
