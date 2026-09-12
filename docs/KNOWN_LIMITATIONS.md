# Known limitations

## The TMS5220 pitch floor is higher

A TMS5220 cannot produce a fundamental below about 50.3 Hz; a TMS5200 reaches
about 37.9 Hz. Frames below the replacement part's floor are clamped upward and
will sound higher than the original.

Nine candidate workarounds were rendered and measured; none recovered the lower
range. See [PITCH_CEILING.md](PITCH_CEILING.md).

## The ROM does not carry a conversion marker

There is no spare header or version field in a TMS52xx speech stream where
Understudy can mark a ROM as converted. Running the conversion twice would move
the indexes again and degrade the result.

For supported games, `convert-set` prevents this by matching every input device
against the profile's SHA-256 hashes. An already converted set no longer matches
and is refused.

The manual `convert` path has no profile and cannot provide that protection.
Keep the original dumps and the generated manifest.

## Most validation is structural, not acoustic

Every conversion is re-parsed and checked for frame structure and length. The 16
bundled profiles have also been exercised with the Squawk & Talk firmware in
board simulation, and the streams observed from that firmware are checked
against the phrases each profile converts.

That does not mean the speech has been heard. **Embryon is the only profile
validated on real hardware.** The other 15 remain `board-simulated`.

The Embryon hardware test used the ordinary conversion. The optional
`--optimize-audio` result has not yet been tested on real hardware.

See [VALIDATION.md](VALIDATION.md) for the exact coverage.

## Optimizer measurements are game-specific

`--optimize-audio` applies pre-measured K-index corrections rather than running a
scorer during conversion. Only Embryon currently ships optimization data.

The Embryon full-corpus run found better local frame scores for 456 of 475
eligible voiced frames. When the finished phrases were scored as wholes, 18 of
20 improved and 2 were slightly worse. No optimized set has yet been heard on a
real board.

The optimizer therefore remains opt-in, and Understudy refuses the flag on a
profile with no matching measurement data. See
[AUDIO_OPTIMIZATION.md](AUDIO_OPTIMIZATION.md).

## Custom inputs step outside the bundled validation

The manifests record the target part, coefficient-table hashes, profile version,
and conversion options. The bundled profile evidence only describes the
combinations that were actually tested.

Supplying custom `--source-tables` or `--target-tables`, using the manual
`convert` path, changing a layout, or forcing an otherwise refused condition
means you are outside that evidence. The structural checks still run, but there
is no claim that the resulting ROM matches a board-simulated profile.

## A layout can be valid-looking and still incomplete

Understudy catches many bad layouts: unterminated phrases, speech leaving the
expected device, unexpected changed bytes, and other structural failures.

It cannot infer that a layout simply contains too few otherwise-valid phrases.
That happened during development of the Flash Gordon profile: the chosen pointer
address was real but started partway through the table, so five of eight played
phrases converted cleanly while three were missed.

Bundled profiles address this with an external coverage check: run the board
firmware, capture the streams it sends to the TMS, and require every observed
stream to fall inside a converted phrase. Entries not reached by that trace are
recorded separately in the profile evidence.

See [VALIDATION.md](VALIDATION.md) and the profile procedure in
[SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md).

## Scope is one board and one chip family

Understudy targets Bally Squawk & Talk speech data converted from the TMS5200 to
the TMS5220 family. TMS5220, TMS5220C and TSP5220C use the same LPC tables for
this purpose; see [CHIPS.md](CHIPS.md).

The TMS5100 and TMS5110 are not supported. They use a different frame layout and
a 5-bit pitch field.

Other TMS52xx hardware would need its own layout work and likely its own profile
schema.

## No checksum handling

Understudy does not update a board-specific ROM checksum. The bundled Squawk &
Talk workflow has not required one, but hardware with firmware-enforced checksums
would need additional support.

## Perceptual evidence is still limited

The project has one real-board Embryon comparison and a small amount of blinded
listening evidence from development work. That is useful engineering feedback,
not a controlled perceptual study. Objective rendering scores are also proxies
for similarity, not a guarantee of what a listener will prefer.
