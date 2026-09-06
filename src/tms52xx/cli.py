"""Command line: inspect a speech ROM, and convert one to a new file.

Two commands, both of which refuse to be surprising.

`inspect` reads and reports. It never writes.

`convert` writes a NEW file and will not overwrite an existing one without
--force. The input is never modified. Every conversion emits a manifest
recording the hashes, the layout you declared, the per-phrase results and the
byte ranges that changed, so a patched ROM can be audited later by someone who
was not there when it was made.

The layout arguments are not optional and cannot be inferred. See
docs/SQUAWK_AND_TALK.md for why, and how to find them for your ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .rom import PhraseTable, patch_rom, summarise
from .tables import ChipTables


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_layout(args, rom: bytes) -> PhraseTable:
    return PhraseTable.from_pointers(
        rom, args.table_offset, args.phrases,
        address_ordered=not args.command_ordered,
        has_end_bound=not args.no_end_bound,
        base_address=args.base_address)


def _changed_ranges(before: bytes, after: bytes):
    """Contiguous ranges that differ, so a manifest can state them exactly."""
    ranges, start = [], None
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b and start is None:
            start = i
        elif a == b and start is not None:
            ranges.append([start, i])
            start = None
    if start is not None:
        ranges.append([start, len(before)])
    return ranges


def cmd_inspect(args) -> int:
    rom = Path(args.rom).read_bytes()
    print("file      %s" % args.rom)
    print("size      %d bytes" % len(rom))
    print("sha256    %s" % _sha256(rom))
    if args.phrases is None:
        print("\nNo layout given, so no phrases were read. Pass --table-offset "
              "and --phrases\nto have the pointer table interpreted; see "
              "docs/SQUAWK_AND_TALK.md.")
        return 0
    table = _load_layout(args, rom)
    print("\n%d phrases from a pointer table at 0x%X" % (len(table.phrases),
                                                         args.table_offset))
    print("  %-5s %-8s %-8s %s" % ("#", "start", "end", "bytes"))
    for phrase in table.phrases:
        print("  %-5d 0x%06X 0x%06X %d" % (phrase.index, phrase.start,
                                           phrase.end, phrase.length))
    return 0


def cmd_convert(args) -> int:
    rom_path = Path(args.rom)
    rom = rom_path.read_bytes()
    source = ChipTables.from_json(args.source_tables)
    target = ChipTables.from_json(args.target_tables)
    table = _load_layout(args, rom)

    out, results = patch_rom(rom, table, source, target,
                             last_byte_verbatim=not args.truncate_last_byte)
    stats = summarise(results)

    # Verify before writing: re-read the produced image and confirm that only
    # the declared phrase extents moved. A conversion that touched anything else
    # is a bug, and the user should not receive the file.
    if len(out) != len(rom):
        print("refusing to write: length changed", file=sys.stderr)
        return 2
    phrase_bytes = set()
    for phrase in table.phrases:
        phrase_bytes.update(range(phrase.start, phrase.end))
    stray = [i for i, (a, b) in enumerate(zip(rom, out))
             if a != b and i not in phrase_bytes]
    if stray:
        print("refusing to write: %d bytes outside the phrase extents changed "
              "(first at 0x%X)" % (len(stray), stray[0]), file=sys.stderr)
        return 2

    print("phrases              %d" % stats["phrases"])
    print("frames               %d" % stats["frames"])
    print("frames at the pitch floor %d (%.1f%%)  -- cannot be reproduced"
          % (stats["frames_clamped"], stats["clamped_percent"]))
    print("frames pitch-approximated %d  -- nearest available period"
          % stats["frames_approximated"])
    print("bytes changed        %d of %d" % (stats["bytes_changed"], len(rom)))
    if stats["phrases_without_stop_frame"]:
        print("phrases with no stop frame: %d -- check the layout"
              % stats["phrases_without_stop_frame"])

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    out_path = Path(args.output)
    if out_path.exists() and not args.force:
        print("refusing to overwrite %s (pass --force)" % out_path,
              file=sys.stderr)
        return 2
    out_path.write_bytes(out)

    manifest = {
        "tool": "understudy",
        "input": {"path": str(rom_path), "sha256": _sha256(rom),
                  "bytes": len(rom)},
        "output": {"path": str(out_path), "sha256": _sha256(out),
                   "bytes": len(out)},
        "tables": {"source": source.name, "target": target.name,
                   "source_lowest_f0_hz": round(source.lowest_f0_hz, 2),
                   "target_lowest_f0_hz": round(target.lowest_f0_hz, 2)},
        "layout": {"table_offset": args.table_offset,
                   "phrases": args.phrases,
                   "address_ordered": not args.command_ordered,
                   "has_end_bound": not args.no_end_bound,
                   "base_address": args.base_address,
                   "last_byte_verbatim": not args.truncate_last_byte},
        "summary": stats,
        "changed_ranges": _changed_ranges(rom, out),
        "phrases": [{"index": r.phrase.index, "start": r.phrase.start,
                     "end": r.phrase.end, "frames": r.frames,
                     "clamped": r.clamped, "changed_bytes": r.changed_bytes,
                     "stopped_cleanly": r.stopped_cleanly}
                    for r in results],
    }
    manifest_path = out_path.with_suffix(out_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("\nwrote %s\nwrote %s" % (out_path, manifest_path))
    return 0


def _add_layout_args(parser, required: bool) -> None:
    parser.add_argument("--table-offset", type=lambda v: int(v, 0),
                        required=required,
                        help="byte offset of the 16-bit big-endian pointer table")
    parser.add_argument("--phrases", type=int, required=required,
                        help="number of phrases the table describes")
    parser.add_argument("--base-address", type=lambda v: int(v, 0), default=0,
                        help="subtracted from each pointer, for ROMs whose "
                             "pointers are CPU addresses")
    parser.add_argument("--command-ordered", action="store_true",
                        help="table lists phrases in command order, not address "
                             "order")
    parser.add_argument("--no-end-bound", action="store_true",
                        help="table has one entry per phrase, with no final "
                             "end-bound pointer")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="understudy",
        description="Convert TMS5200 speech data in a Squawk & Talk ROM so it "
                    "plays on a TMS5220.")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="report on a ROM; writes nothing")
    inspect.add_argument("rom")
    _add_layout_args(inspect, required=False)
    inspect.set_defaults(func=cmd_inspect)

    convert = sub.add_parser("convert", help="write a converted copy of a ROM")
    convert.add_argument("rom")
    convert.add_argument("-o", "--output", required=True)
    convert.add_argument("--source-tables", required=True)
    convert.add_argument("--target-tables", required=True)
    convert.add_argument("--truncate-last-byte", action="store_true",
                         help="the player never transmits a phrase's final ROM "
                              "byte; leave it untouched")
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--force", action="store_true",
                         help="allow overwriting an existing output file")
    _add_layout_args(convert, required=True)
    convert.set_defaults(func=cmd_convert)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
