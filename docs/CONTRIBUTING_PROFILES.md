# Adding a game profile

A profile is what lets `understudy identify` and `convert-set` work on a game
without anyone typing pointer offsets. It is a small JSON file of layout facts
and device hashes.

**A profile contains no ROM data, and we do not want any.** Do not attach ROM
images to an issue or a pull request. Everything below is derived from a ROM you
have; none of it reproduces one.

## What you need to find

Five layout facts and a description of the sockets. `understudy inspect` and the
procedure in
[SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md#working-out-the-layout-for-your-rom)
walk you through finding them:

| | |
|---|---|
| pointer table offset | where the table of phrase pointers begins |
| phrase count | how many entries it has |
| base address | the CPU address the assembled window starts at |
| ordering | address order, or command order |
| end bound | does the table carry one extra entry for the last phrase's end? |

plus, per socket: the device type and size, the CPU address it maps to, whether
a 2 KB device is mirrored in a 4 KB socket, and whether it holds speech.

## Writing it

Copy `src/tms52xx/data/profiles/embryon.json` and edit it. The fields are
documented in `src/tms52xx/profiles.py`; the loader validates every one and will
tell you exactly what is wrong.

Get the device hashes with:

```
understudy identify U4.bin U5.bin
```

which prints the SHA-256 of each file whether it recognises them or not.

### Status

Be honest about this. It is the field a technician reads before trusting the
profile.

| status | means |
|---|---|
| `draft` | written, not yet checked against a real dump |
| `layout-verified` | the layout parses: every phrase found, every one terminates |
| `emulator-verified` | converted output renders correctly through an emulator |
| `silicon-verified` | a converted set has been played on a real board |

**Only a real-machine test earns `silicon-verified`**, and it needs a report —
see [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).

### Evidence

The `evidence` block is not decoration. Say how you established the layout, what
you checked, and — importantly — what you did **not**. Embryon's carries a
`not_verified` key saying plainly that nothing has been played on a real board.
Follow that habit.

## Checking it

Point Understudy at your working directory rather than editing the installed
copy:

```
export UNDERSTUDY_PROFILE_DIR=/path/to/your/profiles     # Windows: set
```

Then:

```
understudy identify U4.bin U5.bin           # should now name your game
understudy convert-set U4.bin U5.bin --target tsp5220c -o out/ --dry-run
```

The dry run prints the validation block without writing anything. Look for:

- every phrase found, and none reported without a stop frame;
- phrase lengths that look like words rather than wildly uneven;
- every socket you marked `holds_speech` actually changing;
- the reconciliation line adding up.

If a socket you marked as holding speech does not change, the layout is not
finding its phrases and the profile is wrong — Understudy will refuse rather
than write, but do not talk it into proceeding.

Then run the tests:

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Sending it

Open a pull request with:

- the profile JSON;
- a line in [CHANGELOG.md](../CHANGELOG.md);
- the game added to the supported table in [README.md](../README.md);
- in the PR description: how you established the layout, what you verified, and
  the output of the `--dry-run` above.

**Do not attach ROM images.** If a maintainer needs to check something, the
hashes and the manifest are enough; if they are not, we will ask you to run a
command rather than send data.

## If you cannot get it working

Open an issue with the **New game profile** template anyway. A partial layout,
or a clear description of where it stops making sense, is a useful contribution.
Several of the awkward cases already documented here — the mirrored device, the
pointer table sitting above the speech — were found exactly that way.
