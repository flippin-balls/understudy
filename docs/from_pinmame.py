#!/usr/bin/env python3
"""Extract TMS5200 and TMS5220 coefficient tables from a PinMAME checkout.

    python docs/from_pinmame.py /path/to/pinmame tables/

Check the licence header on `src/sound/tms5220r.c` in your own checkout and
satisfy yourself it suits your use before relying on the output. PinMAME is
migrating to 3-Clause BSD per file and not every file has been converted; that
is why this project does not ship the tables itself.

WHY THIS IS NOT A ONE-LINE REGEX

The tables are fields of `struct tms5100_coeffs` instances, not standalone named
arrays, so they must be read positionally in declaration order. The file also
contains a second, superseded `tms5220_coeff` inside an `#if 0` block; a parser
that ignores the preprocessor picks the dead one. Both are handled below, and
every extracted table is checked against the width its own struct declares, so a
misparse fails here rather than producing quiet nonsense downstream.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Field order within `struct tms5100_coeffs`. Positional, because the C
# initialisers are positional.
SUBTYPE, NUM_K, ENERGY_BITS, PITCH_BITS, KBITS, ENERGY, PITCH, KTABLE = range(8)

VARIANTS = {"tms5200": "tms5200_coeff", "tms5220": "tms5220_coeff"}


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


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    root, outdir = Path(argv[1]), Path(argv[2])
    source_file = root / "src" / "sound" / "tms5220r.c"
    if not source_file.exists():
        raise SystemExit("%s not found -- point this at a PinMAME checkout"
                         % source_file)

    raw = strip_comments(source_file.read_text(errors="replace"))
    # Drop dead branches BEFORE collecting macros. Collecting from the raw text
    # would pick up definitions inside `#if 0`, and if a name is defined in both
    # arms the dead one can win by being later in the file -- a misparse that
    # would look like a plausible table rather than an error.
    text = drop_dead_blocks(raw)
    text = expand_macros(text, collect_macros(text))
    outdir.mkdir(parents=True, exist_ok=True)

    for our_name, struct_name in VARIANTS.items():
        data = build(text, struct_name, our_name)
        path = outdir / ("%s.json" % our_name)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        longest = max(p for p in data["pitch"] if p)
        print("%-16s -> %s   lowest f0 %.1f Hz"
              % (struct_name, path, 8000 / longest))

    print("\nCheck the licence header on %s before relying on these." % source_file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
