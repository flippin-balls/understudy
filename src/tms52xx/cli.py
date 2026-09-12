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
import shlex
import sys
import tempfile
import zipfile
from . import reads
from pathlib import Path, PurePosixPath

from . import __version__
from .rom import PhraseTable, diagnose_last_byte, patch_rom, summarise

#: The manual `convert` command's manifest. Versioned separately from
#: `convert-set`'s, because they describe different things: one image and a
#: declared layout, versus a whole ROM set and the profile that identified it.
MANUAL_MANIFEST_SCHEMA_VERSION = 1
from .tables import ChipTables


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _table_file(path, default_chip: str) -> Path:
    """The file the tables actually came from, bundled or named."""
    if path:
        return Path(path)
    from .chips import CHIPS
    return CHIPS[default_chip].table_path


def _load_table(path, default_chip: str):
    """Read a table file ONCE, returning (tables, bytes, path).

    Parsing and hashing separate reads lets a file changed in between produce a
    manifest that describes something other than what made the ROM.
    """
    where = _table_file(path, default_chip)
    raw = reads.read_bytes(where)
    return ChipTables.from_bytes(raw, where), raw, where


def _table_origin(path, default_chip: str) -> str:
    return str(path) if path else "bundled:%s" % default_chip


def _table_hash(path, default_chip: str) -> str:
    return _sha256(reads.read_bytes(_table_file(path, default_chip)))


def _tables_or_bundled(path, default_chip: str) -> ChipTables:
    """A table file if one was named, otherwise the bundled set for that part.

    Bundling means a first conversion needs no setup. Naming a file still
    overrides it, which is what the research path and unsupported variants use.
    """
    if path:
        return ChipTables.from_json(path)
    from .chips import CHIPS
    return CHIPS[default_chip].tables()


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
    rom = reads.read_bytes(args.rom)
    print("file      %s" % args.rom)
    print("size      %d bytes" % len(rom))
    print("sha256    %s" % _sha256(rom))
    if args.phrases is None and args.table_offset is None:
        print("\nNo layout given, so no phrases were read. Pass --table-offset "
              "and --phrases\nto have the pointer table interpreted; see "
              "docs/SQUAWK_AND_TALK.md.")
        return 0
    if args.phrases is None or args.table_offset is None:
        missing = "--phrases" if args.phrases is None else "--table-offset"
        raise ValueError(
            "a layout needs both --table-offset and --phrases; %s is missing. "
            "Neither can be guessed from the ROM -- see "
            "docs/SQUAWK_AND_TALK.md for how to find them." % missing)
    table = _load_layout(args, rom)
    print("\n%d phrases from a pointer table at 0x%X" % (len(table.phrases),
                                                         args.table_offset))
    verdicts = {}
    if args.source_tables or not args.no_tables:
        source = _tables_or_bundled(args.source_tables, "tms5200")
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

    A half-written ROM is a file that looks like a ROM, has a plausible size,
    and is wrong. `os.replace` is atomic within a directory, so the destination
    holds either the old content or the complete new content.

    The name comes from `mkstemp`, so it is unpredictable and created
    exclusively. A derived name like `<output>.tmp` is a path the user may
    already hold -- converting `out.bin.tmp` into `out.bin` would truncate the
    input -- and a guessable path invites symlink redirection.
    """
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                        prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PublishRollbackError(OSError):
    """A write failed AND the rollback could not fully undo it.

    Rare, and the one case where the caller must not tell the user that nothing
    was changed. Carries the surviving backups so they can be recovered by hand.
    """

    def __init__(self, lost) -> None:
        self.lost = list(lost)
        super().__init__(
            "the output could not be written and the previous contents could "
            "not all be restored. These backups still hold the original "
            "bytes:\n%s"
            % "\n".join("  %s  ->  should be restored to  %s" % (b, d)
                         for b, d in self.lost))


def invocation() -> str:
    """How the user actually started this tool.

    The commands this tool prints are meant to be copied and run, so they have
    to name the thing the reader just typed. Someone running it from a clone
    typed `python understudy.py`; telling them to run `understudy` sends them
    looking for a command that is not on their PATH.
    """
    argv0 = Path(sys.argv[0] or "understudy")
    stem = argv0.name
    if stem in ("understudy", "understudy.exe"):
        return "understudy"                      # installed as a command
    if stem == "cli.py":
        return "%s -m tms52xx.cli" % Path(sys.executable).name
    if argv0.suffix == ".py":
        return "%s %s" % (Path(sys.executable).name, stem)
    return "understudy"


def shell_quote(name: str) -> str:
    """Quote one argument for the shell the user is most likely holding.

    ROM dumps really are named things like
    "Big_Bat_Baseball_Sound EPROM U3 06-20-1984.BIN", and a printed command
    that splits such a name into four arguments is worse than no command at
    all. Quoting follows the running platform, because the command is for the
    shell on that machine: double quotes on Windows, where cmd.exe does not
    accept single ones, and POSIX quoting elsewhere.
    """
    if os.name == "nt":
        return '"%s"' % name if any(c in name for c in ' \t"&()^|<>') else name
    return shlex.quote(name)


def _within(path: Path, directory: Path) -> bool:
    """Is `path` inside `directory` once both are resolved?"""
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _publish(payloads) -> None:
    """Write a whole set of files, or none of them.

    A converted ROM set is only useful complete. Writing the device images one
    at a time meant a failure part-way -- a full disk, a permission change, a
    removable drive pulled -- left some new files beside some stale ones, and a
    technician can burn that mixture without noticing.

    Every payload is staged in the destination directory first, then renamed
    into place. Renaming cannot be made atomic across several names, but the
    slow, failure-prone part is the writing; by the time the renames start,
    every byte is on disk. If staging fails nothing is published, and if a
    rename fails the ones already done are rolled back to what was there
    before.
    """
    staged = []
    try:
        for path, data in payloads:
            handle, name = tempfile.mkstemp(dir=str(path.parent),
                                            prefix=path.name + ".",
                                            suffix=".part")
            with os.fdopen(handle, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(name, 0o644)
            staged.append((Path(name), path))
    except BaseException:
        for temporary, _ in staged:
            _unlink(temporary)
        raise

    published, replaced, lost = [], [], []
    try:
        for temporary, destination in staged:
            if destination.exists():
                # The backup name comes from mkstemp, not from the destination.
                # A derived name like `<dest>.replaced` is a path a user can
                # hold, and this unlinks it -- which destroyed exactly the kind
                # of file this function exists to protect.
                handle, backup = tempfile.mkstemp(dir=str(destination.parent),
                                                  prefix=destination.name + ".",
                                                  suffix=".backup")
                os.close(handle)
                os.replace(destination, backup)
                replaced.append((Path(backup), destination))
            os.replace(temporary, destination)
            published.append(destination)
    except BaseException:
        for destination in published:
            _unlink(destination)
        for backup, destination in replaced:
            try:
                os.replace(backup, destination)
            except OSError:
                # Say so rather than swallow it. The caller reports "nothing
                # was left behind", and that must not be a guess.
                lost.append((backup, destination))
        for temporary, _ in staged:
            _unlink(temporary)
        if lost:
            raise PublishRollbackError(lost)
        raise
    for backup, _ in replaced:
        _unlink(backup)


def _unlink(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _same_file(a: Path, b: Path) -> bool:
    """Would writing `b` overwrite `a`? Handles links, and `b` not existing yet.

    `samefile` is the reliable test but needs both to exist, and the output
    usually does not yet. The path comparison that backs it up goes through
    `os.path.normcase`, because on Windows `speech.bin` and `SPEECH.BIN` are one
    file and comparing `Path`s would call them different -- which would let the
    input ROM be destroyed on exactly the platform most EPROM software runs on.
    """
    try:
        if b.exists() and a.exists() and a.samefile(b):
            return True
    except OSError:
        pass
    try:
        return (os.path.normcase(os.path.abspath(str(a)))
                == os.path.normcase(os.path.abspath(str(b))))
    except (OSError, ValueError):
        return False


def cmd_convert(args) -> int:
    rom_path = Path(args.rom)

    out_path = Path(args.output)
    manifest_path = out_path.with_suffix(out_path.suffix + ".manifest.json")
    consumed = [rom_path] + [Path(t) for t in (args.source_tables,
                                               args.target_tables) if t]
    # --force means "replace the file you named", never "destroy the ROM you are
    # converting". A source ROM may be the only copy someone has of a board's
    # contents, and there is no version of this tool's job that requires
    # overwriting it -- so this check sits ahead of --force rather than under it.
    for label, candidate in (("output", out_path), ("manifest", manifest_path)):
        for supplied in consumed:
            if _same_file(supplied, candidate):
                print("refusing to convert: the %s path (%s) is an input to "
                      "this run (%s)" % (label, candidate, supplied),
                      file=sys.stderr)
                return 2

    rom = reads.read_bytes(rom_path)
    source, source_raw, source_path = _load_table(args.source_tables, "tms5200")
    target, target_raw, target_path = _load_table(args.target_tables, "tms5220")
    table = _load_layout(args, rom)

    try:
        truncate = _truncation_choice(args.truncate_last_byte)
    except ValueError as error:
        print("bad --truncate-last-byte: %s" % error, file=sys.stderr)
        return 2
    try:
        # allow_unterminated is passed through unconditionally: the CLI reports
        # the failure in its own words below, with the phrase extents and the
        # layout flags to check, which is more use than the library's message.
        out, results = patch_rom(rom, table, source, target,
                                 truncate_last_byte=truncate,
                                 allow_unterminated=True)
    except ValueError as error:
        print("%s" % error, file=sys.stderr)
        return 2
    stats = summarise(results)

    # Verify before writing: re-read the produced image and confirm that only
    # the declared phrase extents moved. A conversion that touched anything else
    # is a bug, and the user should not receive the file.
    if len(out) != len(rom):
        # An internal invariant broke. There is nothing the reader can fix, and
        # the one thing they must not do is treat a partial result as usable.
        print("refusing to write: the converted image changed length, which "
              "must never happen.\n"
              "  NO output files were produced. Do not burn anything from "
              "this run.\n"
              "  This is a bug in understudy, not something you did -- please "
              "report it with the command you ran.", file=sys.stderr)
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

    # Print the direction. The tool cannot tell which chip a ROM came from, so
    # supplying the two tables the wrong way round is a mistake it can only make
    # visible, not catch -- and a reversed conversion produces a plausible ROM.
    print("converting           %s -> %s   (lowest f0 %.1f Hz -> %.1f Hz)"
          % (source.name, target.name, source.lowest_f0_hz,
             target.lowest_f0_hz))
    if target.lowest_f0_hz < source.lowest_f0_hz:
        print("  note: the target reaches LOWER than the source. If you meant "
              "TMS5200 -> TMS5220,\n  the tables are the wrong way round.")
    print("phrases              %d" % stats["phrases"])
    print("frames               %d" % stats["frames"])
    print("frames at the pitch floor %d (%.1f%%)  -- cannot be reproduced"
          % (stats["frames_clamped"], stats["clamped_percent"]))
    print("frames pitch-approximated %d  -- nearest available period"
          % stats["frames_approximated"])
    if stats["phrases"] != stats["distinct_phrases"]:
        print("distinct phrases     %d  -- %d pointer(s) name a phrase another "
              "already names" % (stats["distinct_phrases"],
                                 stats["phrases"] - stats["distinct_phrases"]))
    print("bytes changed        %d of %d" % (stats["bytes_changed"], len(rom)))
    print("frame kinds preserved %d of %d  -- checked by re-parsing the output"
          % (stats["frame_kinds_preserved"], stats["frames"]))
    if "f0_error_hz" in stats:
        e = stats["f0_error_hz"]
        print("f0 error, unclamped frames: median %.2f Hz, max %.2f Hz  (n=%d)"
              % (e["median"], e["max"], e["frames"]))
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

    # SECOND CHECK, AFTER THE READS. The check at the top of this function runs
    # before anything has been read, so it can only know about the paths the user
    # named -- which is why `convert ... -o src/tms52xx/data/tms5220.json --force`
    # could replace a bundled coefficient table that this very run had loaded. By
    # here every read has been recorded, so ask the registry the same question
    # convert-set asks. Two layers, because one guard on a path is never enough:
    # the early one gives a good error before doing work, this one is the true one.
    for label, candidate in (("output", out_path), ("manifest", manifest_path)):
        for supplied in reads.consumed():
            if _same_file(supplied, candidate):
                print("refusing to convert: the %s path (%s) is a file this run "
                      "reads (%s). Choose a different --output."
                      % (label, candidate, supplied), file=sys.stderr)
                return 2

    if out_path.exists() and not args.force:
        print("refusing to overwrite %s (pass --force)" % out_path,
              file=sys.stderr)
        return 2
    if manifest_path.exists() and not args.force:
        print("refusing to overwrite %s (pass --force)" % manifest_path,
              file=sys.stderr)
        return 2

    manifest = {
        "schema_version": MANUAL_MANIFEST_SCHEMA_VERSION,
        "tool": "understudy",
        "understudy_version": __version__,
        "path": "manual",
        "input": {"path": str(rom_path), "sha256": _sha256(rom),
                  "bytes": len(rom)},
        "output": {"path": str(out_path), "sha256": _sha256(out),
                   "bytes": len(out)},
        # Hash the table FILES, not just their self-declared names. Two runs
        # with different tables that both call themselves "tms5220" would
        # otherwise produce indistinguishable manifests, which defeats the point
        # of writing one.
        "tables": {"source": source.name, "target": target.name,
                   "source_file": _table_origin(args.source_tables, "tms5200"),
                   "target_file": _table_origin(args.target_tables, "tms5220"),
                   "source_sha256": _sha256(source_raw),
                   "target_sha256": _sha256(target_raw),
                   "source_bundled": args.source_tables is None,
                   "target_bundled": args.target_tables is None,
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
        # `alias_of` is not decoration: without it the per-phrase rows cannot be
        # reconciled with the summary. When two commands name one phrase both
        # rows carry that phrase's counts, but the physical work happened once,
        # so the summary totals only the rows where alias_of is null.
        "phrase_rows": ("one row per pointer in the layout. A row with "
                        "alias_of set repeats an earlier row's phrase; the "
                        "bytes were converted once, and summary totals count "
                        "only rows with alias_of null."),
        "phrases": [{"index": r.phrase.index, "start": r.phrase.start,
                     "end": r.phrase.end, "frames": r.frames,
                     "clamped": r.clamped, "approximated": r.approximated,
                     "truncated": r.truncated,
                     "last_byte_truncated": r.last_byte_truncated,
                     "alias_of": r.alias_of,
                     "changed_bytes": r.changed_bytes,
                     "stopped_cleanly": r.stopped_cleanly}
                    for r in results],
    }
    # Both files, or neither. A manifest describing an image that was never
    # written is a lie about what happened, and an image with no manifest is
    # unauditable; `_publish` stages both before renaming either.
    try:
        _publish([(out_path, out),
                  (manifest_path,
                   json.dumps(manifest, indent=2).encode("utf-8"))])
    except PublishRollbackError as error:
        print("failed to write the output, AND could not fully restore what "
              "was there:\n%s" % error, file=sys.stderr)
        return 2
    except OSError as error:
        print("failed to write the output: %s\nNeither the ROM nor its manifest "
              "was created or replaced. Any leftover .part or .backup file is "
              "safe to delete." % error, file=sys.stderr)
        return 2
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


def _read_dump(path: Path) -> bytes:
    data = reads.read_bytes(path)
    if not data:
        raise ValueError("%s is empty" % path)
    return data


#: Suffixes that are never a ROM dump. Used only when EXPANDING a folder or a
#: zip, never when the user names a file: if someone points at a file directly
#: they mean it, whatever it is called.
#:
#: A blocklist rather than an allowlist, because dump extensions are whatever
#: the person who read the chip felt like -- .716, .532, .bin, .rom, .u4, none
#: at all. Guessing which are ROMs would drop real dumps; guessing which are
#: documentation drops, at worst, a file that would have been reported unused.
_NOT_A_DUMP = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".png", ".jpg",
               ".gif", ".xml", ".yml", ".yaml", ".csv", ".log", ".cfg", ".ini",
               ".doc", ".docx", ".zip", ".gz", ".7z", ".rar"}


def _looks_like_a_dump(name: str) -> bool:
    base = PurePosixPath(name.replace("\\", "/")).name
    if not base or base.startswith("."):
        return False
    if base.upper() in ("README", "READ.ME", "FILE_ID.DIZ", "LICENSE", "COPYING"):
        return False
    return PurePosixPath(base).suffix.lower() not in _NOT_A_DUMP


#: A speech ROM on this hardware is at most 8 KB. These bounds are three orders of
#: magnitude above anything real, and exist only so that pointing at the wrong
#: thing -- a backup folder, a zip of a whole drive, a crafted archive -- fails
#: with a sentence instead of exhausting memory. A 16 KB archive expanded to
#: 16 MB during review; nothing stopped it.
_MAX_ONE_INPUT = 8 * 1024 * 1024
_MAX_ALL_INPUTS = 64 * 1024 * 1024
_MAX_INPUT_COUNT = 512


def _expand_inputs(names):
    """Turn what the user typed into (label, data, guard, explicit) rows.

    Each argument may be a FILE, a FOLDER, or a ZIP. Pinball ROMs arrive as a
    zip far more often than as a tidy list of files, and "point at the folder"
    is what someone repairing a board actually wants to type.

    `label` names the row for output filenames and messages; `guard` is the real
    path that must not be overwritten (for a zip member, the zip itself);
    `explicit` records whether the user named this file personally. That last
    flag is the whole reason this returns rows instead of a dict: a file the
    user NAMED and which fits no socket is an error, because converting less
    than they asked for is worse than refusing. A file merely FOUND inside a
    folder or zip is not -- those legitimately hold the CPU ROMs, a README and
    whatever else, and complaining about them would make the easy path the one
    that fails.
    """
    rows = []
    opened = set()
    total = 0
    seen = 0

    def consider():
        """Count an entry BEFORE deciding whether to read it.

        The count used to be checked inside take(), i.e. only for entries that
        were accepted -- so a folder or archive of any size passed as long as most
        of its entries were skipped, which is exactly the shape that costs the
        most to enumerate. What has to be bounded is how much we look at, not how
        much we keep.
        """
        nonlocal seen
        seen += 1
        if seen > _MAX_INPUT_COUNT:
            raise ValueError(
                "more than %d files to look at. This is not a Squawk & Talk ROM "
                "set -- point at the folder holding the ROMs, not one above it."
                % _MAX_INPUT_COUNT)

    def take(label, data, guard, named):
        nonlocal total
        if len(data) > _MAX_ONE_INPUT:
            raise ValueError(
                "%s is %.1f MB. Speech ROMs on this hardware are at most 8 KB, so "
                "this is not one -- check you pointed at the right thing."
                % (label, len(data) / 1048576.0))
        total += len(data)
        if total > _MAX_ALL_INPUTS or len(rows) >= _MAX_INPUT_COUNT:
            raise ValueError(
                "too much data to be a Squawk & Talk ROM set (stopped at %d files, "
                "%.1f MB). Point at the folder holding the ROMs, not one above it."
                % (len(rows) + 1, total / 1048576.0))
        rows.append((label, data, guard, named))

    for name in names:
        path = Path(name)
        # PROTECTION IS EARNED BY BEING OPENED, not by yielding a usable ROW.
        # This used to be recorded inside take(), so an archive whose members were
        # all skipped -- a zip holding only README.txt -- was opened, read, and
        # left unguarded. `convert-set good.zip that-zip -o . --force` then
        # overwrote it with the manifest and exited 0.
        opened.add(path)
        reads.track(path)
        if path.is_dir():
            for found in path.iterdir():
                consider()
                if not found.is_file():
                    continue
                # Do not follow a symlink out of the folder we were pointed at.
                # Scanning is a convenience; reading files the user did not mean
                # to offer is not part of it.
                if found.is_symlink():
                    continue
                if _looks_like_a_dump(found.name):
                    # Registered only once we mean to READ it. Tracking every
                    # entry we merely looked at made an unread manifest sitting
                    # in the folder block a forced rerun into that folder.
                    opened.add(found)
                    reads.track(found)
                    # Check the size on the filesystem BEFORE reading it in.
                    if found.stat().st_size > _MAX_ONE_INPUT:
                        raise ValueError(
                            "%s is %.1f MB. Speech ROMs on this hardware are at "
                            "most 8 KB, so this is not one -- check you pointed "
                            "at the right thing."
                            % (found, found.stat().st_size / 1048576.0))
                    data = found.read_bytes()
                    if data:
                        take(str(found), data, found, False)
            continue
        if path.is_file() and zipfile.is_zipfile(path):
            # Size the CONTAINER before opening it: ZipFile() reads and builds the
            # whole central directory in its constructor, so a bound applied to
            # members afterwards is applied after the cost.
            reads.check_size(path, _MAX_ALL_INPUTS)
            try:
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        consider()
                        if info.is_dir() or not _looks_like_a_dump(info.filename):
                            continue
                        # Refuse on the DECLARED size before reading, so a crafted
                        # archive cannot spend the memory first and be refused after.
                        if info.file_size > _MAX_ONE_INPUT:
                            raise ValueError(
                                "%s in %s claims to be %.1f MB; speech ROMs are at "
                                "most 8 KB." % (info.filename, path,
                                                info.file_size / 1048576.0))
                        data = archive.read(info)
                        if data:
                            take(info.filename, data, path, False)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
                raise ValueError(
                    "%s looks like a zip but could not be read (%s). Try "
                    "extracting it yourself and pointing at the folder." % (path, exc))
            continue
        if path.is_file() and path.stat().st_size > _MAX_ONE_INPUT:
            raise ValueError(
                "%s is %.1f MB. Speech ROMs on this hardware are at most 8 KB."
                % (path, path.stat().st_size / 1048576.0))
        take(str(path), _read_dump(path), path, True)
    rows.sort(key=lambda r: r[0])      # deterministic order, after bounding
    if not rows:
        raise ValueError(
            "nothing that looks like a ROM dump was found in: %s\n"
            "  Folders are not searched recursively -- point at the folder that "
            "directly contains the files, not the one above it.\n"
            "  If your ROMs are still inside a .zip, point at the ZIP itself "
            "rather than the folder holding it -- scanning a folder does not "
            "look inside archives.\n"
            "  Files named README, or ending .txt .md .json and similar, are "
            "skipped when scanning. Name a file directly if you mean it."
            % ", ".join(str(n) for n in names))
    return rows, opened


def _labelled_inputs(names):
    """Expand, and refuse a name that appears twice.

    Both commands need this. `identify` used to build its dict with a
    comprehension, which silently kept the last of any duplicate pair -- so a
    zip holding two members called U4.bin identified cleanly and then printed a
    convert command that failed. A name that does not identify one file cannot
    be matched to a socket, and guessing which one was meant is not available.
    """
    rows, opened = _expand_inputs(names)
    files, consumed = {}, set(opened)
    for label, data, guard, _named in rows:
        if label in files:
            raise ValueError(
                "more than one input is called %r. Rename or separate them: a "
                "name that appears twice cannot be matched to a socket." % label)
        files[label] = data
        consumed.add(guard)
    return files, consumed


def _sockets_from_args(args, profile):
    """Map the files the user gave us onto the profile's sockets.

    Returns (dumps, sources): socket -> bytes, and socket -> the path it came
    from, so outputs can be named after their input.

    Either `--socket U4=file` explicitly, or by matching each file against the
    profile: by hash first, and only then by size. Size alone is not enough when
    two sockets take the same size device, so an ambiguous set is refused rather
    than guessed -- putting a dump in the wrong socket converts the wrong bytes.
    """
    from .profiles import sha256 as _sha

    dumps, sources = {}, {}
    if args.socket and args.dumps:
        raise ValueError(
            "give either positional dumps or --socket, not both. Mixing them "
            "silently ignored the positional files.")
    if args.socket:
        for item in args.socket:
            if "=" not in item:
                raise ValueError("--socket wants SOCKET=PATH, got %r" % item)
            socket, path = item.split("=", 1)
            if profile.device_for(socket) is None:
                raise ValueError("socket %r is not in the %s profile"
                                 % (socket, profile.id))
            if socket in dumps:
                raise ValueError("socket %r given twice" % socket)
            dumps[socket] = _read_dump(Path(path))
            sources[socket] = path
        # Every path READ, keyed by nothing -- the preflight needs the set of
        # files on disk this run touched, and an earlier version keyed it by
        # socket while the caller looked it up by source filename, so the
        # guard list came out wrong whenever the two differed.
        return dumps, sources, {Path(v) for v in sources.values()}

    if not args.dumps:
        raise ValueError("no dumps given")

    rows, opened = _expand_inputs(args.dumps)
    files, consumed, explicit = {}, set(opened), set()
    for label, data, guard, was_named in rows:
        if label in files:
            # Two members with the same name, or two archives sharing one. Either
            # way the label no longer identifies a file, and silently keeping one
            # would convert something the user cannot see.
            raise ValueError(
                "more than one input is called %r. Rename or separate them: a "
                "name that appears twice cannot be matched to a socket." % label)
        files[label] = data
        consumed.add(guard)
        if was_named:
            explicit.add(label)
    digests = {name: _sha(data) for name, data in files.items()}
    taken = set()

    # Hash matches first, across all devices, so a size guess can never take a
    # file that some other socket can identify exactly.
    for device in profile.devices:
        if not device.sha256:
            continue
        hit = [n for n, d in digests.items()
               if d == device.sha256 and n not in taken]
        if hit:
            dumps[device.socket] = files[hit[0]]
            sources[device.socket] = hit[0]
            taken.add(hit[0])

    for device in profile.devices:
        if device.socket in dumps:
            continue
        candidates = [n for n, data in files.items()
                      if len(data) == device.size and n not in taken]
        if len(candidates) == 1:
            dumps[device.socket] = files[candidates[0]]
            sources[device.socket] = candidates[0]
            taken.add(candidates[0])
        elif not candidates:
            raise ValueError(
                "nothing supplied fits socket %s of the %s profile.\n"
                "  That socket holds a %s, %d bytes. Nothing you gave me is that "
                "size, so either the chip has not been read yet -- several of "
                "these games hold speech in TWO devices -- or it was read with "
                "the wrong device type selected, which changes the size."
                % (device.socket, profile.id, device.device_type, device.size))
        else:
            raise ValueError(
                "cannot tell which file belongs in socket %s: %d files are %d "
                "bytes and none matches the profile's hash. Name it explicitly "
                "with --socket %s=PATH."
                % (device.socket, len(candidates), device.size, device.socket))

    # Every file the user named must have gone somewhere. Silently dropping one
    # converts less than they asked for and leaves it out of the manifest, which
    # is the record of what was done.
    # Only files the user NAMED have to land somewhere. One they named and which
    # fits no socket is an error: converting less than they asked for, silently,
    # is worse than refusing. Files merely FOUND inside a folder or zip are a
    # different case -- a Squawk & Talk zip holds the CPU ROMs too, and the whole
    # point of accepting a folder is that the user does not have to know which
    # files are the speech ones.
    unused = [n for n in files if n not in taken and n in explicit]  # noqa: E501
    if unused:
        # Suggesting --socket here used to invite assigning a CPU ROM to a speech
        # socket, which converts the wrong bytes. The likely truth is simpler:
        # these are the board's other ROMs, and pointing at the folder ignores
        # them instead of refusing.
        raise ValueError(
            "these files are not part of the %s speech set: %s\n"
            "  They are probably the board's CPU ROMs. Either leave them out, or "
            "point at the whole folder -- understudy ignores what it does not "
            "need:\n"
            "    %s convert-set FOLDER"
            % (profile.id,
               ", ".join(PurePosixPath(n).name for n in unused),
               invocation()))
    return dumps, sources, consumed


def cmd_chips(args) -> int:
    from .chips import describe
    print(describe())
    return 0


def cmd_notices(args) -> int:
    """The bundled data is BSD-3-Clause; its notice must be reachable."""
    from .chips import notices
    text = notices()
    if not text:
        print("no third-party notice found beside the bundled data -- this "
              "install is incomplete", file=sys.stderr)
        return 2
    print(text)
    return 0


def cmd_profiles(args) -> int:
    from . import profiles as profile_mod
    found = profile_mod.available()
    if not found:
        print("no profiles bundled")
        return 0
    print("%-12s %-26s %-17s %7s  %s"
          % ("id", "title", "status", "phrases", "game revisions covered"))
    for profile in found:
        print("%-12s %-26s %-17s %7d  %s"
              % (profile.id, profile.label, profile.status, profile.phrases,
                 len(profile.revisions)))
    total = sum(len(p.revisions) for p in found)
    print("\n%d profile(s), covering %d game revision(s). Coverage is counted in"
          % (len(found), total))
    print("distinct SOUND ROM sets: revisions of one game usually share their")
    print("sound ROMs, so one profile serves all of them.")
    print("\nA profile is chosen only on an exact hash match of every "
          "speech-bearing\ndevice. Anything less is reported and refused -- see "
          "`%s identify`." % invocation())
    return 0


def cmd_identify(args) -> int:
    from . import profiles as profile_mod

    # Same expansion as convert-set: a folder or a zip is a perfectly ordinary
    # thing to point at, and identify is usually the FIRST command anyone runs.
    files, _consumed = _labelled_inputs(args.dumps)

    print("Supplied dumps")
    for name, data in files.items():
        print("  %-34s %6d bytes  sha256 %s"
              % (Path(name).name, len(data), profile_mod.sha256(data)[:32]))

    matches = profile_mod.identify(files)
    print()
    if not matches:
        print("No bundled profile recognises any of these.")
        print()
        print("That is not a failure -- it means this set is not one of the")
        print("revisions shipped with this version. Use the manual path:")
        print("  %s inspect <image> --table-offset ... --phrases ..."
              % invocation())
        print("and see docs/SQUAWK_AND_TALK.md for how to find the layout.")
        print("If you work it out, please contribute a profile:")
        print("  docs/CONTRIBUTING_PROFILES.md")
        return 1

    complete = [m for m in matches if m.complete]
    for match in matches:
        profile = match.profile
        mark = "MATCH  " if match.complete else "partial"
        print("%s %s  (profile %s v%d, status %s)"
              % (mark, profile.label, profile.id, profile.version,
                 profile.status))
        for socket, name in sorted(match.matched.items()):
            print("           %-4s <- %s" % (socket, Path(name).name))
        for socket in match.missing:
            device = profile.device_for(socket)
            print("           %-4s -- no supplied file matches (%s, %d bytes)"
                  % (socket, device.device_type, device.size))
        for socket in match.unsupplied:
            if socket in match.missing:
                continue
            device = profile.device_for(socket)
            print("           %-4s -- not supplied; holds no speech, but is "
                  "burned too (%s, %d bytes)"
                  % (socket, device.device_type, device.size))

    print()
    if len(complete) == 1:
        match = complete[0]
        profile = match.profile
        print("Identified: %s" % profile.label)
        if len(profile.revisions) > 1:
            print("  (this sound ROM set is shared by %d game revisions: %s)"
                  % (len(profile.revisions), ", ".join(profile.revisions)))
        if not match.burnable:
            # The speech ROMs identify the set; they are not the whole set.
            # Printing a convert-set command here would hand over something
            # that fails on the next line.
            print()
            print("This identifies the SPEECH ROMs, but the set is not complete:")
            for socket in match.unsupplied:
                device = profile.device_for(socket)
                print("  %-4s is missing (%s, %d bytes). It holds no speech, but"
                      % (socket, device.device_type, device.size))
                print("       convert-set authenticates and emits every device,")
                print("       so it needs that dump too.")
            print()
            print("Dump the remaining device(s) and run identify again.")
            return 1
        print()
        # THE SHORTEST COMMAND THAT WORKS. Every flag this used to print is a
        # default: the set is identified by hash, the target defaults to the
        # TMS5220, and the output directory is made for you. Printing them
        # taught everyone that four flags were required, which is the opposite
        # of what the tool does -- and the person reading this is usually
        # holding a soldering iron, not looking for options.
        # ECHO BACK WHAT THEY TYPED -- unless they named plain files and some of
        # them are not part of the set.
        #
        # Printing the names discovered inside a folder or zip produces a command
        # that does not run: they are relative to the archive, not to where the
        # user is standing. But echoing the arguments verbatim has its own trap --
        # `identify a.bin b.bin cpu.bin` succeeds, because identify only has to
        # recognise the speech ROMs, and then suggests a convert-set that refuses
        # cpu.bin. Naming a file is a claim it belongs in the set, and convert-set
        # holds the user to it. So when every argument is a plain file, suggest
        # only the ones this match actually used.
        used = list(match.matched.values()) + list(match.incidental.values())
        if args.dumps and all(Path(d).is_file() and not zipfile.is_zipfile(Path(d))
                              for d in args.dumps) and used:
            suggest = [str(u) for u in used]
        else:
            suggest = [str(given) for given in args.dumps]
        print("Convert it with:")
        print("  %s convert-set %s"
              % (invocation(), " ".join(shell_quote(x) for x in suggest)))
        if profile.status != "silicon-verified":
            print()
            print("Note: this profile is %r. No converted ROM from it has been"
                  % profile.status)
            print("played on a real board yet. See docs/HARDWARE_VALIDATION.md.")
        return 0
    if len(complete) > 1:
        print("REFUSING TO CHOOSE: %d profiles match completely (%s)."
              % (len(complete), ", ".join(m.profile.id for m in complete)))
        print("Name the one you want with --game.")
        return 2
    print("No profile matches completely, so none will be used automatically.")
    print("A partial match usually means a different revision, or a device")
    print("that was read with the wrong type selected. Check the read first;")
    print("if the set really is a new revision, the manual path still works.")
    return 1


def cmd_convert_set(args) -> int:
    from . import profiles as profile_mod
    from .chips import resolve as resolve_chip
    from .workflow import ConversionRefused, convert_set, output_name

    if args.game:
        profile = profile_mod.get(args.game)
    else:
        files, _consumed = _labelled_inputs(args.dumps)
        matches = [m for m in profile_mod.identify(files) if m.complete]
        if len(matches) != 1:
            # GIVE THEM A COMMAND THEY CAN RUN. The old message named `identify`
            # without the files, so copying it produced a usage error -- and it
            # asserted "not a supported game", which is only one of three causes.
            # A half-dumped set and a bad read look identical from here, and the
            # person reading this has a machine in pieces.
            given = " ".join(shell_quote(str(d)) for d in args.dumps)
            if len(matches) > 1:
                print("error: %d profiles match this set. Choose one with "
                      "--game NAME." % len(matches), file=sys.stderr)
                return 2
            print("error: this does not match any game understudy knows.\n"
                  "  See exactly what was found and what was expected:\n"
                  "    %s identify %s\n"
                  "  Three things cause this, and they look the same from here:\n"
                  "    - the game is not one of the %d covered  (%s profiles)\n"
                  "    - a device is missing: some games hold speech in TWO chips\n"
                  "    - a ROM was read with the wrong device type selected\n"
                  "  If you already know the game, name it: --game NAME"
                  % (invocation(), given,
                     len(profile_mod.available()), invocation()),
                  file=sys.stderr)
            return 2
        profile = matches[0].profile
        print("identified   %s (profile %s v%d)"
              % (profile.label, profile.id, profile.version))

    target = resolve_chip(args.target)
    if target.role not in ("target", "both"):
        print("error: %s is not a replacement part" % target.id, file=sys.stderr)
        return 2

    dumps, sources, consumed = _sockets_from_args(args, profile)
    try:
        result = convert_set(
            dumps, profile, target,
            source_tables=Path(args.source_tables) if args.source_tables else None,
            target_tables=Path(args.target_tables) if args.target_tables else None,
            allow_unterminated=args.allow_unterminated,
            allow_unverified_rate_control=getattr(
                args, "allow_unverified_rate_control", False))
    except ConversionRefused as error:
        print("refusing to convert: %s" % error, file=sys.stderr)
        return 2

    outdir = Path(args.output)
    manifest_path = outdir / ("%s.manifest.json" % profile.id)

    # PREFLIGHT EVERYTHING BEFORE WRITING ANYTHING.
    #
    # Two failures this prevents, both of which were real. The manifest's name
    # is derived from the profile id, so it is a path a user can already hold --
    # and with --force it was written over an input dump, atomically, returning
    # success. And writing device files one at a time meant a refusal on the
    # second could leave the first behind, so a technician could burn a mixture
    # of new and stale images.
    #
    # So: compute every destination, check them all against every input and
    # against each other, then write. No destination is created until all of
    # them are known to be safe.
    plan = []
    for entry in result.outputs:
        device = profile.device_for(entry["socket"])
        # Name each output after the file it came from, looked up by SOCKET.
        # Matching on contents would name two sockets holding identical bytes
        # after the same input.
        origin = sources.get(entry["socket"])
        source_name = (PurePosixPath(str(origin).replace("\\", "/")).name if origin
                       else "%s_%s" % (profile.id, entry["socket"]))
        name = output_name(source_name, device, target, result.custom_tables)
        destination = outdir / name
        # DEFENCE IN DEPTH. The profile loader restricts socket and type to safe
        # identifiers, so a name should never contain a separator -- but this is
        # the step that decides where bytes land, and it is cheap to make the
        # containment a fact rather than a consequence of validation elsewhere.
        # `..` inside a single component is harmless; a component that IS `..`,
        # or any separator, is not.
        resolved = (outdir / name).resolve()
        if Path(name).name != name or not _within(resolved, outdir.resolve()):
            raise SystemExit(
                "refusing to write %r: the %s profile builds an output name "
                "that leaves the output directory. Its socket or device type "
                "contains a path separator." % (name, profile.id))
        plan.append((destination, entry))

    destinations = [path for path, _ in plan] + [manifest_path]

    # EVERY file this run consumed, not only the ROM dumps. A custom
    # coefficient table or a profile is just as much an input, and just as
    # irreplaceable to whoever wrote it; an earlier version of this check
    # defined "input" as the dumps alone and would replace the others.
    # EVERY FILE THIS RUN READ, not merely the ones whose contents were used.
    #
    # This was `[guards.get(origin) for origin in sources.values()]` -- the files
    # backing the SELECTED sockets. Hand it two archives where only the first
    # supplies the sockets and the second is read and discarded, and the second
    # was unprotected: `convert-set good.zip notes.zip -o . --force` overwrote
    # notes.zip with the manifest. Reading a file is what earns it protection.
    # ASK ONE PLACE. This list used to be assembled here from the pieces this
    # function happened to know about -- the dumps, the two --tables options, the
    # selected profile -- and it was incomplete four separate times. Every read in
    # the package now goes through tms52xx.reads, which records the path, so the
    # question "what did this run read" has one answer and it is not this
    # function's job to remember. The union with `consumed` keeps zip members,
    # whose bytes come out of zipfile rather than through a read helper.
    inputs = list(reads.consumed() | set(consumed))
    for destination in destinations:
        for supplied in inputs:
            if _same_file(supplied, destination):
                print("refusing to convert: %s would be written over a file "
                      "this run reads (%s). Choose a different --output "
                      "directory." % (destination, supplied), file=sys.stderr)
                return 2
    for i, first in enumerate(destinations):
        for second in destinations[i + 1:]:
            if _same_file(first, second):
                print("refusing to convert: two outputs resolve to the same "
                      "path (%s)" % first, file=sys.stderr)
                return 2
    if not args.force:
        existing = [d for d in destinations if d.exists()]
        if existing:
            print("refusing to overwrite %s (pass --force)"
                  % ", ".join(str(d) for d in existing), file=sys.stderr)
            return 2

    written = []
    if not args.dry_run:
        outdir.mkdir(parents=True, exist_ok=True)
        for path, entry in plan:
            entry["path"] = str(path)
        for entry, manifest_entry in zip(result.outputs,
                                         result.manifest["outputs"]):
            manifest_entry["path"] = entry.get("path")

        payloads = [(path, entry["data"]) for path, entry in plan]
        payloads.append((manifest_path,
                         json.dumps(result.manifest, indent=2).encode("utf-8")))
        try:
            _publish(payloads)
        except PublishRollbackError as error:
            print("failed to write the output set, AND could not fully restore "
                  "what was there:\n%s" % error, file=sys.stderr)
            return 2
        except OSError as error:
            print("failed to write the output set: %s\nNo file in %s was "
                  "created or replaced. Cleanup of the temporary files is "
                  "best-effort: if any remain they end in .part or .backup and "
                  "are safe to delete." % (error, outdir), file=sys.stderr)
            return 2
        written = [(path, entry) for path, entry in plan]

    _print_set_summary(result, profile, target, written, args)
    if not args.dry_run:
        print("manifest     %s" % manifest_path)
    return 0


def _print_set_summary(result, profile, target, written, args) -> None:
    """The block a technician reads before burning anything."""
    stats = result.stats
    print()
    print("=" * 68)
    print("  CHECK THIS BEFORE YOU BURN ANYTHING")
    print("=" * 68)
    print("profile      %s  (%s v%d, status %s)"
          % (profile.label, profile.id, profile.version, profile.status))
    print("chips        %s  ->  %s" % (result.source_chip.id, target.id))
    tables = result.manifest["tables"]
    print("tables       source %s / target %s  (%s)"
          % (tables["source"]["sha256"][:12], tables["target"]["sha256"][:12],
             "bundled" if tables["target"]["bundled"] else "custom"))
    print()
    print("input dumps")
    for entry in result.inputs.values():
        flag = "" if entry["matches_profile"] is not False else "  MISMATCH"
        print("  %-4s %-8s %6d bytes  sha256 %s%s"
              % (entry["socket"], entry["device_type"], entry["bytes"],
                 entry["sha256"][:24], flag))
    print()
    print("conversion")
    print("  phrases                %d" % stats["phrases"])
    print("  frames                 %d" % stats["frames"])
    print("  frame kinds preserved  %d of %d"
          % (stats["frame_kinds_preserved"], stats["frames"]))
    print("  clamped to pitch floor %d (%.1f%%)"
          % (stats["frames_clamped"], stats["clamped_percent"]))
    if "f0_error_hz" in stats:
        err = stats["f0_error_hz"]
        print("  f0 error, unclamped    median %.2f Hz, max %.2f Hz"
              % (err["median"], err["max"]))
    print("  bytes changed          %d" % stats["bytes_changed"])
    print()
    print("output devices")
    for entry in result.outputs:
        note = {"mirror": "  (taken from the mirror half)",
                "merged": "  (merged from both mirror windows)",
                "lower": ""}.get(entry.get("source_window", "lower"), "")
        if not entry["changed"]:
            note = "  (unchanged - holds no speech)"
        coverage = entry.get("speech_coverage_percent")
        # Says what is measured. It is the share of the PHYSICAL device that the
        # phrases actually consume, counted to each one's stop frame -- not the
        # share their declared extents span, which on one real set called a
        # device 100% speech when a quarter of it is something else.
        share = ("  %.0f%% converted" % coverage
                 if coverage is not None else "")
        print("  %-4s %-8s %6d bytes  %d changed%s%s"
              % (entry["socket"], entry["device_type"], entry["bytes"],
                 entry["changed_bytes"], share, note))
        if entry.get("path"):
            print("       burn into %s: %s"
                  % (entry["device_type"], entry["path"]))
    # TWO DIFFERENT COUNTS, AND THEY NEED NOT BE EQUAL.
    #
    # `changed_bytes` is per PHYSICAL device. `stats["bytes_changed"]` counts
    # the assembled CPU image, where a mirrored device appears twice -- so a
    # layout that reaches the same physical byte through both windows changes
    # two image bytes and one device byte. Printing "A == B" asserted an
    # equality that is false exactly when mirrors are in play, in a summary
    # whose whole purpose is that the numbers reconcile.
    device_total = sum(e["changed_bytes"] for e in result.outputs)
    window_total = sum(e.get("window_changed_bytes", e["changed_bytes"])
                       for e in result.outputs)
    print()
    print("  bytes changed          %d across the physical devices"
          % device_total)
    print("  reconciliation         %d in the CPU image == %d across the "
          "device windows" % (stats["bytes_changed"], window_total))
    if window_total != device_total:
        print("                         (a mirrored device answers at two "
              "addresses, so the")
        print("                          image counts %d byte(s) the device "
              "holds once)" % (window_total - device_total))
    low = [e for e in result.outputs
           if (e.get("speech_coverage_percent") or 100) < 20]
    if low:
        print()
        print("  NOTE: only %s of %s is speech this layout converts."
              % (", ".join("%.0f%%" % e["speech_coverage_percent"] for e in low),
                 ", ".join(e["socket"] for e in low)))
        print("  A correct layout usually reaches most of a speech device. A"
              " small figure here means")
        print("  the layout is finding a corner of the speech and leaving the"
              " rest unconverted --")
        print("  which still boots and still sounds wrong. Check the layout"
              " before burning.")

    if result.warnings:
        print()
        print("warnings")
        for warning in result.warnings:
            print("  - %s" % warning)
    if args.dry_run:
        print()
        print("dry run: nothing written")
    print("=" * 68)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=invocation(),
        description="Convert TMS5200 speech data in a Squawk & Talk ROM so it "
                    "plays on a TMS5220.")
    parser.add_argument("--version", action="version",
                        version="understudy %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="report on a ROM; writes nothing")
    inspect.add_argument("rom")
    inspect.add_argument("--source-tables", default=None,
                         help="tables used to parse frames for the final-byte "
                              "report; defaults to the bundled TMS5200 set")
    inspect.add_argument("--no-tables", action="store_true",
                         help="skip the final-byte report entirely")
    _add_layout_args(inspect, required=False)
    inspect.set_defaults(func=cmd_inspect)

    convert = sub.add_parser("convert", help="write a converted copy of a ROM")
    convert.add_argument("rom")
    convert.add_argument("-o", "--output", required=True)
    convert.add_argument("--source-tables", default=None,
                         help="table file; defaults to the bundled TMS5200 set")
    convert.add_argument("--target-tables", default=None,
                         help="table file; defaults to the bundled TMS5220 set")
    convert.add_argument("--truncate-last-byte", nargs="?", const="all",
                         metavar="ALL|N,N,...",
                         help="phrases whose final ROM byte the player never "
                              "transmits, so it must be left untouched. Bare "
                              "flag means every phrase; otherwise a list of "
                              "phrase indexes. `inspect --source-tables` "
                              "reports which phrases it is SAFE for; whether it "
                              "is needed depends on your player's firmware")
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

    # -- the short path ---------------------------------------------------
    identify = sub.add_parser(
        "identify", help="say which game a set of socket dumps is, if known")
    identify.add_argument("dumps", nargs="+",
                          help="one file per ROM device, in any order")
    identify.set_defaults(func=cmd_identify)

    convert_set_p = sub.add_parser(
        "convert-set",
        help="convert a whole ROM set: socket dumps in, replacement device "
             "images out")
    convert_set_p.add_argument("dumps", nargs="*",
                               help="one file per ROM device, in any order")
    convert_set_p.add_argument("--game", default=None,
                               help="profile id; omit to identify by hash")
    convert_set_p.add_argument("--target", default="tms5220",
                               help="replacement part (see `understudy chips`)")
    convert_set_p.add_argument("-o", "--output", default="understudy-out",
                               help="directory for the converted devices")
    convert_set_p.add_argument("--socket", action="append", metavar="SOCKET=PATH",
                               help="name a file's socket explicitly; repeatable")
    convert_set_p.add_argument("--source-tables", default=None,
                               help="override the bundled source tables")
    convert_set_p.add_argument("--target-tables", default=None,
                               help="override the bundled target tables")
    convert_set_p.add_argument("--allow-unterminated", action="store_true",
                               help="convert phrases with no stop frame")
    convert_set_p.add_argument(
        "--i-have-checked-this-firmware-never-sets-the-rate",
        dest="allow_unverified_rate_control", action="store_true",
        help="convert for a TMS5220C/TSP5220C even though the profile does not "
             "record which commands its firmware sends. Those parts read the "
             "0x00/0x20 opcode as SET RATE where a TMS5200 ignores it, so this "
             "asserts something about the BOARD that this tool has not checked.")
    convert_set_p.add_argument("--dry-run", action="store_true")
    convert_set_p.add_argument("--force", action="store_true",
                               help="allow overwriting existing output files")
    convert_set_p.set_defaults(func=cmd_convert_set)

    chips = sub.add_parser("chips", help="list the parts this tool knows")
    chips.set_defaults(func=cmd_chips)

    profiles_p = sub.add_parser("profiles", help="list the bundled game profiles")
    profiles_p.set_defaults(func=cmd_profiles)

    notices = sub.add_parser(
        "notices", help="print the third-party licence notice for bundled data")
    notices.set_defaults(func=cmd_notices)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as error:
        # Layout and table problems are the expected failure of this tool, not
        # a crash: the user is guessing at a pointer table and will guess wrong
        # several times. A traceback buries the one line that helps them.
        print("error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
