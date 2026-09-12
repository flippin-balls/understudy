# Reporting a real-board test

**This is the most useful thing anyone can contribute.** Exactly one profile --
Embryon -- has been validated on silicon, on a single board, by ear. Everything
the other fifteen claim comes from static analysis and emulation, and until
someone fits a converted set to a real Squawk & Talk and listens to it, that is
all they can claim.

A second report on a title that already has one is still worth having: the
Embryon result is one listener's judgement, and it left an unexplained
observation behind (the replacement part sounded slightly louder than the
original).

If you do it — whether it works or not — please report it. A failure is worth
more than silence, and a partial failure ("phrases 1-14 fine, 15 sounds wrong")
is worth more than either.

Open an issue using the **Hardware validation** template, or copy the form below
into one.

## Before you start

- **Keep your original ROMs.** Burn onto blanks. If the conversion is wrong you
  want to be able to put the machine back.
- **Keep the manifest** `convert-set` wrote. Nearly every question anyone will
  ask you is answerable from it, and it contains no ROM data.
- Note the chip markings before you pull anything.

## The baseline matters

A test is far more useful with a "before". If the machine currently talks,
record what it sounds like with the original TMS5200 and original ROMs first,
phrase by phrase. Without that, an oddity in phrase 12 cannot be told from an
oddity that was always there — these boards are forty-odd years old and not
everything odd is our fault.

---

## Form

### Machine and board

| | |
|---|---|
| Game / title | |
| Board | e.g. Bally Squawk & Talk AS-2518-61 / -61A |
| Board revision markings | |
| Anything non-standard about the board | repairs, mods, socketed parts |

### Chips

| | original | replacement |
|---|---|---|
| Part number as marked | e.g. TMS5200NL | e.g. TSP5220C |
| Date code | | |
| Other markings | | |

Did the replacement need any board change (jumpers, sockets, wiring)?

### ROMs

| socket | device type | jumpers set for | original SHA-256 | converted SHA-256 |
|---|---|---|---|---|
| U4 | 2716 | | | |
| U5 | 2532 | 2532 / 2732 | | |

The hashes are in your manifest, under `inputs` and `outputs`.

### Understudy

| | |
|---|---|
| Version (`python understudy.py --version`, or the manifest) | |
| Profile id and version | |
| Target chip | |
| Source table SHA-256 | from the manifest, `tables.source.sha256` |
| Target table SHA-256 | from the manifest, `tables.target.sha256` |
| Any overrides used | `--allow-unterminated`, custom tables, etc. |

### Power-on behaviour

- Does the board come out of reset normally?
- Does the speech chip's READY behave as before?
- Anything different about the self-test, if the board has one?
- Any new noise, hum, or click that was not there before?

### Phrase by phrase

The important part. One row per phrase the game can speak.

| phrase / command | intelligible? | pitch vs original | notes |
|---|---|---|---|
| 0 | yes / no / partly | same / higher / lower | |
| 1 | | | |

For "pitch vs original": Understudy raises frames it cannot reproduce, so
*some* phrases sounding higher is expected and the manifest says how many
frames were affected. What matters is whether it is intelligible and whether
anything sounds broken rather than merely higher.

Note especially:

- a phrase that is **cut short** or runs on;
- **noise or garbage** instead of speech;
- a phrase that **does not play at all**;
- speech that plays at the **wrong speed** — that one is interesting, because it
  is what a TMS5220C would do if the board sent it a SET RATE command
  (see [CHIPS.md](CHIPS.md)).

### Conclusion

- [ ] **PASS** — the machine speaks correctly; differences are limited to the
      expected pitch raising
- [ ] **PARTIAL** — mostly works, specific phrases wrong (say which)
- [ ] **FAIL** — does not work (say how)

Anything else worth knowing?

---

## What happens to your report

A PASS on a profile moves it from `board-simulated` to `silicon-verified`, and
that is recorded in the profile with your report referenced. A FAIL or PARTIAL
is more valuable still: it means something is wrong that no amount of emulation
was going to find, and it will be treated as a bug.

You will be credited in [ACKNOWLEDGEMENTS.md](../ACKNOWLEDGEMENTS.md) unless you
would rather not be.
