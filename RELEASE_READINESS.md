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
| **Game profiles** | Versioned schema of layout facts and device hashes. No ROM contents. Sixteen of the nineteen distinct sound ROM sets, covering 45 of 49 game revisions. |
| **Layout forms** | Three facts a table can carry that could not previously be stated: `entry_form=start_end_pairs` (both bounds per phrase in a 4-byte record), `silent_phrases` (a deliberate "say nothing" entry), and `unterminated_phrases` (the player, not the ROM, supplies the terminator). Each is a checked claim, not a switch. |
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

| profile | status | phrases | frames | revisions |
|---|---|---|---|---|
| `beatclck` | `board-simulated` | 62 | 1695 | 2 |
| `centaur` | `board-simulated` | 37 | 1759 | 3 |
| `eballchp` | `board-simulated` | 62 | 1485 | 1 |
| `eballdlx` | `board-simulated` | 42 | 1448 | 6 |
| `elektra` | `board-simulated` | 16 | 1148 | 2 |
| `embryon` | `board-simulated` | 20 | 850 | 6 |
| `fathom` | `board-simulated` | 26 | 1182 | 3 |
| `fball_ii` | `board-simulated` | 16 | 721 | 2 |
| `flashgdf` | `board-simulated` | 24 | 663 | 2 |
| `flashgdn` | `board-simulated` | 24 | 677 | 2 |
| `m_mpac` | `board-simulated` | 26 | 721 | 3 |
| `medusa` | `board-simulated` | 27 | 1567 | 3 |
| `mysteria` | `board-simulated` | 36 | 1392 | 1 |
| `spectrum` | `board-simulated` | 31 | 1478 | 4 |
| `vector` | `board-simulated` | 50 | 2287 | 4 |
| `bigbat` | `board-simulated` | 24 | 1012 | 1 |

**16 of 19 sound ROM sets; 45 of 49 game revisions.** Each cleared all four
acceptance criteria: every phrase either terminating in a stop frame or
declared and checked as one the player terminates instead (one phrase of
`m_mpac`, and nothing else in the sixteen), healthy per-device speech coverage,
**every stream the firmware plays falling inside a converted phrase** — checked
against a phrase list captured from the running board, not against another
static read of the ROM — and the board's own firmware booting and driving the
converted ROMs identically to the originals — compared on total writes to the
sound hardware, not only on speech commands, because a set can issue identical
speech commands while its other sound output collapses (§8b).

That third criterion is stated as coverage of what was played, deliberately. It
is not a claim that every declared phrase was independently confirmed; eight of
the sixteen have entries no command reached, and the next section gives the
numbers.

### What the third criterion does and does not establish

Precisely: **every stream the firmware played is inside a phrase the profile
converts.** The firmware is driven through every command its MPU can send, the
byte stream it feeds the TMS is captured, each stream is located back in the
ROM and trimmed at its own stop frame, and the result must fall inside a
converted phrase. That is what rules out a layout which misses speech, and it
is what caught both defects below.

It does **not** confirm every phrase a profile declares. Eight of the sixteen
sets have table entries no command reached in that sweep:

| profile | distinct phrases declared | confirmed by the trace | resting on the table alone |
|---|---|---|---|
| `beatclck` | 60 | 48 | 12 |
| `eballdlx` | 42 | 36 | 6 |
| `eballchp` | 38 | 33 | 5 |
| `flashgdf` | 10 | 8 | 2 |
| `fball_ii` | 13 | 12 | 1 |
| `flashgdn` | 9 | 8 | 1 |
| `m_mpac` | 26 | 25 | 1 |
| `medusa` | 27 | 26 | 1 |
| the other eight | — | all | 0 |

For those entries the evidence is the pointer table — the same kind of evidence
that was wrong in Fathom v1. They are converted because they are entries in a
table whose every other entry the trace confirms, and each profile says so in
`evidence.not_established_by_the_trace`. Nothing here should be read as those
phrases having been independently verified.

Each profile also carries `evidence.traced_phrase_starts`, the addresses the
firmware actually played, so a reader holding the same dumps can re-derive the
list and check it rather than taking this document's word for it. Compare in
device offsets, not CPU addresses: a 2 KB part answers at two.

The third criterion changed during this work, and that is the substantive
result. It used to be a frame count from a separately built corpus. That corpus
was produced by static extraction — the same kind of read a profile does — so
where a profile misread a table, the corpus misread it the same way and
confirmed it. It is now a phrase list derived from **execution**: the board's
own firmware is run, the byte stream it sends the TMS is captured, and those
bytes are located back in the ROM. Every stream the firmware plays must fall
inside a phrase the profile converts.

Re-checking the already-shipped profiles that way found two of the five wrong:

| profile | was | defect |
|---|---|---|
| `fathom` v1 | 28 phrases | Two entries past the end of the table. One aimed at erased 0xFF (parses as an immediate stop frame); one aimed at 6802 code, and conversion rewrote 31 bytes of firmware in the region reached from the reset vector. The board simulation booted and issued identical speech commands, because the commands it issues never reach that code. Its frame count matched the static corpus, which had made the same misread. |
| `flashgdn` v1 | table `$F326`, 5 phrases | `$F326` is entry 14 of a table that starts at `$F30A`. Reading from the middle of a table still yields plausible pointers: it found 5 of 8 phrases and converted 372 of 677 frames, leaving the rest to be read with the wrong tables. |

Both are corrected. Every other profile accounts for every stream its firmware
played — subject to the limits stated above.

### The three sets not covered

These are accounted for, not merely absent:

| set | drivers | why |
|---|---|---|
| `rapidfir` | 2 | Only the firmware ROM is fitted (`U5`, `BY61_SOUNDROMxxx0`); the three speech sockets are empty. Across all 256 commands the MPU can send it makes **zero** writes to the TMS while writing the DAC 128,144 times. Its ROM does carry the standard TMS byte-write routine at `$F365` — checked rather than assumed — and no direct call to it appears anywhere: no `JSR`, no `JMP`, no literal occurrence of its address. That is an observation, **not** a proof of unreachability; the firmware dispatches through a computed jump, and a target can be constructed without its address appearing literally. The exclusion does not rest on it. It rests on criterion 3: the trace yields no streams, so there is nothing for a phrase list to be checked against, and the layout the auto-detector proposes is executed code (§8b). |
| `cosflash` | 1 | Same single-socket arrangement, and no dump on hand to confirm it. |
| `blackbl2` | 1 | No *identifiable* dump on hand — the PinMAME driver carries no CRC or SHA-1 for its sound ROMs, so a search can only ask whether the expected filenames are present, and a renamed dump sitting in the collection could not be ruled out. |

"No dump on hand" was checked rather than assumed, and the checking is worth
recording because it moved a set off this list. The first search covered the
1,141 archives in one tree, by SHA-1 against every hash the drivers record and —
for `blackbl2`, whose driver records no hash at all, so a hash search could never
find it — by filename too. That search reported three sets missing.

It was searching the wrong place for one of them. Widening to every archive on
the machine found all three of Big Bat's sound ROMs in a separate `files/` tree,
under descriptive names ("Big_Bat_Baseball_Sound EPROM U3 06-20-1984.BIN")
rather than the driver's `u3.bin`. A hash search of the wrong tree could not
find them, and a filename search using the driver's names would not have found
them either. All three match
the driver's SHA-1 exactly. Big Bat is now covered.

`cosflash` still produces no hash match anywhere, and `blackbl2`'s expected
filenames appear in no archive — though with no hash in its driver, that search
cannot exclude a renamed dump. The lesson is the obvious one: a negative result
is only as wide as the search that produced it, and this one was too narrow.

The remaining two are an acquisition problem before they are an engineering one. A
dump does not by itself make a seventeenth set: it would still need its layout
worked out, a trace captured, a profile written and the whole acceptance bar
cleared, which is the same work every set here took. What a dump changes is that
the work becomes possible. For `blackbl2` there is an extra step — with no hash
in the driver, the dump would have to be authenticated some other way, most
naturally by the traced phrase list criterion 3 already requires.

`rapidfir` is the reason coverage stops at 16 rather than 17. It was expected to
be convertible and is not.

Be exact about the strength of that. What is established: no speech ROM is
fitted; across every command the MPU can send, the firmware never writes to the
TMS; no traced stream exists; and the only layout automatic detection proposes
is executed code.

What is **not** established, and is not claimed: that the set can contain no
speech. Its firmware does carry the standard TMS byte-write routine, no direct
call to it appears in the ROM, and that is as far as the analysis goes — the
firmware dispatches through a computed jump, so a target can be reached without
its address appearing literally, and proving otherwise would need the complete
target set of that jump. Nor is it established that no LPC data could be
embedded in the 4 KB firmware ROM.

The exclusion does not need any of that. Criterion 3 requires an independent
phrase list; there is no stream to build one from; so a profile here could only
ever rest on self-consistency, which this project does not ship. That is the
whole reason, and it is sufficient.

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

**340 tests.** Standard library only, no fixtures, no network, no ROM data.

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
| all 16 bundled profiles | the board's own firmware, in emulation, boots and drives the **converted** ROMs: same SPEAK EXTERNAL commands, same number of TMS writes, and a DAC stream identical value for value and in order — structure and control flow, **not sound** |
| all 16 bundled profiles | every stream the firmware plays, captured and shown to fall inside a converted phrase — coverage, still **not sound**. It does not confirm table entries no command reached; see §3 |
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
does not prove the layout found the speech. `eballchp` converted 42 frames where
the corpus has 550 and still drove the board normally.

Since then the same point has been made twice more, and more sharply: `fathom`
v1 booted identically to the original while rewriting 31 bytes of the firmware's
own code, and the frame corpus **agreed with it**, because that corpus was built
by static extraction and had made the same misread. A static cross-check is only
independent of the layout if it was not derived the same way. The corpus is no
longer used as the third criterion; a traced phrase list is (§3).

Three conclusions, all acted on:

1. **The bottleneck is layout discovery, not conversion.** Profiles stay
   hand-verified and few, and automatic detection is not used to ship one.
2. **The third criterion must come from execution, not from another static
   read.** A phrase list captured from the running board is the only check a
   wrong layout cannot agree with, and it is now what every profile clears.
3. **Coverage is now reported.** `convert-set` prints what fraction of each
   speech device the layout reached, and calls out anything under 20%. Correct
   layouts in the sweep ran 33–70%; the false pass ran 1.5%. Reported rather
   than gated — 24.3% was wrong and 32.7% was right, so no threshold is safe.

The harness is not in the repository: it depends on a private research toolkit
and on ROM images. Its findings are.

## 8b. Rapid Fire: a boot is not a check

Rapid Fire plays no speech under any command the MPU
can send (§3 is precise about what that does and does not establish). Trying to
convert it anyway is the sharpest demonstration in this project of why criterion
4 cannot stand alone.

| | |
|---|---|
| auto-detected layout | table `$F82D`, 8 phrases, every one terminating in a stop frame, confident score |
| Understudy's verdict | refused at 8 and 9 phrases; **accepted at 7** — 69 frames, 111 bytes changed |
| board simulation | **boots**, and issues the same speech commands as the original (both zero) |
| bytes rewritten that the CPU executes | **27** |
| DAC writes, original → converted | 128,144 → 47,760, down 62.7% |

The same detector proposes Fathom's known-wrong `$FA6F`/28 and a table for
Mr. and Mrs. Pac-Man that is nowhere near its real one at `$F20E`. Nothing here
ships on detection, and nothing ships on a boot.

It also sharpened criterion 4. Comparing SPEAK EXTERNAL counts cannot see a set
whose *other* sound output collapsed, and equal counts are not equal behaviour.
The check now compares the DAC as an ORDERED stream of values — conversion has
nothing to do with the DAC, so every write to it must survive byte for byte and
in order — alongside the SPEAK EXTERNAL count and the total number of TMS
writes. The bytes sent to the TMS are deliberately not compared: changing them
is what conversion is. All 16 bundled profiles pass, and each records its own
figures in `evidence.emulation`.

## 9. Known limitations

- The TMS5220 family cannot reach the TMS5200's lowest pitches. Frames below
  the floor are raised: 17 of 850 (2.0%) on Embryon. Nine workarounds were
  tried and none worked; that work is not reproducible from this repository and
  is labelled as such.
- Nearest-value coefficient mapping is an auditable baseline, not a perceptual
  optimum.
- Sixteen sound ROM sets have profiles; three do not, for stated reasons (§3).
  The corpus sweep (§8a) shows automatically detected layouts are wrong often
  enough that they must not be shipped, and none is.
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

Fixed (profile v4, 20 phrases with an end bound), guarded (a phrase beginning
with a long run of silence frames is refused; Embryon's 20 real phrases begin
with none, the padding entry with twelve), and written up in
`docs/SQUAWK_AND_TALK.md` because it is what the next person working out a
layout will hit.

### It happened twice more, and the guard did not catch either

`fathom` v1 read two entries past the end of its table. One aimed at erased
`0xFF`, which parses as an immediate stop frame and so begins with no silence at
all. The other aimed straight at 6802 code whose first byte carries a non-zero
energy nibble — again, no leading silence. The silence guard is aimed at
padding, and neither of these was padding. Conversion rewrote 31 bytes of
firmware in the region reached from the reset vector, the board simulation
booted, and the static frame corpus agreed with it.

`flashgdn` v1 put the table at `$F326`, which is entry 14 of a table starting at
`$F30A`. Every pointer it read was a real phrase pointer. It simply read 5 of
the 8 phrases and converted 372 of 677 frames.

The lesson is not that another static guard was needed. It is that **no static
check distinguishes a plausible wrong layout from a right one**, because a wrong
layout that reads real pointers produces real phrases. The check that separates
them has to come from outside the ROM's own description of itself: run the
firmware, capture what it sends the TMS, and require every played byte to be
converted. That is now criterion 3, and it is what found both of these.

## 11. Community and contribution readiness

README structured for the technician first and the researcher second. Guides
for hardware validation and for contributing a profile without sending ROM
data, three issue templates, a contribution guide stating the house rules
(fail closed; every guard needs a test that fails without it; do not claim more
than you checked), and acknowledgements crediting the people who decapped the
chips.

`UNDERSTUDY_PROFILE_DIR` lets a contributor test a profile before submitting it.

## 12. Review rounds

Twenty-three adversarial Codex reviews, each briefed to find ways to corrupt a
ROM, lose an input, use the wrong profile or table, or misrepresent evidence.

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
| 10 | Three HIGH on the traced-layout work, fixed and mutation-tested: the relaxed phrase-coverage guard needed a replacement for the case it stopped catching (a phrase that converts nothing is now refused outright); `silent_phrases` could be claimed for a phrase that was merely never found; and the mirrored-device merge tested which bytes changed when a conversion may legitimately leave a byte unchanged — the first replacement tested coverage, which round 11 showed was too strong. Two MEDIUM findings on evidence wording were fixed by stating what the trace does and does not establish, per profile and in §3. |
| 11 | **No blocker.** Confirmed HIGH 2 and MEDIUM 4 closed. HIGH 1 only partly: the new guard catches a phrase cut off by a missing device, but a profile that simply declares fewer phrases than its table holds is self-contained and no static check can see it — that is now stated as a limitation rather than covered by a claim. HIGH 3's replacement was too strong and refused a harmless duplicate; it now tests whether the two windows *disagree* rather than whether they overlap. Three MEDIUM: a miscount of the affected profiles (nine → eight), a headline criterion that contradicted `m_mpac`'s declared unterminated phrase, and guard ordering that hid the specific diagnosis behind a device-level one. All fixed. |
| 12 | No blocker. Three MEDIUM: documents describing an earlier version of the mirror check, of the termination criterion, and of how many profiles had been board-simulated. |
| 13 | No blocker. Four MEDIUM: a hand procedure that would have rejected a correct layout, a byte-identity claim that did not follow from hash identification, a precision table naming only Embryon, and a headline stronger than the qualification beneath it. |
| 14 | No blocker. Two MEDIUM: the corrected hand procedure was still weaker than the tool without saying so, and "the output is not the simulated one" was too strong for options that may not change a byte. |
| 15 | No HIGH, no MEDIUM. Ship as a clearly-labelled pre-1.0 research preview. |
| 16 | **Attacked the Rapid Fire exclusion**, which was the whole reason coverage stopped short. One HIGH: the exclusion rested on one observation and the attribution of 35 PIA references was undemonstrated. Disassembly showed the firmware DOES carry the TMS byte-write routine; that claim was retracted. |
| 17 | One MEDIUM: "nothing reaches it, so it is dead code" did not follow from the absence of a literal address. Conclusion removed rather than defended; the exclusion rests on criterion 3 alone. |
| 18–19 | Two MEDIUM, one each: an unqualified "has no speech" surviving in §8b and then in the README, both narrowed to "plays no speech under any command the MPU can send". |
| 20 | **Ready.** No HIGH, no MEDIUM, no LOW. |
| 21 | Three LOW on the ROM-availability wording: "no identifiable dump", a dump does not by itself make another set, and hash-verified vs verified. |
| 22 | **Coverage rose to 16 of 19** — Big Bat's ROMs were found in an archive tree the earlier search never walked. Three MEDIUM: the new profile shipped without the traced-evidence fields the other fifteen carry, its 29% U4 coverage was unjustified in the profile itself, and its provenance recorded no SHA-1 to check the SHA-256 against. |
| 23 | One MEDIUM: the residue above Big Bat's speech was classified as "not speech" when the evidence supports "consistent with sequencer data, and nothing the firmware plays lies there". Plus three stale counts. |

Rounds 10 to 23 covered the traced-layout work: eleven new profiles, two
corrected ones, three new layout facts in the schema, a per-byte merge for
mirrored devices, and the replacement of the static frame corpus with an
execution-derived phrase list as criterion 3, and finally a sixteenth set.
Nothing in it was accepted on the first pass. Two of the guards written to
answer a finding were themselves found to be too strong or to claim more than
they did, three of the author's claims about Rapid Fire had to be retracted or
narrowed, and the set that took coverage to 16 was found only because a review
round refused to accept a negative result whose search had been too narrow.

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
5. At least one profile moved to `silicon-verified` on the strength of that
   report; any failure understood and fixed. `silicon-verified` is per profile,
   so a single hardware test raises one set, not the other fifteen.
6. The exact release artifact still passing every CI check.

More profiles and a better mapper are welcome afterwards. They are not
prerequisites for a truthful 1.0 scoped to the validated Embryon workflow.
