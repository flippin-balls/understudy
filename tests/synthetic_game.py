"""A synthetic two-socket ROM set, shaped like a real Squawk & Talk one.

No ROM data. The speech here is frames built by `test_rom.stream` from the
synthetic coefficient tables, and the layout reproduces the structure that makes
real sets awkward:

  * two sockets, one holding a 2 KB device mirrored into a 4 KB window;
  * the speech reached through that mirror rather than the lower copy;
  * the pointer table sitting ABOVE the speech, in the other socket;
  * command-ordered pointers with no end bound.

That is Embryon's shape, which is why it is the shape worth testing against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import original                          # noqa: E402
from tms52xx.profiles import sha256                     # noqa: E402

WINDOW_BASE = 0xC000
WINDOW_SIZE = 0x4000
U4_ADDR = 0xE000        # 2 KB device, mirrored to 0xE800
U4_SIZE = 0x800
U5_ADDR = 0xF000        # 4 KB device
U5_SIZE = 0x1000
TABLE_CPU = 0xFC00      # pointer table, in U5, above the speech
PHRASES = 4


def _phrase(chip, energy, pitch, terminate=True):
    from test_rom import stream
    frames = [(energy, 0, pitch, list(range(10))),
              (energy, 0, pitch + 1, list(range(10)))]
    if terminate:
        frames.append((0xF, 0, 0, []))
    return stream(chip, frames)


def build(terminate=True):
    """Return (dumps, profile_dict). `dumps` maps socket -> bytes.

    `terminate=False` builds a set whose phrases carry no stop frame, for the
    tests that need a layout which parses but does not terminate.
    """
    chip = original()
    # Two phrases live in U4 (reached through its mirror), two in U5.
    a = _phrase(chip, 7, 40, terminate)
    b = _phrase(chip, 9, 12, terminate)
    c = _phrase(chip, 8, 30, terminate)
    d = _phrase(chip, 6, 20, terminate)

    u4 = bytearray(b"\xFF" * U4_SIZE)
    u5 = bytearray(b"\xFF" * U5_SIZE)

    # Speech in U4 starts at its mirror address 0xE800, i.e. offset 0 of the
    # device (the mirror is a second copy of the same 2 KB).
    u4[0:len(a)] = a
    u4[len(a):len(a) + len(b)] = b

    # Speech in U5 starts at 0xF000, table at 0xFC00.
    u5[0:len(c)] = c
    u5[len(c):len(c) + len(d)] = d

    starts = [0xE800, 0xE800 + len(a), 0xF000, 0xF000 + len(c)]
    # Command order: not ascending, to exercise that path.
    order = [starts[2], starts[0], starts[3], starts[1]]
    table_at = TABLE_CPU - U5_ADDR
    for i, value in enumerate(order):
        u5[table_at + 2 * i:table_at + 2 * i + 2] = value.to_bytes(2, "big")

    dumps = {"U4": bytes(u4), "U5": bytes(u5)}
    profile = {
        "schema_version": 1,
        "profile_id": "synthgame",
        "profile_version": 1,
        "title": "Synthetic Test Game",
        "manufacturer": "Nobody",
        "year": 1981,
        "board": "test fixture",
        "source_chip": "tms5200",
        "status": "draft",
        "memory": {"window_base": WINDOW_BASE, "window_size": WINDOW_SIZE,
                   "fill": 255},
        "devices": [
            {"socket": "U4", "type": "2716", "size": U4_SIZE,
             "cpu_address": U4_ADDR, "mirrored": True, "holds_speech": True,
             "sha256": sha256(dumps["U4"]), "label": "synth-u4"},
            {"socket": "U5", "type": "2532", "size": U5_SIZE,
             "cpu_address": U5_ADDR, "mirrored": False, "holds_speech": True,
             "sha256": sha256(dumps["U5"]), "label": "synth-u5"},
        ],
        "layout": {"table_offset": TABLE_CPU - WINDOW_BASE,
                   "base_address": WINDOW_BASE,
                   "phrases": PHRASES,
                   "address_ordered": False,
                   "has_end_bound": False,
                   "truncate_last_byte": []},
        "evidence": {"layout": "constructed by tests/synthetic_game.py"},
        "notes": ["Not a real game."],
    }
    return dumps, profile


def write_profile(directory, profile) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%s.json" % profile["profile_id"])
    path.write_text(json.dumps(profile, indent=1), encoding="utf-8")
    return path
