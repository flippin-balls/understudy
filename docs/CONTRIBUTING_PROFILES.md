# Adding a game profile

A profile lets `identify` and `convert-set` handle a game without asking the user
for pointer offsets or socket mappings. It contains layout facts, device hashes,
and validation evidence.

**Do not include ROM images.** Profiles contain no ROM data, and ROM files should
not be attached to issues or pull requests.

## What you need to establish

Start with the layout procedure in
[SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md#working-out-the-layout-for-your-rom).
A profile needs these layout facts:

| field | meaning |
|---|---|
| pointer table offset | where phrase pointers begin |
| phrase count | number of phrases |
| base address | CPU address of the assembled image |
| ordering | address order or command order |
| end bound | whether the table has a final end pointer |

It also needs, for each socket: device type and size, CPU address, mirroring,
whether it carries speech, and its SHA-256.

## Create the profile

Copy `src/tms52xx/data/profiles/embryon.json` and edit it. The loader in
`src/tms52xx/profiles.py` validates the schema and reports invalid fields.

### Layout exceptions

Some games need explicit exceptions to the default layout rules:

| field | use it for | check performed |
|---|---|---|
| `entry_form` | `starts` or `start_end_pairs` | pair bounds and table overlap are validated |
| `silent_phrases` | known all-silence phrases | named phrases must actually contain only silence |
| `unterminated_phrases` | phrases terminated by the player rather than the ROM | named phrases must be unterminated; unnamed phrases must stop normally |
| `truncate_last_byte` | phrases whose last ROM byte is not transmitted | use `inspect --source-tables` to establish where truncation is safe |

Name only exceptions you have checked. Everything not named remains subject to
the normal rule.

Every emitted device needs a `sha256`, including devices that hold no speech.
`convert-set` verifies every file it will write back out.

You can print hashes with:

```text
python understudy.py identify U4.bin U5.bin
```

The command prints each file's SHA-256 even if the set is not recognized.

## Status

Use the lowest status supported by the evidence:

| status | meaning |
|---|---|
| `draft` | layout written but not fully checked |
| `layout-verified` | phrases and layout checks pass against a real dump |
| `board-simulated` | converted ROMs boot and run with the board firmware in simulation |
| `silicon-verified` | a converted set has been fitted to a real board and listened to |

`board-simulated` is not an audio result. Only `silicon-verified` means anyone
has heard the conversion on hardware.

Past profile failures are documented in [VALIDATION.md](VALIDATION.md). They are
why a clean parse or successful boot alone is not enough: a profile also needs
coverage evidence from the board firmware's actual TMS byte streams.

## Evidence block

Record how you established the layout and what remains unverified. In
particular, distinguish:

- table/layout evidence;
- board-simulation evidence;
- firmware-trace coverage;
- real-hardware listening evidence.

If the firmware trace does not exercise some table entries, record them in the
profile evidence rather than implying they were covered.

## Test the profile locally

Point Understudy at a working profile directory:

```bash
export UNDERSTUDY_PROFILE_DIR=/path/to/your/profiles
```

```powershell
$env:UNDERSTUDY_PROFILE_DIR = 'C:\path\to\profiles'
```

Then run:

```text
python understudy.py identify U4.bin U5.bin
python understudy.py convert-set U4.bin U5.bin --target tsp5220c -o out/ --dry-run
```

Check that:

- the expected game is identified;
- every phrase parses as expected;
- speech-bearing sockets actually change;
- reported speech coverage makes sense for the device;
- the image/device reconciliation line balances.

Then run the test suite:

```text
PYTHONPATH=src python -m unittest discover -s tests
```

## What a profile must clear before shipping

1. **Valid phrase layout.** Phrases must terminate normally unless an exception
   is explicitly established and recorded.
2. **Plausible device coverage.** `convert-set` reports how much of each physical
   device is consumed by speech. There is no universal threshold; use it as a
   sanity check against the board and ROM organization.
3. **Independent evidence where available.** A separately derived frame count or
   phrase list is useful because it does not depend on the same pointer-table
   interpretation.
4. **Board simulation.** The board firmware should boot and behave normally with
   the converted ROMs before using `board-simulated` status.
5. **Firmware-trace coverage.** Every speech stream observed from the board
   firmware must fall inside a phrase the profile converts. Any entries not
   reached by the trace must be called out in the evidence.

A profile that cannot clear all of those can still be contributed as `draft`.

## Send the pull request

Include:

- the profile JSON;
- a CHANGELOG entry;
- the game in the README supported-games table;
- the `--dry-run` output and a short description of how the layout was
  established.

Do not attach ROM images. If more information is needed, maintainers can ask for
a command to run against your copy.

## If you get stuck

Open an issue using the **New game profile** template. A partial layout or a
specific point where the analysis stops making sense is still useful.
