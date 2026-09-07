"""Which chips Understudy knows about, and which tables each one uses.

Understudy bundles the TMS5200 and TMS5220 coefficient tables (see
`data/` and THIRD_PARTY_NOTICES.md), so nothing has to be extracted before a
first conversion. `ChipTables.from_json` still loads a file from anywhere, for
research and for parts these tables do not cover.

WHY 5220, 5220C AND TSP5220C SHARE ONE TABLE

They share it because the silicon does. MAME's `tms5110r.hxx`, in the comment
above the table this project bundles:

    The TMS5220CNL was decapped and imaged by digshadow in April, 2013.
    The LPC table table is verified to match the decap and exactly matches
    TMS5220NL.

and its section heading, "TMS5220/5220C (1983 era for 5220, 1986-1992 era for
5220C; 5220C may also be called TSP5220C)". So one decap-verified table covers
all three, and MAME itself keeps only one struct for them.

WHAT THAT CLAIM DOES NOT COVER, WHICH MATTERS WHEN CHOOSING A PART

The LPC tables are identical. The chips are not. The 5220C has a command the
5220 does not: the opcode that is a NOP on a TMS5200 or TMS5220 is SET RATE on a
5220C, taking a variable frame rate from the low nibble (MAME
`tms5220.cpp`, `TMS5220_HAS_RATE_CONTROL`). At reset the rate is 0, and MAME
notes beside its reload table that "5200 and 5220 always reload with 0" -- so an
un-commanded 5220C runs at the 5220's timing.

The practical consequence for a Squawk & Talk: the board must never send that
opcode. On Embryon it does not. Driving the board's own firmware through every
one of the 64 commands its MPU can send produces exactly one TMS command byte,
`0x60` SPEAK EXTERNAL, and never anything in the SET RATE range. That is a
measurement of one game, not a guarantee about the family, and it is recorded
per profile rather than assumed.

Nothing here says anything about pinout, supply current, clock or audio output
level. Check the datasheet for the part you actually intend to fit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .tables import ChipTables

DATA_DIR = Path(__file__).resolve().parent / "data"


class Chip:
    """A part Understudy can convert from or to."""

    def __init__(self, chip_id: str, names: List[str], table: str, role: str,
                 note: str = "") -> None:
        self.id = chip_id
        #: Markings that identify this part in the wild.
        self.names = names
        #: Basename of the bundled table file this part uses.
        self.table = table
        #: "source", "target", or "both".
        self.role = role
        self.note = note

    @property
    def table_path(self) -> Path:
        return DATA_DIR / ("%s.json" % self.table)

    def tables(self) -> ChipTables:
        return ChipTables.from_json(self.table_path)

    def __repr__(self) -> str:
        return "Chip(%r)" % self.id


#: The parts this tool knows. Keyed by the id used on the command line.
CHIPS: Dict[str, Chip] = {
    "tms5200": Chip(
        "tms5200", ["TMS5200", "TMS5200NL", "CD2501E", "TMC0285"], "tms5200",
        "source",
        "The original part. Also sold as the CD2501E/TMC0285, which MAME's "
        "decap notes record as equivalent."),
    "tms5220": Chip(
        "tms5220", ["TMS5220", "TMS5220NL"], "tms5220", "target",
        "The straightforward replacement."),
    "tms5220c": Chip(
        "tms5220c", ["TMS5220C", "TMS5220CNL"], "tms5220", "target",
        "LPC tables decap-verified identical to the TMS5220. Adds a SET RATE "
        "command on an opcode the 5220 treats as a NOP; harmless on a board "
        "that never sends it."),
    "tsp5220c": Chip(
        "tsp5220c", ["TSP5220C"], "tms5220", "target",
        "The same die as the TMS5220C under TI's TSP part number, and often "
        "the most findable replacement today."),
}

#: Ids accepted where a replacement part is wanted.
TARGETS = [c for c in CHIPS.values() if c.role in ("target", "both")]
#: Ids accepted where an original part is wanted.
SOURCES = [c for c in CHIPS.values() if c.role in ("source", "both")]


def resolve(name: str) -> Chip:
    """Look a chip up by id or by any marking we know it by."""
    key = name.strip().lower().replace("-", "").replace(" ", "")
    if key in CHIPS:
        return CHIPS[key]
    for chip in CHIPS.values():
        if key in [n.lower() for n in chip.names]:
            return chip
    raise ValueError(
        "unknown chip %r. Known: %s"
        % (name, ", ".join(sorted(CHIPS))))


def bundled_provenance(table: str) -> Optional[dict]:
    """The `_provenance` block recorded in a bundled table file."""
    path = DATA_DIR / ("%s.json" % table)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("_provenance")


def describe() -> str:
    """Human-readable listing, used by `understudy chips`."""
    lines = ["Original parts (convert FROM):"]
    for chip in SOURCES:
        lines.append("  %-9s %s" % (chip.id, ", ".join(chip.names)))
        lines.append("            %s" % chip.note)
    lines.append("")
    lines.append("Replacement parts (convert TO):")
    for chip in TARGETS:
        lines.append("  %-9s %s" % (chip.id, ", ".join(chip.names)))
        lines.append("            %s" % chip.note)
    lines.append("")
    lines.append("tms5220, tms5220c and tsp5220c share one decap-verified LPC")
    lines.append("table, so a conversion targeting any of them is the same")
    lines.append("conversion. They differ in control behaviour, not in these")
    lines.append("tables -- see the module docstring in chips.py.")
    return "\n".join(lines)
