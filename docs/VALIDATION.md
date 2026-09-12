# Validation and why profiles are conservative

This page records the evidence behind Understudy's game profiles and the failures
that shaped the checks. If you are fixing a machine, you do not need any of this
to use the tool; start with the [README](../README.md) or the
[repair walkthrough](REPAIR_WALKTHROUGH.md).

## What has actually been tested

Every conversion is re-parsed and checked frame by frame. All 16 bundled
profiles have also been run with the Squawk & Talk firmware in board simulation,
and every speech stream observed from that firmware has been checked against the
phrases the profile converts.

That is structural evidence, not an acoustic test. As of 2026-09-11, **Embryon
is the only profile tested on real hardware**. A converted set was fitted to a
Bally Squawk & Talk AS-2518-61A with a TMS5220 and compared by ear with the same
board running a TMS5200 and its original ROMs. The converted result was reported
very close to the baseline, with no broken or missing phrase. No electrical or
acoustic measurements were made.

| check | coverage |
|---|---|
| output re-parsed and frame kinds compared | every conversion |
| converted ROMs booted with board firmware in simulation | all 16 profiles |
| firmware-played streams shown to fall inside converted phrases | all 16 profiles |
| listened to on real hardware | Embryon only |

A profile can also contain table entries that the firmware trace did not reach.
Those are recorded in `evidence.not_established_by_the_trace`; the trace should
not be read as evidence for commands it never exercised.

## Why a successful boot is not enough

Early work tried automatic pointer-table detection followed by a simulated board
boot. It looked promising: 25 sets produced output that drove the board as the
original did. Cross-checking against an independently built frame corpus showed
that only 4 of 12 comparable sets matched exactly. One candidate converted only
1.5% of the speech and still booted.

The lesson was simple: a board can boot while the speech layout is wrong. The
profiles now use game-specific layouts backed by execution traces rather than an
automatically detected table.

## Defects that got through earlier checks

### Embryon

An early profile treated an end bound as a 21st phrase. The bytes parsed as a
valid stream and passed the static checks, but conversion rewrote 6800
instructions in the sound firmware. Running the board firmware against the
converted ROM caught it when the simulated board stopped booting.

### Fathom

A profile read two entries beyond its pointer table. One pointed into erased
space and one into 6802 code. The conversion changed 31 bytes of executable
firmware, yet the simulated board still booted and issued the same speech
commands because its normal command set never reached that code.

This is why profiles now check that speech terminates inside the expected device
and reconcile changed bytes between the assembled image and physical devices.

### Flash Gordon

A real pointer address was mistaken for the start of the table when it was
actually entry 14. The resulting layout found five of eight played phrases and
converted 372 of 677 frames. Everything it converted was valid; the problem was
what it missed.

That failure led to the execution-derived coverage check: the board firmware is
run, the byte streams it sends to the TMS are captured, and every played stream
must fall inside a phrase the profile converts.

### Rapid Fire

Rapid Fire is the clearest demonstration of why speech-only checks can pass the
wrong thing. Automatic detection finds plausible speech-like data and a
conversion can be made that still lets the board boot. But tracing all 256 MPU
commands shows that the firmware writes to the TMS zero times while driving the
DAC heavily. Rapid Fire makes sound, but does not use the speech path.

There is therefore no speech profile to ship for it.

## What a supported profile establishes

For the automatic `convert-set` path, Understudy requires an exact hash match on
the relevant devices. The profile supplies a known layout. Phrases must parse
and terminate according to that profile, converted frames are re-parsed, changed
bytes are reconciled back to the physical devices, and the firmware-played
speech must be covered by the converted phrases.

These checks are intended to catch plausible-but-wrong ROMs. They are not a
claim that the other 15 profiles have been heard on hardware.

## Embryon hardware result

The Embryon test compared three configurations on the same board:

1. TMS5200 with original ROMs — baseline.
2. TMS5220 with original ROMs — replacement chip without conversion.
3. TMS5220 with converted ROMs — Understudy result.

The third configuration was reported very close to the first. The 17 frames
(2.0%) that must be raised to the TMS5220 pitch floor were not noticed by the
listener. The TMS5220 configuration was reported slightly louder; the cause is
not established. The coefficient remapping may alter lattice-filter gain, or
the parts' analog output stages may differ.

If you test another game on a real board, please record it using
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).
