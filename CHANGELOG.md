# Changelog

All notable changes to this project are documented here. Dates are ISO 8601.
Versions follow [Semantic Versioning](https://semver.org/); the project is
pre-1.0, and **1.0 is gated on a real-machine validation** rather than on
features.

## [Unreleased]

### Added

- **Midnight Marauders (`mdntmrdr`), the seventeenth profile** — and the first
  that is not a pinball. A Bally Midway *gun game* from 1984 on the same
  AS-2518-61 Squawk & Talk board, 20 phrases and 21 seconds of speech. It was
  missing because the survey that enumerates this platform finds games by their
  `BY61_SOUNDROM` macro, and this one declares its sound ROMs by hand; it has
  therefore never appeared in any Squawk & Talk count, including ours.
- Two things about it are unlike every other profile. Its pointer table lives in
  a device that holds **no speech at all**, and it uses **both** end-of-phrase
  conventions — 17 phrases drop their final ROM byte, 3 transmit it — where
  every other traced set uses one. Phrase 19 is also genuinely unterminated on
  the stream the chip receives: the FIFO runs dry rather than hitting a stop
  frame. All three are recorded in the profile's evidence.
- It clamps **7.5 % of its frames** at the TMS5220 pitch floor, the highest in
  the library and nearly four times Embryon's, so expect it to sound more
  obviously raised in pitch than the pinballs do.
- **Optimization data for sixteen of the seventeen profiles.** The measurement
  behind `--optimize-audio` has been run across the library by the identical
  process — same renderer, metric, eligibility gate, two-pass local K search and
  strict-improvement rule, with no per-game tuning and no game-specific runtime
  code. Embryon was regenerated first and reproduced its shipped result exactly
  (475/456/19, all 456 overrides identical), which is what licensed running the
  rest. Across the library: 10,580 eligible frames, 10,184 improved (96.3 %),
  33,075 K indexes moved. `bigbat` has no data because no ROM set was available.
- **Read the coverage table before using it on a new game.** Every game's mean
  whole-phrase score improves, but 70 of 461 phrases came out worse, and unlike
  Embryon's 0.67 dB the worst is Elektra at **+12.13 dB**. `fball_ii` is the only
  title with no regression at all. The regressions are deterministic and track
  phrase length rather than pitch clamping or correction density; the per-game
  figures, the itemised regressions and the analysis are in
  [AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md) and
  `docs/optimization_coverage.json`. Nothing here has been heard on hardware.
- **`--optimize-audio`, an optional conversion mode.** The default conversion
  is unchanged and remains the deterministic nearest-table mapping; this flag
  additionally applies per-frame K-coefficient refinements that were measured,
  for that game, by rendering candidate frames and comparing them against the
  original chip. In the experiment behind it, **39 of 40 representative Embryon
  frames improved** and one found nothing better. Measured as whole phrases
  instead of frames, 18 of Embryon's 20 improved and 2 came out slightly worse.
  That is a measurement on one game, not a promise that any given phrase or game
  sounds better, and it does nothing about the pitch floor — see
  [AUDIO_OPTIMIZATION.md](docs/AUDIO_OPTIMIZATION.md).
- Optimisation data exists only for games it has been measured on, and
  `--optimize-audio` says so plainly rather than silently converting without it.
- Manifests now always carry an `audio_optimization` section — set schema 4,
  manual schema 2 — stating whether the pass ran, and, when it did, every frame
  it touched with the scores that justified each move.

### Validated on silicon

- **Embryon has been played on a real board.** On 2026-09-11 a converted set was
  fitted to a Bally Squawk & Talk AS-2518-61A with a TMS5220 and listened to —
  the first time any conversion from this tool has been heard. Three
  configurations were compared on the same board, one variable at a time: a
  TMS5200 with the original ROMs, a TMS5220 with the original ROMs, and a
  TMS5220 with the converted ones. The last was reported as very close to the
  first, with no phrase broken or missing. The profile moves to
  `silicon-verified`; the other fifteen remain `board-simulated` and nothing
  about this transfers to them.
- The 17 frames clamped at the TMS5220 pitch floor were **not** noticed, where
  the analysis predicted they would sound audibly higher. The ceiling itself is
  unchanged — it is a property of the destination coefficient table — but its
  audible cost at 2% of frames appears smaller than the emulator measurements
  implied.
- **Open question:** the TMS5220 was reported as slightly louder than the
  TMS5200. Not attributable to conversion — the two parts' energy tables are
  byte-identical and the energy field is never rewritten. Recorded, unexplained.

### Changed

- **Point at a folder or a zip.** `convert-set` and `identify` now accept a
  directory or a `.zip` as well as a list of files, and ignore anything inside
  that is not a speech ROM. ROM sets arrive as zips far more often than as tidy
  file lists, and "point at the folder" is what someone with a machine open
  actually wants to type. A file the user *names* which fits no socket is still
  an error; one merely *found* while expanding a folder is not.
- **`identify` now prints the shortest command that works.** It used to suggest
  `--game X --target tsp5220c -o out/`, every part of which is a default, which
  taught everyone that four flags were required.

### Removed

- **Packaging.** `pyproject.toml` and `MANIFEST.in` are gone, along with the
  wheel and sdist CI jobs. The distribution is the repository: clone or download
  it and run `understudy.py`. Nothing to install, and `pip install understudy`
  never referred to this project in the first place — that name belongs to an
  unrelated package on PyPI.
- `RELEASE_READINESS.md`, an internal pre-release memo describing a packaged
  0.3.0 and a private repository. Both statements had stopped being true.

### Security

- **A custom profile can no longer write outside `--output`.** `socket` and
  `type` become part of an output filename, and were only checked for being
  non-empty — so a profile with a socket of `U4/../../x` put a burn image
  wherever it liked, and `UNDERSTUDY_PROFILE_DIR` exists precisely so profiles
  from elsewhere can be tried. They are now restricted to safe identifiers, and
  the writer separately refuses any name that is not a single path component
  resolving inside the output directory. Two layers, because one guard on a path
  is never enough.

### Fixed

- **Partially overlapping phrases are refused.** A `start_end_pairs` table could
  declare extents that share only part of a range. `patch_rom` converts each
  phrase from the original bytes, so the second write landed on the first
  phrase's tail with data converted at a different bit alignment — and the
  result still re-parsed as a clean terminated phrase, because the per-phrase
  check runs before the second write. Extents must now be identical aliases or
  disjoint, checked both where the layout is read and in `patch_rom` itself. No
  bundled profile was affected.
- **A TMS5220C/TSP5220C target now requires evidence about the firmware.** Those
  parts read the `0x00`/`0x20` opcode as SET RATE where a TMS5200 ignores it,
  which is a property of the board, not of the speech data. Only one profile
  recorded what its firmware sends, and nothing consulted it. All sixteen now
  carry the measurement — every one issues only `0x60` SPEAK EXTERNAL — and a
  C-family conversion without it is refused. `chip_commands_observed` is also
  validated rather than coerced: `list("0x60")` is `["0","x","6","0"]`, so a
  bare string would have become four bogus commands. This says nothing about
  electrical substitution, which remains unverified.
- **`identify` no longer calls a set ready that `convert-set` will refuse.** It
  reported "complete" when every SPEECH device matched, but conversion
  authenticates and emits every device — including one holding no speech, which
  is still burned. A set could be identified, be handed a convert-set command,
  and have it fail on the next line. `Match.complete` keeps its meaning (the
  speech ROMs identify the set); `Match.burnable` and `Match.unsupplied` are new
  and are what the command line now reports.
- **The reconciliation line stated an equality that could be false.** It printed
  physical-device changed bytes as equal to the CPU-image total. A mirrored
  device answers at two addresses, so a layout reaching one physical byte
  through both windows changes two image bytes and one device byte. Both counts
  are now reported, and the image is reconciled against the window total, which
  is the pair that genuinely matches.
- **A device merged from both mirror windows is no longer described as "taken
  from the mirror half".** `source_window` distinguishes lower, mirror, merged
  and unchanged.

### Changed

- **`speech_coverage_percent` measures something different, and the manifest
  schema is now 3.** It unioned DECLARED phrase extents against the CPU window
  and the summary printed it as "X% of it is speech". A declared extent runs to
  the next pointer or to the pointer table, which can be far past where the
  speech stops: one set declares a 10 KB extent for a phrase whose speech ends
  after 207 bytes, and its device read as 100% speech when a quarter of it is
  something else. It now counts the bytes each phrase actually consumes through
  its stop frame, mapped through the mirror to physical device offsets, and the
  summary says "X% converted". A fully converted 2 KB part in a 4 KB window
  reads ~100% where it used to read ~50%.


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
