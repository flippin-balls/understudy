# Third-party notices

Understudy's own code and documentation are Zero-Clause BSD
([LICENSES/0BSD.txt](LICENSES/0BSD.txt)) — use them for anything, no attribution
required.

**The bundled coefficient data is not ours and is not 0BSD.** It is
BSD-3-Clause, and that licence requires this notice to travel with it. If you
redistribute Understudy, in source or binary form, keep this file.

---

## TMS5200 and TMS5220 LPC coefficient tables

**Files:** `src/tms52xx/data/tms5200.json`, `src/tms52xx/data/tms5220.json`

| | |
|---|---|
| Upstream | MAME — <https://github.com/mamedev/mame> |
| Source path | `src/devices/sound/tms5110r.hxx` |
| Upstream commit for that file | `2d5bb2dc20176f765a5fb7f1e59ff4e27a41e34e` (2017-05-26) |
| Source file SHA-256 | `43b114437812a94073804617f78a4fd72e9874292dc9be44660cf7b8904f6480` |
| Licence | BSD-3-Clause |
| Copyright holders | Frank Palazzolo, Couriersud, Jonathan Gevaryahu |

### What was taken

Only the numeric coefficient tables for two chip variants, transcribed into JSON
by `tools/extract_tables.py`:

| Understudy file | MAME struct | Contents |
|---|---|---|
| `tms5200.json` | `T0285_2501E_coeff` | energy, pitch and K1–K10 tables, field widths |
| `tms5220.json` | `tms5220_coeff` | energy, pitch and K1–K10 tables, field widths |

No MAME code was copied. The chirp table, interpolation coefficients, subtype
constants and every other variant in that file were not taken.

MAME has no `tms5200_coeff`. Its TMS5200 table is `T0285_2501E_coeff`, under a
section headed "TMS5200/CD2501E" — the TMS5200 is equivalent to the
CD2501E/TMC0285, as the upstream decap notes record.

### Why we consider this redistributable

MAME's `COPYING` states:

> MAME as a whole is made available under the terms of the GNU General Public
> License. Individual source files may be made available under less restrictive
> licenses, as noted in their respective header comments.

and the header comment of `tms5110r.hxx` reads:

```
// license:BSD-3-Clause
// copyright-holders:Frank Palazzolo, Couriersud, Jonathan Gevaryahu
```

BSD-3-Clause permits redistribution in source and binary form provided the
copyright notice, the conditions and the disclaimer travel with it. That is what
this file and [LICENSES/BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) are for.

This is our reading, offered so you can check it rather than take it on trust.
It is not legal advice, and it is your call for your use.

### Verification basis stated upstream

The values are not a transcription of a datasheet. `tms5110r.hxx` records how
each was established:

> **TMS5200/CD2501E** — "The TMS5200NL was decapped and imaged by digshadow in
> March, 2013. […] The LPC table is verified to match the decap. (It was
> previously dumped with PROMOUT which matches as well)"

> **TMS5220/5220C** — "The TMS5220NL was decapped and imaged by digshadow in
> April, 2013. The LPC table table is verified to match the decap. […] The
> TMS5220CNL was decapped and imaged by digshadow in April, 2013. The LPC table
> table is verified to match the decap and exactly matches TMS5220NL."

That last sentence is why Understudy treats the TMS5220, TMS5220C and TSP5220C
as one conversion target — see [docs/CHIPS.md](docs/CHIPS.md) for what that
claim does and does not cover.

### Regenerating and checking it yourself

```
git clone https://github.com/mamedev/mame
python tools/extract_tables.py mame src/tms52xx/data/
git diff --stat src/tms52xx/data/
```

The extractor prints the source file's SHA-256 and its licence header, and says
so plainly if the file is not a revision it has been checked against. A clean
`git diff` means the bundled data is exactly what upstream holds today.

`tools/extract_tables.py` also reads PinMAME's `src/sound/tms5220r.c`, whose
tables are identical for these two parts. That path exists for comparison;
PinMAME is mid-migration to per-file BSD-3-Clause and not every file has been
converted, which is why the bundled copy comes from MAME.

---

## Not bundled

**No ROM images.** Understudy contains no game code or speech data, and never
distributes any. See
[docs/SQUAWK_AND_TALK.md](docs/SQUAWK_AND_TALK.md#where-the-roms-come-from) for
legitimate ways to obtain the ROMs for a machine you own.

**Nothing from other LPC projects.** The tables in Talkie, python_wizard,
BlueWizard and TMS Express were compared during research and none of their code
or data is included here. [docs/PRIOR_ART.md](docs/PRIOR_ART.md) records what is
in each and how they differ.
