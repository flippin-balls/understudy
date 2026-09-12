# Contributing

Understudy is a preservation tool that produces files people burn into EPROMs
and put into machines they cannot replace. That shapes how it is built: it
would rather refuse than guess, and it tries never to claim more than it has
checked.

## The short version

- Tests: `PYTHONPATH=src python -m unittest discover -s tests`
- Documentation check: `python tools/check_docs.py`
- Standard library only. No dependencies, on purpose.
- Python 3.9+, and CI runs on Linux, macOS and Windows.
- No ROM images, ever, anywhere — not in tests, fixtures, issues or PRs.

## Kinds of contribution

| | where to start |
|---|---|
| A real-machine test result | [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) — **the most valuable thing you can send** |
| A new game profile | [docs/CONTRIBUTING_PROFILES.md](docs/CONTRIBUTING_PROFILES.md) |
| A conversion that went wrong | open a bug with the manifest attached |
| Code | read on |

## House rules for code

**Fail closed.** If a condition could mean the output is wrong, stop and say so.
A file of the right length that is silently incorrect is the worst thing this
tool can produce; an error message is never worse than that.

**Every guard needs a test that fails without it.** Revert your fix and confirm
the suite goes red. Several checks in this repository were once passing tests
that could not fail; the mutation habit is how they were found.

**Do not claim more than you checked.** If a result comes from emulation, say
emulation. If a figure comes from one game, say which. `evidence` blocks and
status fields exist so a reader can tell what stands behind a claim.

**Two checks are marked as backstops** — the stray-byte and reconciliation
checks in `workflow.py`. They cannot fire today, and property tests hold the
invariants that keep them unreachable. If you change how patching works, those
property tests are the ones to watch.

## Documentation style

Write for the person standing at a bench first. Put the command, decision, or
warning they need before the explanation of why it works.

Keep a caveat where it first matters, then link to the detailed evidence instead
of restating it throughout the docs. Technical precision matters; exhaustive
qualification in every paragraph does not make a claim safer.

Prefer ordinary language. A useful test is whether you would say the sentence
to another technician while looking at the board. Avoid sales language,
rhetorical flourishes, and paragraphs that argue with objections nobody has
raised yet.

Run `python tools/check_docs.py` before sending documentation changes. It is a
small local check for accidental prose problems, not a style authority. A
warning is a prompt to reread the passage, not an instruction to rewrite a good
technical sentence to satisfy a score.

## Things that will surprise you

- Bits leave a byte **LSB-first** but assemble into fields **MSB-first**.
- The TMS5200 and TMS5220 use the **same field widths** — only table contents
  differ. The earlier TMS5100/5110 use a 5-bit pitch field; assuming that here
  desynchronises every frame after the first voiced one.
- A phrase's pointer table may sit **above** the speech it points at.
- A 2 KB device mirrored into a 4 KB socket may be addressed through the
  **mirror**, so conversion rewrites the upper half and the lower copy goes
  stale.
- Duplicate pointers are legal: two commands can name one phrase.

Most of these are documented where they bite, in
[docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md).

## Licensing

Code and documentation you contribute are under **0BSD**, like the rest of the
project. The bundled coefficient tables are BSD-3-Clause and are not ours to
relicense — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). If you add
third-party data of any kind, it needs an entry there with its provenance.

## Review

Changes that affect what gets written to a ROM get read carefully, and usually
adversarially: how could this produce a plausible but wrong file? That is the
same standard the existing code was held to, and it has found real defects.
