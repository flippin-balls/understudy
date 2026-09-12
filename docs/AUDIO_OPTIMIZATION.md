# Audio optimization (`--optimize-audio`)

`--optimize-audio` is an optional conversion mode. Without the flag, Understudy
uses the same nearest-value conversion as before the optimizer was added.

## What it changes

The default converter maps each TMS5200 parameter independently to the nearest
value in the target chip's tables. That is deterministic and length-preserving,
but the ten K coefficients in a voiced frame act together as one filter. A
slightly different combination of K indexes can therefore render closer to the
TMS5200 reference even when some individual coefficients move farther from their
nearest values.

The optimizer changes **K indexes only**. It does not change energy, pitch,
frame type, repeat flags, phrase boundaries, or frame length.

## How the measurements were made

The search was run offline, not during conversion. Starting from the normal
nearest-value mapping, it tried each K index's immediate neighbors by coordinate
descent and accepted a move only when the rendered result scored strictly
better against the TMS5200 reference.

The search makes two passes. A coefficient can therefore end up at most two
index positions from the default mapping.

Candidates were scored by rendering the frame and its successor and comparing
the spectral envelope with the TMS5200 reference. Energy, pitch, timing, and
frame type were held fixed.

A 40-frame stratified Embryon study produced:

| sample | n | mean gain | improved |
|---|---:|---:|---:|
| worst frames | 10 | 2.77 dB (8.0%) | 10/10 |
| median frames | 10 | 2.41 dB (19.2%) | 10/10 |
| random frames | 20 | 1.72 dB (14.2%) | 19/20 |

**39 of 40 frames improved.** The remaining frame had no better candidate within
the bounded search.

The full eligible Embryon corpus was then measured: 475 voiced frames above the
silence gate, with improvements found for **456** and the default mapping kept
for **19**. Across the 456 changed frames, 1,486 K indexes move; 46 of those
moves are two positions from the default mapping.

## Phrase-level result

The search scores frames locally, so frame gains are not additive. The finished
phrases were therefore rendered and scored separately:

| result | Embryon | whole library |
|---|---:|---:|
| phrases improved | 18 of 20 | 375 of 441 |
| phrases unchanged | 0 | 2 |
| phrases worse | 2 of 20 | 64 of 441 |
| worst single regression | +0.67 dB | +12.13 dB (Elektra) |

Every game's mean whole-phrase score improves. But Embryon set an expectation
the rest of the library does not meet: its worst phrase is 0.67 dB worse, while
Elektra's is **eighteen times that**, and seven other titles exceed 2 dB. See
[Coverage](#coverage) for the per-game figures and what the regressions turned
out to be.

The shipped data keeps the frame-local choices from the measured search.
Phrase-level scoring is reported as a separate check and is not used to reselect
individual frames. The mixed result is one reason the feature remains opt-in.

There is **no real-hardware listening result for the optimized ROMs yet**. The
Embryon hardware result documented elsewhere used the ordinary conversion.

## Why the search is not run inside Understudy

Scoring requires a speech synthesizer and spectral analysis. Understudy itself
has no synthesis or FFT dependency, so conversion-time scoring would either add
a large dependency stack or use a different scorer from the one that produced
the measured data.

Instead, the repository ships the measured **outcome**: for each optimized
frame, which direction each K index moved on each pass.

The optimization data contains no absolute source K values. It stores step
directions and hashes used to verify that the measurements still describe the
ROM, profile, and coefficient tables being converted.

## What is checked before applying optimization data

Optimization data is tied to the material it was measured against. A mismatch
stops the conversion.

Understudy checks:

- a hash of each original, pre-conversion phrase;
- a guard covering the optimized frame and its successor, including all fields
  and frame kinds;
- the source and target coefficient-table hashes;
- the profile version;
- that each recorded score is finite and represents a strict improvement;
- that only voiced-frame K indexes are changed;
- that no K index moves more than two positions from the default mapping;
- that every recorded override is actually reached and applied.

The original-phrase hash matters because conversion is many-to-one: different
TMS5200 inputs can map to identical TMS5220 frames while having different source
audio. A guard based only on the converted frame cannot distinguish them.

## Existing conversion checks still apply

Optimization runs before the final ROM is packed, so the normal safety checks
see the optimized output. The stream must keep the same length, frame kinds must
survive re-parsing, phrases must terminate as the profile expects, changed bytes
must remain inside the declared speech regions, and device/image byte counts
must reconcile.

The optimizer does **not** change pitch handling. Frames below the TMS5220 pitch
floor are handled exactly as they are in the default conversion; see
[PITCH_CEILING.md](PITCH_CEILING.md).

## Coverage

Fifteen of the sixteen supported profiles ship optimization data. `bigbat` has
none, because no ROM set was available to measure it; on a profile without data
`--optimize-audio` stops with an error rather than silently falling back to the
default mapping.

Every game was measured by the identical process — same renderer, same metric,
same eligibility gate, same two-pass local search, same strict-improvement rule.
No game has tuning of its own and nothing in the runtime is game-specific.

| game | optimization | whole-phrase result |
|---|---|---|
| `beatclck` | measured | 43 better / 17 worse, worst +7.37 dB |
| `bigbat` | none | no ROM set available to measure |
| `centaur` | measured | 29 better / 8 worse, worst +11.62 dB |
| `eballchp` | measured | 34 better / 4 worse, worst +11.86 dB |
| `eballdlx` | measured | 39 better / 3 worse, worst +11.86 dB |
| `elektra` | measured | 12 better / 4 worse, worst +12.13 dB |
| `embryon` | measured | 18 better / 2 worse, worst +0.67 dB |
| `fathom` | measured | 24 better / 2 worse, worst +1.05 dB |
| `fball_ii` | measured | 13 better / 0 worse |
| `flashgdf` | measured | 9 better / 1 worse, worst +0.02 dB |
| `flashgdn` | measured | 7 better / 1 worse, worst +1.08 dB |
| `m_mpac` | measured | 18 better / 7 worse, worst +7.37 dB |
| `medusa` | measured | 23 better / 4 worse, worst +0.97 dB |
| `mysteria` | measured | 30 better / 6 worse, worst +2.48 dB |
| `spectrum` | measured | 29 better / 2 worse, worst +0.32 dB |
| `vector` | measured | 47 better / 3 worse, worst +2.16 dB |

Across all fifteen: **10,151 eligible frames, 9,777 improved** (96.3 %), 31,797
K indexes moved.

### What the regressions are, and are not

The frame-level result generalises well — 96 % of frames improve in every game,
and most titles gain more per frame than Embryon did. The phrase-level result
does not generalise as cleanly, and `fball_ii` is the only game with no
regression at all.

- **Not random.** Bally reused speech between machines. Where the same phrase
  appears in several ROM sets it regresses by an identical amount in each:
  `eballchp` #0 and `eballdlx` #2 are the same audio and both move 9.40 → 21.26
  dB. The 64 regressed instances are 53 distinct pieces of speech.
- **Not the pitch floor.** Clamped frames are 2.8 % of regressed phrases and
  3.1 % of improved ones.
- **Not over-correction.** Regressed and improved phrases carry the same
  fraction of corrected frames — 0.514 in both.
- **Correlated with length.** Regressed phrases average 35 frames against 45
  for improved ones. A short phrase gives the average fewer frames to absorb one
  badly diverging region.

That points back at the method's known gap: each frame was scored over itself
and its successor against the *unoptimised* phrase, so corrections that help
individually are not guaranteed to help together — and on short phrases they
sometimes do not.

**None of it has been listened to.** No optimised ROM for any game has been
played on hardware. Treat the table as measurement, not recommendation, and the
large-regression titles as unproven until somebody hears them.

Run it with:

```text
python understudy.py convert-set . --optimize-audio
```

The manifest records whether optimization was enabled, the optimization-data
digest and method, every changed frame, the K indexes moved, and the recorded
before/after score.

A typical summary is:

```text
audio optimization
  frames considered      475
  frames improved        456
  baseline retained       19
  K indexes moved       1486
  mean spectral gain     2.09 dB
```

If you test an optimized set on real hardware, please report it using
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).
