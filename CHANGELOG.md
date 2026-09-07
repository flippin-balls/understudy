# Changelog

All notable changes to this project are documented here. Dates are ISO 8601.
Versions follow [Semantic Versioning](https://semver.org/); the project is
pre-1.0, and **1.0 is gated on a real-machine validation** rather than on
features.

## [Unreleased]

### Added

- **Twelve more sound ROM sets**, taking coverage from 4 to **16 of the 19
  distinct Squawk & Talk sound ROM sets**, and from 17 to **45 of the 49 game
  revisions**, each carrying the addresses the firmware was seen to play
  (`evidence.traced_phrase_starts`) and an explicit statement of which of its
  declared phrases the trace did **not** confirm
  (`evidence.not_established_by_the_trace`): Beat the Clock, Centaur, Eight
  Ball Champ, Eight Ball Deluxe, Big Bat, Spectrum,
  Fireball II, Flash Gordon (French), Medusa, Mr. and Mrs. Pac-Man, Mysterian
  and Vector, alongside the corrected Fathom and Flash Gordon.
- **`entry_form: "start_end_pairs"`** — some tables store both bounds of every
  phrase in a four-byte record rather than listing starts. Read as a list of
  starts, every *end* pointer becomes a phrase too and the invented ones cover
  whatever lies between the real phrases; nothing raises, because every other
  pointer really is a phrase start. Centaur, Medusa, Eight Ball Deluxe,
  Fireball II and Vector are built this way. With this form, stating
  `address_ordered` or `has_end_bound` is refused rather than ignored, because
  a (start, end) record carries both of its own bounds.
- **`silent_phrases`** — a deliberate "say nothing" entry is a run of silence
  frames, which is exactly what a pointer aimed at padding looks like. Silence
  therefore stays refused, and a profile must name the phrases it claims are
  silent. The claim is then checked: a named phrase that carries speech is
  refused, so the field cannot be used to switch the guard off. A phrase that
  parses to a lone stop frame is not silence — it is a phrase that was never
  found — and is refused before this field is consulted.
- **`unterminated_phrases`** — in at least one set the player, not the ROM,
  supplies a phrase's terminator. Same treatment: named, and checked both ways.
  A named phrase that *does* terminate is refused, and any phrase not named
  must still terminate. `patch_rom`'s `allow_unterminated` now accepts a list of
  indexes as well as `True`, so one phrase can be excused without excusing the
  set.

- **A phrase that converts nothing is now refused.** If a phrase's first frame
  is a stop frame it changes not one byte, yet reports as clean and terminated:
  the frame kinds are trivially preserved and the reconciliation only counts
  bytes that changed. Erased space reads as `0xFF`, which *is* a stop frame, so
  this is what a pointer into a gap — or one entry past the end of a table —
  looks like, and it is the shape of the Fathom defect. No threshold is
  involved: a real phrase says something, so its first frame is never the one
  that ends it, and none of the 523 phrases the bundled profiles declare begins
  with one. This guard runs before `silent_phrases` is consulted, so no claim in a
  profile can excuse it.
- **A mirrored device's two windows must agree where they overlap.** Reaching
  some phrases through the lower window and others through the mirror is
  legitimate and is merged. Where a physical offset is reached through *both*,
  the two conversions must want the same byte — two entries naming one phrase
  through each window are harmless, but two phrases at different alignments are
  not: only one conversion could survive into the burned device and the other
  phrase would read as corrupt. The test is on the value each window requires,
  not on which bytes changed, because a conversion may legitimately leave a byte
  unchanged: one side rewriting it while the other leaves it alone is a
  disagreement in which only one side looks like a change.
- **`allow_unterminated` checks its list in both directions.** Naming a phrase
  that does end in a stop frame, or an index that is not a phrase, is refused
  rather than ignored — otherwise the argument would act as a blanket override
  instead of a statement about the bytes in front of it.

- **Criterion 4 now compares total sound output, not just speech commands.**
  Rapid Fire showed why: a conversion that rewrites executed code can still boot
  and still issue an identical set of speech commands while the board's DAC
  writes fall by 62.7%. Equal counts are not equal behaviour either, so the DAC
  is compared as an ordered stream of values — it has nothing to do with
  conversion, so every write to it must survive byte for byte and in order —
  alongside the SPEAK EXTERNAL count and the number of TMS writes. The bytes
  sent to the TMS are deliberately not compared: changing them is what
  conversion is. All 16 bundled profiles pass, each recording its figures in
  `evidence.emulation`.
- **Big Bat**, whose ROMs were believed unobtainable. They were in a second
  archive tree the first search never walked, filed under descriptive names
  ("Big_Bat_Baseball_Sound EPROM U3 06-20-1984.BIN") rather than the driver's
  `u3.bin` — so a hash search of the wrong tree could not find them, and a
  filename search using the driver's names would not have found them either. All three match the driver's SHA-1 exactly. A negative result
  is only as wide as the search behind it.

### Fixed

- **Two shipped profiles were wrong**, both found by checking them against a
  phrase list captured from the running board rather than against another
  static read.

  **Fathom v1** read two entries past the end of its pointer table. Entry 26
  (`$F77D`) is the last phrase's end bound and points at erased `0xFF`, which
  parses as an immediate stop frame. Entry 27 (`$FAD3`) is 6802 code, and
  conversion rewrote 31 bytes of it — in the region reached from the reset
  vector. Every static check passed, and the board simulation booted and issued
  the same eight speech commands, because the 64 commands it issues never reach
  that code. The frame count that appeared to confirm it came from a corpus
  built by static extraction, which had made the same misread. Profile v2 is 26
  phrases with an end bound.

  **Flash Gordon v1** placed the pointer table at `$F326`. That address is real,
  but it is entry 14 of a table starting at `$F30A`, and reading from the middle
  of a table still yields pointers that look like phrases: it found 5 of the 8
  phrases the game plays and converted 372 of 677 frames, leaving the rest to be
  read with the wrong tables. Profile v2 is the full 24-entry table.

- **A mirrored device may now be reached through both of its windows.** A 2 KB
  part answers at two addresses, and a set is free to reach some phrases through
  the lower window and others through the mirror — Eight Ball Deluxe does, and
  the two groups land on different offsets of the same physical device.
  Previously any such layout was refused as "the two mirror halves changed to
  different contents". The halves are now merged byte by byte, and only a
  genuine collision — the same offset converted two different ways — is refused,
  naming the offset.


- **The Embryon profile read one pointer too many.** The table's 21st entry is
  an end bound, not a phrase: it points at six zero bytes followed by 6800
  code. The zeros parsed as silence frames and the parser ran on until a byte
  in the code carried a `0xF` nibble, so conversion rewrote instructions the
  sound board executes — and a simulation of the board, loaded with the
  converted ROMs, stopped booting. Profile v2 corrected the layout: 20 phrases
  with an end bound. Found by running the converted devices through an
  emulation of the board rather than by inspecting them.

### Changed

- **The phrase-coverage guard tests each phrase's START, not its whole extent.**
  An extent is the *declared* bound — the next pointer, or the pointer table —
  and the last phrase in a device is legitimately bounded by a table living in
  the next device. Requiring the whole extent to lie in speech-bearing devices
  refused correct layouts, and marking the table's device as speech-bearing to
  satisfy it was refused in turn because nothing in it changes. What an extent
  must not do is carry converted bytes out of the speech devices entirely, and
  that is now checked directly, against the bytes conversion actually changed.
- The profile status rung `emulator-verified` is now **`board-simulated`**, and
  its definition says what was actually done: the board's own firmware, in
  emulation, boots and drives the converted ROMs — structure and control flow,
  not sound. The old name read as "rendered and sounded right", which nobody
  has established. Embryon is v3 at that status.
- A phrase beginning with a long run of silence frames is now refused, which is
  what a pointer aimed at padding looks like. Across Embryon's 20 real phrases
  every one begins with none; the padding entry began with twelve.

## [0.3.0] — 2026-09-06

The release that makes this usable at a bench rather than at a desk.

### Added

- **Bundled coefficient tables.** The TMS5200 and TMS5220 tables now ship in
  `src/tms52xx/data/`, so a first conversion needs no setup at all. Taken from
  MAME's `tms5110r.hxx` (BSD-3-Clause per its own header, decap-verified
  upstream), with repository, commit, path, SHA-256, licence and copyright
  holders recorded in each file and in `THIRD_PARTY_NOTICES.md`.
- **TMS5220C and TSP5220C as conversion targets.** Their LPC tables are
  decap-verified upstream as exactly matching the TMS5220. The claim is scoped
  to those tables: the parts differ in control behaviour, and `docs/CHIPS.md`
  says how.
- **Game profiles**: a versioned schema of layout facts and device hashes,
  containing no ROM data. Embryon ships as the first.
- **`understudy identify`** — names the game and revision from socket dumps, by
  exact hash, and refuses to guess.
- **`understudy convert-set`** — socket dumps in, burnable device images out.
  Assembles the CPU image, handles mirrored devices, splits the result, names
  the output files after the device to burn them into, and prints a validation
  block before writing.
- **`understudy chips`** and **`understudy profiles`**.
- Manifest **schema v2**: versioned, with tool version, profile identity, chip
  and table identity with hashes, per-device input and output hashes, layout
  facts, per-phrase rows, warnings and overrides.
- `docs/CHIPS.md`, `docs/HARDWARE_VALIDATION.md`,
  `docs/CONTRIBUTING_PROFILES.md`, `CONTRIBUTING.md`, `CITATION.cff`,
  `THIRD_PARTY_NOTICES.md`, `ACKNOWLEDGEMENTS.md`, issue templates.
- Windows and macOS CI, alongside Linux.

### Changed

- `inspect` and `convert` default to the bundled tables; `--source-tables` and
  `--target-tables` still override them.
- `docs/from_pinmame.py` became `tools/extract_tables.py` and now reads MAME as
  well as PinMAME, reporting the source's licence header and SHA-256.
- README restructured: the repair path first, the research second.

### Fixed

- The extractor collected macros before dropping `#if 0` blocks, so a
  definition in a dead branch could shadow the live one.

## [0.2.0] — 2026-09-06

Hardening pass, driven by adversarial review. Not separately released.

### Fixed

- A temporary file named `<output>.tmp` could be the input ROM; converting
  `out.bin.tmp` into `out.bin` destroyed the input. Temporary names now come
  from `mkstemp`.
- `--truncate-last-byte` on a one-byte phrase left nothing to convert and the
  phrase silently vanished from validation and the manifest.
- Malformed table files escaped as tracebacks instead of named errors.
- Duplicate pointers double-counted every total in the manifest.
- Aliases were grouped by their post-truncation extent, so one phrase could be
  converted and counted twice.
- A fixed 100,000-frame cap silently truncated long streams and reported them
  as unterminated.
- The pointer table was assumed to precede the speech; on a Squawk & Talk it
  commonly follows it. With no end bound, the last phrase ran into the table.

### Added

- Fail-closed refusals in the library, not only the CLI.
- Output self-check: converted phrases are re-parsed with the target tables and
  every frame's kind compared.
- 0BSD licence, provenance documentation, prior-art survey.

## [0.1.0] — 2026-09-06

First working conversion: frame codec, nearest-value re-indexing, in-place ROM
patching, `inspect` and `convert`.
