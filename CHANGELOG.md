# Changelog

All notable changes to this project are documented here. Dates are ISO 8601.
Versions follow [Semantic Versioning](https://semver.org/); the project is
pre-1.0, and **1.0 is gated on a real-machine validation** rather than on
features.

## [Unreleased]

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
