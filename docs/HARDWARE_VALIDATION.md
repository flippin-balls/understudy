# Reporting a real-board test

Real-board results are one of the most useful contributions to Understudy.
Embryon is currently the only profile tested on hardware; the other bundled
profiles are validated structurally and in board simulation.

A second report on Embryon is still useful, especially with a different
replacement chip or with `--optimize-audio`.

Open an issue using the **Hardware validation** template, or copy the form below.

## Before you start

- Keep the original ROMs and chips.
- Keep the manifest from `convert-set`.
- Record the markings on the original and replacement speech chips.
- If possible, record or listen to the original TMS5200 setup first so you have a
  baseline on the same board.

## Test form

### Machine and board

| | |
|---|---|
| Game / title | |
| Board | e.g. Bally Squawk & Talk AS-2518-61 / -61A |
| Board revision markings | |
| Repairs, mods, or other non-standard details | |

### Speech chips

| | original | replacement |
|---|---|---|
| Part number as marked | e.g. TMS5200NL | e.g. TSP5220C |
| Date code | | |
| Other markings | | |

Did the replacement require any jumper, socket, wiring, or other board change?

### ROMs

| socket | device type | jumpers set for | original SHA-256 | converted SHA-256 |
|---|---|---|---|---|
| U4 | 2716 | | | |
| U5 | 2532 | 2532 / 2732 | | |

The hashes are in the manifest under `inputs` and `outputs`.

### Understudy

| | |
|---|---|
| Version | `python understudy.py --version` or manifest |
| Profile id and version | |
| Target chip | |
| Audio optimization | off / `--optimize-audio` |
| Source table SHA-256 | manifest `tables.source.sha256` |
| Target table SHA-256 | manifest `tables.target.sha256` |
| Other overrides | custom tables, `--allow-unterminated`, etc. |

If audio optimization was enabled, include the manifest's
`audio_optimization` section.

### Power-on behavior

- Does the board come out of reset normally?
- Does the speech chip's READY behavior look normal?
- Any change in self-test behavior?
- Any new noise, hum, or click?

### Phrase by phrase

One row per phrase or command you can exercise:

| phrase / command | intelligible? | pitch vs original | notes |
|---|---|---|---|
| 0 | yes / no / partly | same / higher / lower | |
| 1 | | | |

Note especially:

- speech cut short or running on;
- noise or garbage instead of speech;
- a phrase that does not play;
- speech at the wrong speed;
- any phrase that sounds worse with `--optimize-audio` than without it.

Some pitch raising is expected when a source frame falls below the TMS5220's
pitch floor. The manifest reports how many frames were affected.

### Conclusion

- [ ] **PASS** — speech works correctly
- [ ] **PARTIAL** — mostly works, with specific problems noted above
- [ ] **FAIL** — does not work

Anything else worth recording?

## What happens to the report

A passing first hardware report can move a profile from `board-simulated` to
`silicon-verified`. Partial and failing reports are just as important because
they expose problems the structural and simulation checks did not catch.

Reports may be referenced from the profile and acknowledgements unless you ask
not to be credited.
