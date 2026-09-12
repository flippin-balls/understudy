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
one step up, one step down — by coordinate descent, accepting a candidate only
when it scored **strictly better**. Crucially, it did not judge candidates by
how close the *numbers* were. It **rendered** each one and compared the
resulting audio against the same speech played through a TMS5200's tables,
scoring the difference in spectral envelope over the frame and the one after it.

The search makes **two passes**, and the second steps from wherever the first
left off. So while the neighbourhood offered is ±1, a coefficient the search
moved twice ends up **two** places from the nearest mapping. That is the bound
enforced when the data is applied; 46 of Embryon's 1486 index moves are two.

Frame length, frame type, energy and pitch were held fixed throughout, so any
improvement is attributable to joint K selection alone.

On a 40-frame stratified sample of Embryon:

| Sample | n | Mean gain | Improved |
|---|---|---|---|
| worst frames | 10 | 2.77 dB (8.0 %) | 10/10 |
| median frames | 10 | 2.41 dB (19.2 %) | 10/10 |
| random frames | 20 | 1.72 dB (14.2 %) | 19/20 |

**39 of 40 improved; in 1, this search found nothing better than the
nearest-value choice.** (That is not the same as proving it optimal — a bounded
local search does not establish a global best.)

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
which the project does not do. An override stores only the step — `+1` or `-1`
per pass, so up to two places over the two passes — plus digests to check
against.

Those digests are the safety check, and getting their *scope* right took two
attempts. The score was measured on rendered audio, so it depended on more than
the frame being corrected:

- each phrase carries a **hash of its original, pre-conversion bytes**. This is
  the one that matters, because conversion is many-to-one: two different TMS5200
  originals can convert to byte-identical output, while the *reference* each was
  scored against is different audio. Nothing computed from the converted side
  can see that. It also covers the speech *before* the corrected frame, which
  sets the filter state the chip enters it with;
- each override additionally hashes **the frame and its successor**, every field
  — the score spanned both, and pitch and energy shape that audio as much as the
  filter does;
- the **coefficient table files** and the **profile version** are pinned too.

If any of them disagrees, the run stops. None degrades to applying the data
anyway.

## What still gets checked

Optimisation happens between conversion and packing, so every existing check
runs against the optimised bytes, not the unoptimised ones:

- the stream is still the same length;
- the output is re-parsed and every frame's type must be unchanged;
- every phrase must still end in a stop frame;
- only bytes inside declared phrase extents may differ, and only in
  speech-bearing devices;
- the profile still authenticates the dumps by hash.

Beyond those, and all enforced when the data is applied rather than assumed of
the file:

- **K indexes only** — energy, pitch, repeat flags and frame length are refused
  outright, so this mode cannot reach the pitch floor even by accident;
- **voiced frames only**, which is what was measured;
- **at most two places** from the nearest mapping, and never outside a field's
  bit width;
- **every override must record the score that justified it**, and that score
  must be a real number showing a strict improvement. A file claiming a
  regression is refused rather than applied;
- **the frame and its successor must hash to what was measured** — covering
  pitch and energy, not just the filter;
- **the coefficient tables and profile version must match** those the
  measurements were taken through;
- **every override must actually reach a frame.** Two pointers naming the same
  bytes are converted once, so an override keyed to the second would otherwise
  be skipped in silence while the manifest still claimed it was applied.

A violation stops the conversion. None of them degrades to applying the data
anyway.

## Coverage today

Only Embryon has been measured. Its whole eligible corpus was run, not a sample:
475 voiced frames above the silence gate, of which **456 improved and 19 found
nothing better** — the same 96 % rate the 40-frame study found, over twelve
times the frames. Every one of the 456 was re-checked against Understudy's own
conversion before shipping, and all 456 agreed.

The other fifteen profiles have no data, and `--optimize-audio` will say so
rather than convert without it.

### The honest caveat: frames were measured one at a time

Each frame was searched against the **unoptimised** phrase, and its score spans
the frame *and its successor*. Applying 456 corrections at once therefore is not
the same experiment: neighbouring corrections interact, and per-frame gains are
not additive by construction.

So the assembled result was measured too, by rendering every finished phrase and
scoring it whole against the TMS5200 reference:

| | |
|---|---|
| phrases improved | **18 of 20** |
| phrases slightly worse | **2 of 20** (phrase 0 by 0.67 dB, phrase 6 by 0.07 dB) |
| mean, whole phrase | **12.65 dB → 12.07 dB** (−0.57 dB) |

The net effect is an improvement and most phrases share it, but it is **not
uniform**: two phrases came out marginally worse as wholes than the ordinary
conversion.

### Why those two are still shipped

The obvious move is to drop them and let those phrases convert normally. They
are kept, deliberately, and the reason is about what MCD can and cannot tell
you.

MCD is a **spectral distance**: it measures how close the output is to the
TMS5200 reference. That is not the same question as how good it sounds. A small
blinded listening test run on a related optimisation for this family of chips
found exactly that divergence — on one item the listener called the *ordinary*
conversion the "cleanest" while judging the optimised version and the original
chip the most similar to each other. Fidelity and pleasantness came apart, and
every objective number available measures only the first.

That same test produced a second result pointing the other way from the metric:
on the two items where the listener independently reached for the word
"warbly", the warbly sample was the **ordinary, unoptimised** conversion — not
the optimised one. Twice, unprompted.

So a 0.67 dB and a 0.07 dB whole-phrase movement in a fidelity proxy is not a
sound basis for discarding per-frame improvements that were each measured
individually. Removing them would be tuning the shipped artefact against a
metric that has already been observed to disagree with a human ear, which is the
specific mistake that test exists to prevent.

Two honest limits on that reasoning: the listening test used **one listener and
eight items**, so it is engineering evidence and not a statistical result; and it
was run on a *different* optimisation strategy for the same chips, so it speaks
to how much weight the metric deserves, not to this data set specifically.

**There is no listening evidence for this optimiser.** The two phrases are named
above precisely so you can listen for them.

This is also why the flag is opt-in. If a phrase sounds worse on your machine,
convert without it and
[say so](HARDWARE_VALIDATION.md) — that is worth more than any number here.

## Auditing a run

The manifest records the mode on every conversion, including when it was off.
When it ran, it lists each frame that moved, which coefficients changed, and the
before/after score that justified the move — enough to trace "phrase 12 sounds
wrong" back to the exact indexes involved.

```
audio optimization
  frames considered      475
  frames improved        456
  baseline retained       19
  K indexes moved       1486
  mean spectral gain     2.09 dB
```
