# Release readiness — understudy 0.3.0

**Recommendation: RESEARCH PREVIEW.** Ship it, clearly labelled pre-1.0, with
the "nobody has heard this speech" qualification kept where it is. Do not
present it as a field-validated repair procedure.

Prepared 2026-09-06. Repository private at
`flippin-balls/understudy`; release branch `release-prep-0.3.0` (PR #4).

---

## 1. What changed

| | |
|---|---|
| **Bundled chip tables** | TMS5200 and TMS5220 coefficient tables ship in `src/tms52xx/data/`. No extraction step, no PinMAME clone. |
| **TMS5220C / TSP5220C** | Added as conversion targets, scoped to LPC-table equivalence. |
| **Game profiles** | Versioned schema of layout facts and device hashes. No ROM contents. Embryon is the first. |
| **Two-command path** | `understudy identify` and `understudy convert-set`: socket dumps in, burnable device images out. |
| **Manifest v2** | Versioned, with tool version, profile identity and hash, chip and table identity and hashes, per-device input/output hashes, layout, per-phrase rows, warnings, overrides. |
| **Platform support** | Windows a first-class target, CI on Windows/macOS/Linux × 3.9/3.13. |
| **Community files** | CONTRIBUTING, CHANGELOG, CITATION.cff, THIRD_PARTY_NOTICES, ACKNOWLEDGEMENTS, issue templates, hardware-validation and profile-contribution guides. |
| **Licensing** | Project 0BSD; bundled data BSD-3-Clause with notices shipped inside the package. |

The manual `inspect` / `convert` path is retained for research and unsupported
revisions, and now defaults to the bundled tables.

## 2. Normal user workflow

```
pip install understudy

understudy identify 841-01_4.716 841-02_5.532
understudy convert-set 841-01_4.716 841-02_5.532 --target tsp5220c -o out/
```

The user supplies one file per ROM device. Understudy identifies the set by
hash, assembles the CPU image, converts, splits the result back into
device-sized files, handles mirrored devices, names each output for its socket
**and device type**, and prints a validation block — profile, chips, table
hashes, input hashes, frames, clamped frames, per-device changed bytes, and a
reconciliation line — before writing anything.

Originals are never modified. Every destination is preflighted against every
file the run reads. The set is written as a unit or not at all.

## 3. Supported games

Coverage is counted in **distinct sound ROM sets**. The 49 PinMAME Squawk &
Talk drivers collapse to **19**; the rest are game-ROM revisions sharing sound
ROMs, so one profile serves several.

| profile | status | phrases | revisions |
|---|---|---|---|
| `embryon` | `board-simulated` | 20 | 6 |
| `elektra` | `board-simulated` | 16 | 2 |
| `flashgdn` | `board-simulated` | 5 | 2 |
| `spectrum` | `board-simulated` | 31 | 4 |

**4 of 19 sound ROM sets; 14 of 49 game revisions.** Each cleared all four
acceptance criteria: every phrase terminating, healthy per-device speech
coverage (48–100%), a frame count matching an independently built corpus, and
the board's own firmware booting and driving the converted ROMs identically to
the originals.

An unrecognised set is reported and refused, never converted on a guess.

## 4. Supported replacement chips

| id | markings | basis |
|---|---|---|
| `tms5220` | TMS5220, TMS5220NL | decap-verified table, MAME |
| `tms5220c` | TMS5220C, TMS5220CNL | decap-verified identical to TMS5220 |
| `tsp5220c` | TSP5220C | recorded upstream as another name for the 5220C |

All three produce byte-identical converted data. **Electrical substitution is
not verified by this project** — pinout, supply, clock and output level are the
reader's to check.

One scoped caveat is recorded: the opcode that is a NOP on a TMS5200/5220 is
SET RATE on a 5220C. Embryon's firmware, driven through all 64 commands its MPU
can send, issues only `0x60` SPEAK EXTERNAL — measured, and recorded per profile
rather than assumed for the family.

## 5. Bundled-data licensing and provenance

| | |
|---|---|
| Upstream | MAME, `src/devices/sound/tms5110r.hxx` |
| Commit | `2d5bb2dc20176f765a5fb7f1e59ff4e27a41e34e` |
| Source SHA-256 | `43b114437812a94073804617f78a4fd72e9874292dc9be44660cf7b8904f6480` |
| Licence | BSD-3-Clause (per-file header) |
| Holders | Frank Palazzolo, Couriersud, Jonathan Gevaryahu |
| Verification | decap and PROMOUT, stated upstream per table |

MAME's `COPYING` says individual files may be under less restrictive licences
per their header; that file's header is `// license:BSD-3-Clause`. Notice and
licence text ship **inside the package**, are reachable via `understudy
notices`, and are kept in sync by `tools/sync_notices.py` with a CI check.

Only the numeric tables for two variants were taken. No MAME code. No ROM data
of any kind is included or distributed.

CI clones MAME at the pinned commit and compares the bundled tables against a
fresh extraction, so the provenance claim is checked against upstream rather
than against itself.

## 6. Platform support

Linux, macOS and Windows, Python 3.9 and 3.13, all green. CI additionally
builds a wheel, installs it, and asserts the bundled data and licence notices
survive packaging; and builds the sdist, unpacks it, and runs the full suite
from inside it.

No dependencies. Standard library only.

A standalone executable was considered and not pursued: `pip install` plus a
console script covers the need, and PyInstaller-class tooling would add
significant fragility for a tool whose value is being auditable. Worth
revisiting if technicians report install friction.

## 7. Test coverage

**278 tests.** Standard library only, no fixtures, no network, no ROM data.

Coverage spans the bit codec (including a frame transcribed by hand from the
field spec, independent of the parser's own assumptions), conversion arithmetic
asserted on emitted bytes rather than reports, ROM layout refusals, profile
validation and identification, the workflow's refusals, the publisher's
atomicity and rollback, CLI behaviour end to end, and the table extractor
against a synthetic C fixture.

Every guard added during this work was **mutation-tested**: the fix is reverted
and the suite must fail. Two checks that cannot fire today are documented as
backstops with property tests holding the invariants that keep them unreachable.

## 8. Silicon validation status

**None.** No physical TMS5200, TMS5220, TMS5220C or TSP5220C has been fitted or
measured. Nobody has heard the converted speech.

What has been done, precisely:

| | |
|---|---|
| every conversion | re-parsed with the target tables, every frame's kind compared, changed bytes reconciled — structural |
| Embryon reference set | the board's own firmware, in emulation, boots and drives the **converted** ROMs and issues the same SPEAK EXTERNAL commands as the original — structure and control flow, **not sound** |
| any conversion, heard | never |
| any conversion, on hardware | never |

That middle row is not decoration. It is what caught the one real defect in
this release (§10), which every static check had passed.

## 8a. Corpus sweep — how far this was actually tested

Every Squawk & Talk sound ROM set obtainable here, **46 of the 49 PinMAME
knows**, each file hash-verified against its driver record. Each was put through
automatic layout detection, conversion, and a boot of the board's own firmware
against the converted devices.

| | |
|---|---|
| sets with complete sound ROMs | 46 of 49 |
| converted and drove the board identically to the original | 25 |
| of the 12 with an independent frame corpus, matched it exactly | **4** |
| worst false pass | one set converted **1.5%** of its speech and still behaved normally |

The 25 figure is the misleading one. Booting proves the ROM is not corrupt; it
does not prove the layout found the speech. `elektra`, `embryon`, `flashgdn` and
`spectrum` matched an independently built corpus exactly — including a
1478-frame set — which says the **conversion** is sound where the layout is
right. `eballchp` converted 42 frames where the corpus has 550.

Two conclusions, both acted on:

1. **The bottleneck is layout discovery, not conversion.** Profiles stay
   hand-verified and few, and automatic detection is not used to ship one.
2. **Coverage is now reported.** `convert-set` prints what fraction of each
   speech device the layout reached, and calls out anything under 20%. Correct
   layouts in the sweep ran 33–70%; the false pass ran 1.5%. Reported rather
   than gated — 24.3% was wrong and 32.7% was right, so no threshold is safe.

The harness is not in the repository: it depends on a private research toolkit
and on ROM images. Its findings are.

## 9. Known limitations

- The TMS5220 family cannot reach the TMS5200's lowest pitches. Frames below
  the floor are raised: 17 of 850 (2.0%) on Embryon. Nine workarounds were
  tried and none worked; that work is not reproducible from this repository and
  is labelled as such.
- Nearest-value coefficient mapping is an auditable baseline, not a perceptual
  optimum.
- One game profile, and a corpus sweep (§8a) showing that automatically
  detected layouts are wrong often enough that they must not be shipped.
- ROM checksum behaviour on Squawk & Talk is **not established**. If a board
  validates these ROMs, Understudy does not update any checksum.
- No layout discovery: an unsupported revision needs the manual path.
- The TMS5100/5110 are not handled and are refused rather than mis-converted.

## 10. The defect that matters most

The Embryon profile shipped briefly reading one pointer too many. The table's
21st entry is an **end bound**, not a phrase: it points at six zero bytes
followed by `8E 00 7F` / `BD FA 5F` — 6800 code. The zeros parsed as silence
frames, the parser ran into the code until a byte happened to carry a `0xF`
nibble, and conversion rewrote executable instructions.

It parsed. It terminated in a stop frame. It changed nothing outside its own
declared extent. Its frame kinds survived conversion. **Every check passed it.**

Booting the board's firmware against the converted ROMs did not — illegal
opcode at `$F9E9`. Tracing the original firmware confirms 270 distinct
addresses are executed in that region.

Fixed (profile v2, 20 phrases with an end bound), guarded (a phrase beginning
with a long run of silence frames is refused; Embryon's 20 real phrases begin
with none, the padding entry with twelve), and written up in
`docs/SQUAWK_AND_TALK.md` because it is what the next person working out a
layout will hit.

## 11. Community and contribution readiness

README structured for the technician first and the researcher second. Guides
for hardware validation and for contributing a profile without sending ROM
data, three issue templates, a contribution guide stating the house rules
(fail closed; every guard needs a test that fails without it; do not claim more
than you checked), and acknowledgements crediting the people who decapped the
chips.

`UNDERSTUDY_PROFILE_DIR` lets a contributor test a profile before submitting it.

## 12. Review rounds

Nine adversarial Codex reviews, each briefed to find ways to corrupt a ROM,
lose an input, use the wrong profile or table, or misrepresent evidence.

| round | outcome |
|---|---|
| 1 | **BLOCKER** — `--force` overwrote an input dump with the manifest. Plus 7 findings. |
| 2 | **BLOCKER** — `0xFF` fill parses as a stop frame; phrases pointing into unmapped space silently dropped. Plus 5. |
| 3 | **BLOCKER** — the publisher's predictable `.replaced` backup name deleted a user file. Plus 6. |
| 4 | **BLOCKER** — "input" meant only ROM dumps, so a custom table or profile could be overwritten. Plus 3. |
| 5 | No blocker. sdist incomplete; manifest did not identify the profile by content; `inspect` accepted half a layout. |
| 6 | No blocker. Ship decision confirmed. |
| 7 | **BLOCKER** — `emulator-verified` claimed an acoustic result never established. |
| 8 | **BLOCKER** — rename half-propagated; two claims stronger than the evidence. |
| 9 | **Ready.** No blocker; no claim stronger than its evidence. |

Every material finding was independently reproduced before being fixed, and
carries a regression test. Review does not prove correctness — round 2's
blocker existed through round 1's clean bill, and the Embryon defect was found
by emulation after nine rounds of code review had passed it.

## 13. Unresolved blockers

**None for a research preview.**

## 14. What 1.0 requires

1. A converted set from a released build, fitted to an identified Squawk & Talk
   board with a TMS5220-family part, recorded per
   `docs/HARDWARE_VALIDATION.md`.
2. Electrical compatibility checked against the actual board and part, not
   inferred from table equivalence.
3. The ROM checksum question settled: either the board does not validate these
   ROMs, or Understudy updates the checksum and that is tested.
4. Phrase-by-phrase comparison against an original-TMS5200 baseline, with only
   the quantified pitch-floor difference remaining.
5. Embryon moved to `silicon-verified` on the strength of that report; any
   failure understood and fixed.
6. The exact release artifact still passing every CI check.

More profiles and a better mapper are welcome afterwards. They are not
prerequisites for a truthful 1.0 scoped to the validated Embryon workflow.
