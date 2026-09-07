# Known limitations

## The pitch floor cannot be worked around

A TMS5220 cannot produce a fundamental below about 50.3 Hz; a TMS5200 reaches
about 37.9 Hz. Frames below the substitute part's floor are clamped upward and
will sound higher than the original. Nine candidate workarounds were built and
measured; none recovered the range. See [PITCH_CEILING.md](PITCH_CEILING.md).

## A converted ROM is not distinguishable from an original

There is no marker in the output saying it has been converted — there is nowhere
to put one. A TMS52xx stream has no header, no version field and no spare bits,
and adding any would change its length and break the in-place property the whole
approach rests on.

The consequence is operational: converting an already-converted ROM moves every
index a second time and quietly degrades the speech, and neither the tool nor
the file can warn you. The manifest records the input's SHA-256 precisely so you
can tell which image you have. Keep the original.

## Emulator-derived, not silicon-confirmed

The pitch ceiling and every measurement behind it were derived against PinMAME's
TMS52xx emulation — the tables in `src/sound/tms5220r.c`, rendered by the
synthesiser in `src/sound/tms5220.c`. No physical TMS5200 or TMS5220 has been
measured for this project.

The ceiling follows from the coefficient table and the counter comparison, which
are documented chip behaviour, so it should transfer. Finer claims — how one
conversion strategy compares with another — depend on the emulator's
interpolation and lattice arithmetic being faithful, which is a stronger
assumption.

So an output of this tool is **structurally checked**: the converter re-parses
what it wrote and confirms every frame kept its kind and the stream its length.
That is not an acoustic check, and it is not an emulator run — the tool does not
invoke one.

For each of the fifteen bundled profiles, the converted devices were
additionally loaded into a simulation of the Squawk & Talk board, which booted
and drove them, issuing the same speech commands as the originals. That
exercises the board's firmware and control flow against the converted data, and
it is what the `board-simulated` profile status means. **It renders no audio and
nobody has heard the result.**

What that means for your own output is narrower than it may look. Hash
identification fixes the *inputs*: every device is matched by SHA-256, so a
`convert-set` run is working on the same bytes the simulation did. The output
also depends on the target part, the coefficient tables, any override you pass,
and the version of this tool. Run the same release against the same set with the
same target and the bundled tables and no overrides, and the result is the one
that was simulated. Change the target, supply `--source-tables` or
`--target-tables`, or pass `--allow-unterminated`, and it is not — the manifest
records each of those precisely so the difference is visible rather than
assumed.

If you used the manual `convert` path, on an unsupported revision or a layout of
your own, none of this applies: it has had no simulation at all. Either way,
calling the result a "working ROM" would require hardware testing nobody has
done.

## Nearest-value conversion is a baseline, not an optimum

`convert` maps each parameter independently to the closest entry in the
destination table. Choosing K indexes jointly per frame, scored by rendering
rather than by table distance, did better in our own private experiments,
because the reflection coefficients interact. **That comparison is not
reproducible from this repository** -- no scorer, harness or measurement is
included -- so it is an assertion about work done elsewhere and should be read
as one.

That work is not in this repository. Scoring by rendering requires a
synthesiser, our synthesiser is PinMAME, and shipping a scorer whose licence
position is unresolved would push that ambiguity onto every user. If you want to
pursue it, the architecture to aim for is a pluggable scorer with the renderer
supplied by you.

## Table discovery is manual

You supply `--table-offset` and `--phrases`. Automatic candidate-table discovery
is feasible and unimplemented. See
[SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md).

## A layout that is too SMALL cannot be detected from the ROM

Understudy refuses a great many wrong layouts: a phrase that does not terminate,
one that converts nothing, one whose speech runs off the end of its device, one
whose bytes leave the devices marked as holding speech, one that overlaps the
pointer table. Every one of those is a phrase that looks wrong.

It cannot detect a layout whose phrases all look *right* and of which there are
simply too few. If a profile declares 20 phrases of a 24-entry table, the 20 it
declares convert perfectly, terminate properly, stay inside their devices and
reconcile byte for byte — while four phrases are left encoded for the TMS5200,
and the machine plays them through the wrong tables. Nothing about the twenty
says anything about the four.

That is not hypothetical. The Flash Gordon profile shipped this way: its table
address was real but sat fourteen entries into the table, so it found 5 of 8
phrases and converted 372 of 677 frames. Everything it did convert was correct.

There is no check inside this tool for that, because the information is not in
the ROM: the number of phrases IS the layout, and it is an input. The check that
finds it is external — run the board's firmware, capture what it sends the TMS,
and require every played stream to fall inside a converted phrase. Step 6 of
"Working out the layout for your ROM" in [SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md)
describes it, every bundled profile has cleared it, and each records in
`evidence.traced_phrase_starts` the addresses it was checked against.

The residue that even that leaves is stated per profile in
`evidence.not_established_by_the_trace`: table entries no command reached during
the sweep, which rest on the pointer table alone.

## Scope is one board and one chip family

Squawk & Talk, TMS5200 to the TMS5220 family — which for the purposes of the
converted data means the TMS5220, TMS5220C and TSP5220C alike, since their LPC
tables are identical. See [CHIPS.md](CHIPS.md), including what that claim does
not cover.

The **TMS5100 and TMS5110 are not handled**. They use a 5-bit pitch field and a
different frame layout, and the converter refuses tables whose field widths are
not the 52xx grammar rather than producing plausible nonsense.

Only **one board** is understood: the Bally Squawk & Talk. Other TMS52xx-bearing
hardware would need its own layout work, and probably its own profile schema
fields.

## No checksum handling

If your board's firmware validates the sound ROM, this tool does not update any
checksum. We have not established whether Squawk & Talk firmware does so.

## Single-listener perceptual evidence

A blinded listening test on the conversion strategies was run with **one
listener** over eight of ten prepared items. It is preliminary, it is not a
controlled study, and no perceptual claim in this repository rests on it.
