# Validation

This page records what Understudy has actually been checked against and the
profile failures that led to the current safeguards. For normal repair use,
start with the [README](../README.md) or
[REPAIR_WALKTHROUGH.md](REPAIR_WALKTHROUGH.md).

## Current coverage

Every conversion is re-parsed and checked frame by frame. All 16 bundled
profiles have also been exercised with the Squawk & Talk firmware in board
simulation, and every speech stream observed from that firmware has been checked
against the phrases the profile converts.

That is structural/control-flow evidence, not an acoustic result.

As of 2026-09-11, **Embryon is the only profile tested on real hardware**. The
ordinary conversion was fitted to a Bally Squawk & Talk AS-2518-61A with a
TMS5220 and compared by ear with the same board running its TMS5200 and original
ROMs. The converted result was reported very close to the baseline, with no
broken or missing phrase.

The optional `--optimize-audio` Embryon result has **not** yet been tested on real
hardware.

| check | coverage |
|---|---|
| output re-parsed and frame kinds compared | every conversion |
| converted ROMs exercised with board firmware in simulation | 16 of 17 profiles |
| firmware-played streams covered by converted phrases | 16 of 17 profiles |
| ordinary conversion listened to on real hardware | Embryon only |
| optimized conversion listened to on real hardware | none |

A profile may contain table entries that the firmware trace did not reach. Those
are recorded separately in its evidence rather than treated as trace-verified.

The profile not covered by the two simulation rows is **Midnight Marauders**,
which is `layout-verified` rather than `board-simulated`. The harness that runs
those checks finds games by their `BY61_SOUNDROM` macro, and this one declares
its sound ROMs by hand inside a plain `SOUNDREGION`, so it is invisible to that
discovery. That is a gap in the harness, not evidence about the game.

## Why a clean boot is not enough

Early work used automatic pointer-table detection followed by a simulated board
boot. Some wrong layouts still looked healthy: one candidate converted only 1.5%
of the speech and the board continued to boot normally.

The bundled profiles therefore use game-specific layouts and require execution
coverage, not just a parse and boot.

## Earlier profile failures

### Embryon

An early profile treated an end bound as a 21st phrase. The bytes parsed as
speech and passed static checks, but conversion rewrote 6800 instructions in the
sound firmware. Board simulation caught it when the converted image stopped
booting.

### Fathom

A profile read two entries beyond its pointer table. One pointed into erased
space and one into 6802 code, changing 31 bytes of executable firmware. The board
still booted because normal commands never reached the damaged code.

This led to stricter device-bound and changed-byte reconciliation checks.

### Flash Gordon

A real pointer address was mistaken for the start of the table when it was
actually entry 14. Five of eight played phrases converted correctly; three were
missed.

This led to the execution-derived coverage check: byte streams emitted by the
board firmware must fall inside phrases the profile converts.

### Rapid Fire

Automatic detection finds plausible speech-like data in Rapid Fire, but tracing
all MPU commands shows the firmware never writes to the TMS speech path and
instead drives the DAC. A speech profile would therefore be meaningless even if
a candidate layout parsed cleanly.

## What `convert-set` establishes

For a supported profile, Understudy requires an exact hash match on the relevant
devices and then checks the known layout, phrase termination, frame structure,
device boundaries, changed-byte reconciliation, and firmware-trace coverage.

Those checks are designed to prevent a plausible-looking but structurally wrong
ROM. They do not replace listening on real hardware.

## Embryon hardware result

The real-board comparison used three configurations on the same board:

1. TMS5200 with original ROMs;
2. TMS5220 with original ROMs;
3. TMS5220 with the ordinary Understudy conversion.

The third was reported very close to the first. The 17 frames (2.0%) raised to
the TMS5220 pitch floor were not noticed by the listener. The TMS5220 setup was
reported slightly louder; the cause is not established.

If you test another title, replacement chip, or the optimized Embryon ROMs, use
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) to record the result.
