"""Game profiles: everything Understudy needs to convert a known ROM set.

A profile records the layout facts a conversion needs and that cannot be derived
from the data: where the pointer table is, how many phrases it holds, whether it
is address- or command-ordered, which sockets carry speech, and how each device
maps into the CPU's address space. It records **no ROM contents**. Device
hashes appear, because a hash identifies a dump without reproducing any of it.

IDENTIFICATION IS DELIBERATELY BLUNT

A profile is selected only when every speech-bearing device the profile lists is
present and its SHA-256 matches exactly. Anything else -- a partial match, a
right-sized file with the wrong hash, two profiles claiming the same dump -- is
reported and then refused. Converting with the wrong layout produces a file of
the right length that is silently wrong, so guessing is worse than stopping.

`identify` therefore returns candidates and a verdict, never a silent choice.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

BUNDLED_PROFILE_DIR = Path(__file__).resolve().parent / "data" / "profiles"

#: Set UNDERSTUDY_PROFILE_DIR to work on a profile before submitting it. The
#: contributing guide relies on this; so does the test suite.
PROFILE_ENV = "UNDERSTUDY_PROFILE_DIR"


def profile_dir() -> Path:
    override = os.environ.get(PROFILE_ENV)
    return Path(override) if override else BUNDLED_PROFILE_DIR

#: Bumped when the on-disk shape changes in a way older readers cannot handle.
SCHEMA_VERSION = 1

#: How far a profile has been taken. Only "silicon-verified" means someone has
#: played the converted ROM on a real board.
STATUS_VALUES = ("draft", "layout-verified", "emulator-verified",
                 "silicon-verified")


class ProfileError(ValueError):
    """A profile file is malformed, or does not describe what it claims to."""


class Device:
    """One ROM device in one socket."""

    def __init__(self, raw: dict, where: str) -> None:
        def need(key, kind, what):
            if key not in raw:
                raise ProfileError("%s: device is missing %r" % (where, key))
            if not isinstance(raw[key], kind) or isinstance(raw[key], bool):
                raise ProfileError("%s: device %r must be %s"
                                   % (where, key, what))
            return raw[key]

        self.socket = need("socket", str, "a string")
        self.device_type = need("type", str, "a string")
        self.size = need("size", int, "an integer")
        self.cpu_address = need("cpu_address", int, "an integer")
        self.mirrored = bool(raw.get("mirrored", False))
        self.holds_speech = bool(raw.get("holds_speech", False))
        self.sha256 = raw.get("sha256")
        self.label = raw.get("label")

        if self.size <= 0:
            raise ProfileError("%s: device %s has size %d"
                               % (where, self.socket, self.size))
        if self.sha256 is not None:
            if not isinstance(self.sha256, str) or len(self.sha256) != 64:
                raise ProfileError("%s: device %s has a malformed sha256"
                                   % (where, self.socket))
            self.sha256 = self.sha256.lower()

    def as_dict(self) -> dict:
        return {"socket": self.socket, "type": self.device_type,
                "size": self.size, "cpu_address": self.cpu_address,
                "mirrored": self.mirrored, "holds_speech": self.holds_speech,
                "sha256": self.sha256, "label": self.label}


class Profile:
    """A parsed, validated profile."""

    def __init__(self, raw: dict, where: str = "<profile>") -> None:
        self.source = where
        self.raw = raw

        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ProfileError(
                "%s: schema_version is %r, this Understudy understands %d"
                % (where, version, SCHEMA_VERSION))

        for key in ("profile_id", "profile_version", "title", "source_chip",
                    "status", "memory", "layout", "devices"):
            if key not in raw:
                raise ProfileError("%s: missing required field %r"
                                   % (where, key))

        self.id = raw["profile_id"]
        self.version = raw["profile_version"]
        self.title = raw["title"]
        self.manufacturer = raw.get("manufacturer")
        self.year = raw.get("year")
        self.board = raw.get("board")
        self.source_chip = raw["source_chip"]
        self.status = raw["status"]
        self.notes = list(raw.get("notes", []))
        self.evidence = dict(raw.get("evidence", {}))
        self.chip_commands_observed = list(raw.get("chip_commands_observed", []))

        if self.status not in STATUS_VALUES:
            raise ProfileError("%s: status %r is not one of %s"
                               % (where, self.status, ", ".join(STATUS_VALUES)))

        memory = raw["memory"]
        self.window_base = memory["window_base"]
        self.window_size = memory["window_size"]
        self.fill = memory.get("fill", 0xFF)
        if not isinstance(self.window_size, int) or self.window_size <= 0:
            raise ProfileError("%s: memory.window_size must be positive" % where)
        if not 0 <= self.fill <= 0xFF:
            raise ProfileError("%s: memory.fill must be a byte" % where)

        layout = raw["layout"]
        for key in ("table_offset", "phrases", "base_address",
                    "address_ordered", "has_end_bound"):
            if key not in layout:
                raise ProfileError("%s: layout is missing %r" % (where, key))
        self.table_offset = layout["table_offset"]
        self.phrases = layout["phrases"]
        self.base_address = layout["base_address"]
        self.address_ordered = bool(layout["address_ordered"])
        self.has_end_bound = bool(layout["has_end_bound"])
        self.truncate_last_byte = list(layout.get("truncate_last_byte", []))
        if not isinstance(self.phrases, int) or self.phrases < 1:
            raise ProfileError("%s: layout.phrases must be at least 1" % where)
        for index in self.truncate_last_byte:
            if not isinstance(index, int) or not 0 <= index < self.phrases:
                raise ProfileError(
                    "%s: truncate_last_byte lists %r, which is not a phrase "
                    "index in 0..%d" % (where, index, self.phrases - 1))

        self.devices = [Device(d, where) for d in raw["devices"]]
        if not self.devices:
            raise ProfileError("%s: no devices listed" % where)

        seen = set()
        for device in self.devices:
            if device.socket in seen:
                raise ProfileError("%s: socket %s listed twice"
                                   % (where, device.socket))
            seen.add(device.socket)
            offset = device.cpu_address - self.window_base
            span = device.size * (2 if device.mirrored else 1)
            if offset < 0 or offset + span > self.window_size:
                raise ProfileError(
                    "%s: device %s at 0x%04X (%d bytes%s) does not fit the "
                    "0x%04X-byte window based at 0x%04X"
                    % (where, device.socket, device.cpu_address, device.size,
                       ", mirrored" if device.mirrored else "",
                       self.window_size, self.window_base))

        if not self.speech_devices:
            raise ProfileError("%s: no device is marked holds_speech" % where)

    # -- convenience ------------------------------------------------------
    @property
    def speech_devices(self) -> List[Device]:
        return [d for d in self.devices if d.holds_speech]

    @property
    def identifiable(self) -> bool:
        """Can every speech device be matched by hash?"""
        return all(d.sha256 for d in self.speech_devices)

    @property
    def label(self) -> str:
        bits = [self.title]
        if self.manufacturer:
            bits.insert(0, self.manufacturer)
        if self.year:
            bits.append("(%d)" % self.year)
        return " ".join(bits)

    def device_for(self, socket: str) -> Optional[Device]:
        for device in self.devices:
            if device.socket == socket:
                return device
        return None

    def assemble(self, dumps: Dict[str, bytes]) -> bytes:
        """Build the CPU's view of the sockets from per-device dumps.

        `dumps` maps socket name to the bytes read from that device. Mirroring
        is applied here, so callers never do it by hand.
        """
        image = bytearray(bytes([self.fill]) * self.window_size)
        for device in self.devices:
            data = dumps.get(device.socket)
            if data is None:
                continue
            if len(data) != device.size:
                raise ProfileError(
                    "socket %s: dump is %d bytes, profile says the %s there is "
                    "%d" % (device.socket, len(data), device.device_type,
                            device.size))
            at = device.cpu_address - self.window_base
            image[at:at + device.size] = data
            if device.mirrored:
                image[at + device.size:at + 2 * device.size] = data
        if len(image) != self.window_size:
            raise ProfileError("assembled image is %d bytes, expected %d"
                               % (len(image), self.window_size))
        return bytes(image)

    def extract(self, image: bytes, device: Device,
                original: bytes) -> "DeviceResult":
        """Pull one device's replacement contents back out of a patched image.

        Returns which window was taken and whether it changed. A mirrored
        device is the awkward case: conversion rewrites whatever the pointers
        addressed, which may be the mirror rather than the lower copy, so the
        half that actually changed is the one to burn.
        """
        at = device.cpu_address - self.window_base
        windows = [(at, at + device.size)]
        if device.mirrored:
            windows.append((at + device.size, at + 2 * device.size))

        changed = [w for w in windows if image[w[0]:w[1]] != original[w[0]:w[1]]]
        if len(changed) > 1:
            raise ProfileError(
                "socket %s: both mirror halves changed, which one device "
                "cannot represent -- the layout is wrong" % device.socket)
        lo, hi = changed[0] if changed else windows[0]
        return DeviceResult(device=device, data=bytes(image[lo:hi]),
                            window=(lo, hi), changed=bool(changed),
                            from_mirror=bool(changed) and changed[0] is windows[-1]
                            and device.mirrored)


class DeviceResult:
    """One device's converted contents, and where they came from."""

    def __init__(self, device: Device, data: bytes, window, changed: bool,
                 from_mirror: bool) -> None:
        self.device = device
        self.data = data
        self.window = window
        self.changed = changed
        self.from_mirror = from_mirror


# -- loading --------------------------------------------------------------

def load_file(path) -> Profile:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProfileError("%s is not valid JSON: %s" % (path, error))
    if not isinstance(raw, dict):
        raise ProfileError("%s must contain a JSON object" % path)
    return Profile(raw, str(path))


def available(directory=None) -> List[Profile]:
    """Every bundled profile that parses. A broken one raises rather than
    being skipped -- a profile silently missing is how the wrong one gets
    picked."""
    directory = Path(directory) if directory else profile_dir()
    if not directory.exists():
        return []
    return [load_file(p) for p in sorted(directory.glob("*.json"))]


def get(profile_id: str, directory=None) -> Profile:
    for profile in available(directory):
        if profile.id == profile_id:
            return profile
    known = ", ".join(p.id for p in available(directory)) or "none bundled"
    raise ProfileError("no profile %r. Known: %s" % (profile_id, known))


# -- identification -------------------------------------------------------

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Match:
    """How well one profile explains a set of dumps."""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        #: socket -> the supplied file whose hash matched
        self.matched: Dict[str, str] = {}
        #: sockets whose speech device the profile knows but nothing matched
        self.missing: List[str] = []
        #: files that matched a non-speech device
        self.incidental: Dict[str, str] = {}

    @property
    def complete(self) -> bool:
        return not self.missing and bool(self.matched)

    def __repr__(self) -> str:
        return "Match(%s, %d matched, %d missing)" % (
            self.profile.id, len(self.matched), len(self.missing))


def identify(files: Dict[str, bytes], directory=None) -> List[Match]:
    """Match supplied dumps against every bundled profile, by hash only.

    `files` maps a display name (usually a path) to its contents. Returns one
    Match per profile that explained at least one speech device, best first.
    The caller decides what to do; this never picks.
    """
    digests = {name: sha256(data) for name, data in files.items()}
    matches = []
    for profile in available(directory):
        match = Match(profile)
        for device in profile.devices:
            if not device.sha256:
                continue
            hit = [n for n, d in digests.items() if d == device.sha256]
            if hit:
                if device.holds_speech:
                    match.matched[device.socket] = hit[0]
                else:
                    match.incidental[device.socket] = hit[0]
            elif device.holds_speech:
                match.missing.append(device.socket)
        if match.matched:
            matches.append(match)
    matches.sort(key=lambda m: (not m.complete, len(m.missing),
                                -len(m.matched)))
    return matches
