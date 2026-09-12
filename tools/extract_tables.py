#!/usr/bin/env python3
"""Extract TMS5200 and TMS5220 coefficient tables from a MAME or PinMAME tree.

    python tools/extract_tables.py /path/to/mame src/tms52xx/data/

This is a MAINTAINER tool. Understudy ships the tables it needs in
`src/tms52xx/data/`, so ordinary users never run this. It exists so the bundled
data can be regenerated and independently checked against upstream.

Two source trees are understood, chosen by which file is present:

    MAME     src/devices/sound/tms5110r.hxx   preferred: BSD-3-Clause by its own
                                              header, and decap-verified
    PinMAME  src/sound/tms5220r.c             kept for comparison

MAME has no `tms5200_coeff`. Its TMS5200 table is `T0285_2501E_coeff`, named for
the CD2501E/TMC0285 the part is equivalent to; the section comment above it
reads "TMS5200/CD2501E". PinMAME carries both names, and they agree.

Not a one-line regex, for three reasons. The tables are fields of
`struct tms5100_coeffs` instances rather than named arrays, so they are read
positionally in declaration order; a superseded table sits in an `#if 0` block,
so a parser that ignores the preprocessor picks the dead one; and some tables
are macro references with backslash-continued bodies. Every extracted table is
checked against the width its own struct declares, so a misparse fails here
rather than producing quiet nonsense downstream.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Field order within `struct tms5100_coeffs`. Positional, because the C
# initialisers are positional.
SUBTYPE, NUM_K, ENERGY_BITS, PITCH_BITS, KBITS, ENERGY, PITCH, KTABLE = range(8)

#: Source trees we know how to read, in preference order. `structs` maps the
#: name Understudy uses to the C identifier holding that variant's table.
SOURCES = [
    {"id": "mame",
     "path": ("src", "devices", "sound", "tms5110r.hxx"),
     "repo": "https://github.com/mamedev/mame",
     "structs": {"tms5200": "T0285_2501E_coeff", "tms5220": "tms5220_coeff"}},
    {"id": "pinmame",
     "path": ("src", "sound", "tms5220r.c"),
     "repo": "https://github.com/vpinball/pinmame",
     "structs": {"tms5200": "tms5200_coeff", "tms5220": "tms5220_coeff"}},
]


def find_source(root):
    """Which of the known source trees is this, and where is its table file?"""
    for source in SOURCES:
        candidate = Path(root).joinpath(*source["path"])
        if candidate.exists():
            return source, candidate
    raise SystemExit(
        "no known coefficient file under %s -- expected one of:\n  %s"
        % (root, "\n  ".join("/".join(s["path"]) for s in SOURCES)))


def licence_header(text):
    """MAME-style `// license:` / `// copyright-holders:` tags, if present."""
    licence = re.search(r"^//\s*license:\s*(.+)$", text, re.M)
    holders = re.search(r"^//\s*copyright-holders:\s*(.+)$", text, re.M)
    return (licence.group(1).strip() if licence else None,
            holders.group(1).strip() if holders else None)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def drop_dead_blocks(text: str) -> str:
    """Resolve `#if 0 ... #else ... #endif`, keeping the live branch.

    The superseded TMS5220 table sits in the `#if 0` arm and the live one in the
    `#else`, so dropping to `#endif` discards exactly the table wanted.
    """
    out, depth, state = [], 0, None      # state: None | "skip" | "keep"
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"#\s*if\s+0\b", stripped):
            state, depth = "skip", 1
            continue
        if state is not None:
            if re.match(r"#\s*if", stripped):
                depth += 1
            elif re.match(r"#\s*else\b", stripped) and depth == 1:
                state = "keep"
                continue
            elif re.match(r"#\s*endif", stripped):
                depth -= 1
                if depth == 0:
                    state = None
                    continue
            if state == "skip":
                continue
        out.append(line)
    return "\n".join(out)


def collect_macros(text: str):
    """`#define NAME body`, including backslash-continued multi-line bodies.

    The live TMS5220 tables are written as macro references rather than
    literals, so extraction without expansion finds an empty struct.
    """
    joined = re.sub(r"\\\n", " ", text)
    macros = {}
    for match in re.finditer(r"^[ \t]*#\s*define[ \t]+(\w+)[ \t]+(.*)$",
                             joined, re.M):
        name, body = match.group(1), match.group(2).strip()
        if "{" in body or re.search(r"-?\d", body):
            macros[name] = body
    return macros


def expand_macros(text: str, macros) -> str:
    """Substitute macro bodies until nothing changes."""
    for _ in range(8):
        before = text
        for name, body in macros.items():
            text = re.sub(r"\b%s\b" % re.escape(name), lambda _m, b=body: b, text)
        if text == before:
            break
    return text


def struct_body(text: str, name: str) -> str:
    """The balanced brace body of `... tms5100_coeffs NAME = { ... };`."""
    match = re.search(r"tms5100_coeffs\s+%s\s*=\s*\{" % re.escape(name), text)
    if not match:
        raise SystemExit("struct %r not found; PinMAME's naming may have changed"
                         % name)
    start = match.end() - 1
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    raise SystemExit("unbalanced braces in struct %r" % name)


def split_top_level(body: str):
    """Split on commas that are not inside braces."""
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current))
    return parts


def ints(text: str):
    return [int(v, 0) for v in re.findall(r"-?0x[0-9a-fA-F]+|-?\d+", text)]


def one_int(text: str, what: str) -> int:
    values = ints(text)
    if len(values) != 1:
        raise SystemExit("expected a single integer for %s, got %r" % (what, text.strip()))
    return values[0]


def build(text: str, struct_name: str, our_name: str) -> dict:
    fields = split_top_level(struct_body(text, struct_name))
    if len(fields) < 8:
        raise SystemExit("struct %s has %d initialisers, expected at least 8"
                         % (struct_name, len(fields)))

    num_k = one_int(fields[NUM_K], "num_k")
    energy_bits = one_int(fields[ENERGY_BITS], "energy_bits")
    pitch_bits = one_int(fields[PITCH_BITS], "pitch_bits")
    k_widths = ints(fields[KBITS])
    energy = ints(fields[ENERGY])
    pitch = ints(fields[PITCH])
    k = [ints(part) for part in split_top_level(fields[KTABLE].strip().lstrip("{").rstrip("}"))]

    if num_k != 10 or len(k_widths) != 10 or len(k) != 10:
        raise SystemExit("%s: expected 10 K tables, got num_k=%d widths=%d tables=%d"
                         % (struct_name, num_k, len(k_widths), len(k)))
    if energy_bits != 4:
        raise SystemExit("%s: energy_bits is %d, expected 4" % (struct_name, energy_bits))
    if len(energy) != 1 << energy_bits:
        raise SystemExit("%s: energy table has %d entries, expected %d"
                         % (struct_name, len(energy), 1 << energy_bits))
    if len(pitch) != 1 << pitch_bits:
        raise SystemExit("%s: pitch table has %d entries, expected %d"
                         % (struct_name, len(pitch), 1 << pitch_bits))
    for i, (values, width) in enumerate(zip(k, k_widths), start=1):
        if len(values) != 1 << width:
            raise SystemExit("%s: K%d has %d entries, expected %d"
                             % (struct_name, i, len(values), 1 << width))

    return {"name": our_name, "pitch_bits": pitch_bits, "k_widths": k_widths,
            "energy": energy, "pitch": pitch, "k": k}


#: Revisions this extractor has been run against and checked. A file that is not
#: one of these is not necessarily wrong, but it has not been seen.
KNOWN_SOURCES = {
    "43b114437812a94073804617f78a4fd72e9874292dc9be44660cf7b8904f6480":
        "MAME src/devices/sound/tms5110r.hxx @ 2d5bb2dc (2017-05-26)",
    "21e3e4c16f044f2a380dbbb630ed375061218936256d413802c3f73883afbdc0":
        "PinMAME src/sound/tms5220r.c @ 9ac98e75 (2026-09-06)",
}


def extract(root):
    """Return (tables, provenance) for a source tree."""
    source, source_file = find_source(root)
    body = source_file.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    text_raw = body.decode("utf-8", errors="replace")
    licence, holders = licence_header(text_raw)

    raw = strip_comments(text_raw)
    # Drop dead branches BEFORE collecting macros: a definition inside `#if 0`
    # could otherwise shadow the live one.
    text = drop_dead_blocks(raw)
    text = expand_macros(text, collect_macros(text))

    # Extract and validate every variant before returning any of them.
    tables = {name: build(text, struct, name)
              for name, struct in source["structs"].items()}

    provenance = {
        "source_id": source["id"],
        "repository": source["repo"],
        "path": "/".join(source["path"]),
        "sha256": digest,
        "known_revision": KNOWN_SOURCES.get(digest),
        "license_tag": licence,
        "copyright_holders": holders,
        "structs": dict(source["structs"]),
    }
    return tables, provenance


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    root, outdir = Path(argv[1]), Path(argv[2])
    if not root.exists():
        raise SystemExit("%s does not exist -- point this at a source checkout"
                         % root)

    tables, prov = extract(root)

    if prov["known_revision"]:
        print("source   %s" % prov["known_revision"])
    else:
        print("source   %s\n         sha256 %s\n"
              "         NOT a revision this extractor has been checked against. "
              "The width validation\n         catches a changed table shape, not "
              "a reordering of the struct's fields.\n"
              "         Compare a few values by eye before relying on it."
              % (prov["path"], prov["sha256"]))
    print("licence  %s" % (prov["license_tag"] or "no per-file tag found"))
    if prov["copyright_holders"]:
        print("holders  %s" % prov["copyright_holders"])
    print()

    outdir.mkdir(parents=True, exist_ok=True)
    for name in sorted(tables):
        data = dict(tables[name])
        data["_provenance"] = {
            "repository": prov["repository"],
            "path": prov["path"],
            "struct": prov["structs"][name],
            "source_sha256": prov["sha256"],
            "license": prov["license_tag"],
            "copyright_holders": prov["copyright_holders"],
        }
        path = outdir / ("%s.json" % name)
        tmp = path.with_name(path.name + ".partial")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        longest = max(v for v in data["pitch"] if v)
        print("%-18s -> %s   lowest f0 %.1f Hz"
              % (prov["structs"][name], path, 8000 / longest))

    print("\nRead the licence header on %s yourself before relying on these."
          % prov["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
