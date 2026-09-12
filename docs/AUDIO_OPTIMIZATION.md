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

| result | Embryon |
|---|---:|
| phrases improved | 18 of 20 |
| phrases slightly worse | 2 of 20 |
| mean whole-phrase score | 12.65 dB → 12.07 dB |

Phrase 0 was 0.67 dB worse and phrase 6 was 0.07 dB worse on the whole-phrase
metric.

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

Only **Embryon** currently ships optimization data. On another profile,
`--optimize-audio` stops with an error rather than silently falling back to the
default mapping.

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
