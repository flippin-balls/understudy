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
import os
import sys
from pathlib import Path

from .rom import PhraseTable, diagnose_last_byte, patch_rom, summarise
from .tables import ChipTables


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _truncation_choice(value):
    """Turn the --truncate-last-byte argument into what patch_rom expects.

    Absent -> False (no phrase truncated). Bare flag -> True (all of them).
    A list of indexes -> just those, because the convention is per stream and a
    single ROM set is known to use both.
    """
    if value is None:
        return False
    if value == "all":
        return True
    indexes = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError("%r is not a phrase index" % part)
        indexes.add(int(part))
    if not indexes:
        raise ValueError("no phrase indexes given")
    return indexes


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
    verdicts = {}
    if args.source_tables:
        source = ChipTables.from_json(args.source_tables)
        verdicts = diagnose_last_byte(rom, table, source)

    header = ("  %-5s %-8s %-8s %-7s %s" % ("#", "start", "end", "bytes",
                                            "final byte")
              if verdicts else "  %-5s %-8s %-8s %s" % ("#", "start", "end",
                                                        "bytes"))
    print(header)
    for phrase in table.phrases:
        row = "  %-5d 0x%06X 0x%06X %-7d" % (phrase.index, phrase.start,
                                             phrase.end, phrase.length)
        print(row + (" %s" % verdicts[phrase.index] if verdicts else ""))

    if not verdicts:
        print("\nPass --source-tables to also report each phrase's final-byte "
              "convention,\nwhich decides whether it needs --truncate-last-byte "
              "on conversion.")
        return 0

    spare = sorted(i for i, v in verdicts.items() if v == "spare")
    broken = sorted(i for i, v in verdicts.items() if v == "no stop")
    print("\n  required  the final ROM byte carries part of the stop frame and "
          "must be kept")
    print("  spare     the phrase already terminates before its final byte")
    print("  no stop   no stop frame either way -- check the layout")
    print("\nThis reports whether the final byte is NEEDED. It cannot tell you "
          "which\nconvention your player uses -- that is firmware behaviour and "
          "is not recorded in\nthe speech data. If your player does not transmit "
          "the final byte, then\n--truncate-last-byte is safe for the `spare` "
          "phrases, and would remove the\nterminator from the `required` ones.")
    if spare:
        print("\nspare in %d phrase(s): %s"
              % (len(spare), ",".join(str(i) for i in spare)))
    if broken:
        print("\n%d phrase(s) have no stop frame (%s). That normally means the "
              "declared\nlayout is wrong; convert will refuse them."
              % (len(broken), ", ".join(str(i) for i in broken)))
    return 0


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temporary file in the same directory, then rename.

    A converted ROM is written to be flashed. A half-written one is a file that
    looks like a ROM, has a plausible size, and is wrong -- the worst possible
    failure for this tool. `os.replace` is atomic within a directory, so the
    destination either holds the previous content or the complete new content
    and never anything in between.
    """
    tmp = path.with_name(path.name + ".tmp")
    handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same_file(a: Path, b: Path) -> bool:
    """Would writing `b` overwrite `a`? Resolves links, and handles b missing."""
    try:
        return a.resolve() == b.resolve() or (b.exists() and a.samefile(b))
    except OSError:
        return False


def cmd_convert(args) -> int:
    rom_path = Path(args.rom)

    out_path = Path(args.output)
    manifest_path = out_path.with_suffix(out_path.suffix + ".manifest.json")
    # --force means "replace the file you named", never "destroy the ROM you are
    # converting". A source ROM may be the only copy someone has of a board's
    # contents, and there is no version of this tool's job that requires
    # overwriting it -- so this check sits ahead of --force rather than under it.
    for label, candidate in (("output", out_path), ("manifest", manifest_path)):
        if _same_file(rom_path, candidate):
            print("refusing to convert: the %s path (%s) is the input ROM"
                  % (label, candidate), file=sys.stderr)
            return 2

    rom = rom_path.read_bytes()
    source = ChipTables.from_json(args.source_tables)
    target = ChipTables.from_json(args.target_tables)
    table = _load_layout(args, rom)

    try:
        truncate = _truncation_choice(args.truncate_last_byte)
    except ValueError as error:
        print("bad --truncate-last-byte: %s" % error, file=sys.stderr)
        return 2
    try:
        out, results = patch_rom(rom, table, source, target,
                                 truncate_last_byte=truncate)
    except ValueError as error:
        print("%s" % error, file=sys.stderr)
        return 2
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
    if stats["frames_truncated"]:
        print("frames left unconverted (truncated): %d"
              % stats["frames_truncated"])
    if stats["phrases_without_stop_frame"]:
        print("phrases with no stop frame: %d"
              % stats["phrases_without_stop_frame"])

    # FAIL CLOSED. A phrase that does not end in a stop frame was almost
    # certainly not a phrase: the usual cause is a wrong --table-offset,
    # --phrases or --base-address, which points the converter at code or at
    # arbitrary data and rewrites it as if it were speech. The resulting file is
    # a plausible-looking, silently corrupt ROM. Warning and writing it anyway
    # puts the burden on the user noticing a line of output; refusing does not.
    unterminated = [r for r in results if not r.stopped_cleanly]
    if unterminated and not args.allow_unterminated:
        print("\nrefusing to convert: %d of %d phrase(s) do not end in a stop "
              "frame (first is phrase %d at 0x%X-0x%X).\nThis normally means the "
              "declared layout is wrong and the converter is rewriting something "
              "that is not\nspeech. Check --table-offset, --phrases and "
              "--base-address against docs/SQUAWK_AND_TALK.md.\nIf the layout is "
              "genuinely right and these phrases really are unterminated, pass "
              "--allow-unterminated."
              % (len(unterminated), len(results), unterminated[0].phrase.index,
                 unterminated[0].phrase.start, unterminated[0].phrase.end),
              file=sys.stderr)
        return 2

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    if out_path.exists() and not args.force:
        print("refusing to overwrite %s (pass --force)" % out_path,
              file=sys.stderr)
        return 2
    if manifest_path.exists() and not args.force:
        print("refusing to overwrite %s (pass --force)" % manifest_path,
              file=sys.stderr)
        return 2

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
                   "truncate_last_byte": sorted(r.phrase.index for r in results
                                                if r.last_byte_truncated)},
        "summary": stats,
        "changed_ranges": _changed_ranges(rom, out),
        "phrases": [{"index": r.phrase.index, "start": r.phrase.start,
                     "end": r.phrase.end, "frames": r.frames,
                     "clamped": r.clamped, "approximated": r.approximated,
                     "truncated": r.truncated,
                     "last_byte_truncated": r.last_byte_truncated,
                     "changed_bytes": r.changed_bytes,
                     "stopped_cleanly": r.stopped_cleanly}
                    for r in results],
    }
    # Manifest first: a manifest with no ROM beside it is an obvious, harmless
    # leftover, while a ROM with no manifest is an unauditable image that looks
    # finished. If the second rename fails, fail in the recoverable direction.
    _atomic_write(manifest_path,
                  json.dumps(manifest, indent=2).encode("utf-8"))
    _atomic_write(out_path, out)
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
    inspect.add_argument("--source-tables", default=None,
                         help="report each phrase's final-byte convention, "
                              "which needs the source chip's tables to parse "
                              "the frames")
    _add_layout_args(inspect, required=False)
    inspect.set_defaults(func=cmd_inspect)

    convert = sub.add_parser("convert", help="write a converted copy of a ROM")
    convert.add_argument("rom")
    convert.add_argument("-o", "--output", required=True)
    convert.add_argument("--source-tables", required=True)
    convert.add_argument("--target-tables", required=True)
    convert.add_argument("--truncate-last-byte", nargs="?", const="all",
                         metavar="ALL|N,N,...",
                         help="phrases whose final ROM byte the player never "
                              "transmits, so it must be left untouched. Bare "
                              "flag means every phrase; otherwise a list of "
                              "phrase indexes. `inspect` reports which phrases "
                              "need it")
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--force", action="store_true",
                         help="allow overwriting an existing output file; never "
                              "permits writing over the input ROM")
    convert.add_argument("--allow-unterminated", action="store_true",
                         help="convert phrases that do not end in a stop frame. "
                              "Off by default because the usual cause is a wrong "
                              "layout, not an unterminated phrase")
    _add_layout_args(convert, required=True)
    convert.set_defaults(func=cmd_convert)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as error:
        # Layout and table problems are the expected failure of this tool, not
        # a crash: the user is guessing at a pointer table and will guess wrong
        # several times. A traceback buries the one line that helps them.
        print("error: %s" % error, file=sys.stderr)
        return 2
    except OSError as error:
        print("error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
