"""Every file this process reads, and a bound on how much of it.

WHY THIS EXISTS. Understudy writes files next to files it has just read, and it
must never write over one of them. That guard was built by collecting the inputs
each code path happened to know about, and it was wrong four times in a row, in
four different ways: a zip whose members were all selected, then one whose
members were not, then one that yielded no members at all, then the profile
directory and the bundled coefficient tables -- all read during a run, none on
the list, each overwritable by pointing `-o` at them with `--force`.

The bug was never in any of those paths. It was that "what did this run read"
was an answer several places assembled separately and none of them owned. So it
is answered here instead: every read in the package goes through this module,
which records the path before returning the bytes. The preflight then asks one
question of one place.

The size bound lives here for the same reason. It was applied at the folder and
archive paths, which is where untrusted input was expected to arrive, and not at
the explicitly named file, the --socket path, the manual ROM, the custom
coefficient table or the profile -- all of which are read just as readily. A
limit that only some callers remember to apply is a limit that does not exist.

Nothing here is a security boundary against a hostile local user: a file can
change between the check and the read, and that race is not what this defends
against. It defends against pointing the tool at the wrong thing and losing
work, which is the failure that actually happens.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Set

#: A speech ROM on this hardware is at most 8 KB, a coefficient table a few KB of
#: JSON, a profile smaller still. 8 MB is three orders of magnitude above any of
#: them: large enough never to obstruct real use, small enough that pointing at a
#: disk image fails with a sentence instead of a memory error.
MAX_FILE_BYTES = 8 * 1024 * 1024

_lock = threading.Lock()
_consumed: Set[Path] = set()


class TooLarge(ValueError):
    """A file is far larger than anything this tool legitimately reads."""


def reset() -> None:
    """Forget what has been read. For tests; a CLI run is one process."""
    with _lock:
        _consumed.clear()


def consumed() -> Set[Path]:
    """Every path read so far, resolved where possible.

    Resolved, because the preflight compares against output destinations and
    `roms/../roms/u4.bin` is the same file as `roms/u4.bin`. A path that cannot
    be resolved is kept as given rather than dropped -- an unresolvable input is
    exactly the one worth being careful with.
    """
    with _lock:
        return set(_consumed)


def track(path) -> Path:
    """Record a path as read, without reading it.

    For content that is read by something other than this module -- a zip member
    comes out of `zipfile`, not `Path.read_bytes` -- where the archive itself is
    still a file this run opened and must not be written over.
    """
    p = Path(path)
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p
    with _lock:
        _consumed.add(resolved)
    return p


def check_size(path, limit: int = MAX_FILE_BYTES) -> None:
    """Refuse an oversized file BEFORE its contents are read.

    Checked against the filesystem rather than after loading, because measuring
    afterwards means the memory has already been spent -- which is the whole
    thing a limit is for. Only regular files can be measured this way; a FIFO or
    a device reports no meaningful size, so those are refused outright rather
    than read hopefully.
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return                      # let the real read raise the real error
    if not p.is_file():
        raise TooLarge(
            "%s is not a regular file. Understudy reads ROM images, coefficient "
            "tables and profiles from disk; a device or pipe is not one." % p)
    if st.st_size > limit:
        raise TooLarge(
            "%s is %.1f MB. Nothing this tool reads is that large -- a speech ROM "
            "here is at most 8 KB. Check you pointed at the right thing."
            % (p, st.st_size / 1048576.0))


def read_bytes(path, limit: int = MAX_FILE_BYTES) -> bytes:
    """Bounded read that records the path."""
    check_size(path, limit)
    data = Path(path).read_bytes()
    track(path)
    return data


def read_text(path, encoding: str = "utf-8", limit: int = MAX_FILE_BYTES) -> str:
    """Bounded read that records the path."""
    check_size(path, limit)
    text = Path(path).read_text(encoding=encoding)
    track(path)
    return text
