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

### Layout fields that are claims, not switches

Four `layout` fields let a profile state something unusual about its table.
Each is *checked*, so none of them can be used to wave a bad layout through:

| field | states | checked how |
|---|---|---|
| `entry_form` | `starts` (default) or `start_end_pairs` — whether an entry is a phrase start or a 4-byte (start, end) record | a pair record whose end precedes its start, or which overlaps the table, is refused; with `start_end_pairs`, stating `address_ordered` or `has_end_bound` is refused because neither has meaning |
| `silent_phrases` | phrases that are a run of silence and nothing else | a named phrase that carries speech is refused |
| `unterminated_phrases` | phrases the ROM leaves the player to terminate | a named phrase that *does* end in a stop frame is refused, and any phrase you did **not** name still has to terminate |
| `truncate_last_byte` | phrases whose final ROM byte is never transmitted | `inspect --source-tables` reports where truncation is safe |

Name only what you have checked. The value of each list is that everything not
on it is still held to the default rule.

**Every device needs a `sha256`, not only the speech-bearing ones.** A device
carrying no speech is still copied out as a burn image, so it has to be
authenticated too; `convert-set` refuses a profile that cannot verify every
device it will emit.

Get the device hashes with:

```
understudy identify U4.bin U5.bin
```

which prints the SHA-256 of each file whether it recognises them or not.

### Status

Be honest about this. It is the field a technician reads before trusting the
profile.

| status | means, exactly |
|---|---|
| `draft` | written, not yet checked against a real dump |
| `layout-verified` | every phrase is found, and terminates in a stop frame or is named in `unterminated_phrases` and checked |
| `board-simulated` | the board's own firmware, in emulation, boots and drives the **converted** ROMs |
| `silicon-verified` | a converted set has been fitted to a real board and listened to |

**No rung below `silicon-verified` means anyone has heard the speech.** Not
even `board-simulated`: that checks structure and control flow, not sound.

`board-simulated` catches a layout that converted something which was not
speech — Embryon's own profile shipped briefly with a pointer-table end bound
read as a 21st phrase; it parsed, it terminated, it changed nothing outside its
extent, and it rewrote 6800 instructions. Every static check passed it. Booting
the board against the converted ROMs did not.

**But booting is not sufficient either.** Fathom shipped a profile that booted
identically to the original while rewriting 31 bytes of firmware, because the
commands the simulation issues never reach that code. A profile now also has to
agree with a phrase list captured from the **running** board — see step 6 of
"Working out the layout for your ROM" in
[SQUAWK_AND_TALK.md](SQUAWK_AND_TALK.md). If you cannot run that check, say so
in the evidence block and mark the profile `draft`; it is better to contribute a
layout labelled as unconfirmed than one labelled as more than it is.

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

```bash
export UNDERSTUDY_PROFILE_DIR=/path/to/your/profiles       # bash / zsh
```

```powershell
$env:UNDERSTUDY_PROFILE_DIR = 'C:\path\to\profiles'      # PowerShell
```

```bat
set UNDERSTUDY_PROFILE_DIR=C:\path\to\profiles           # cmd.exe
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

## What a profile has to clear

Automatic layout detection is not enough. A sweep over 46 Squawk & Talk sets
found layouts that convert cleanly, boot the board's firmware, and are still
wrong — one converted 1.5% of its speech and behaved normally. Before a profile
ships:

1. **every phrase found and terminating** — `inspect --source-tables` shows it.
   If one does not, that is normally a wrong layout. It can also be a ROM whose
   player supplies the terminator: one phrase of Mr. and Mrs. Pac-Man is, and
   nothing else in the fifteen sets. Establish which before naming it in
   `unterminated_phrases`, and expect to be held to it — a named phrase that
   does terminate is refused;
2. **speech coverage that looks like a whole ROM.** `convert-set` prints the
   percentage of each speech device the layout reached. Correct layouts in that
   sweep ran 33–70%; the wrong one ran 1.5%. There is no safe threshold, so look
   at the number and judge it;
3. **an independent frame count if you can get one** — four sets matched a
   separately built corpus exactly, and that is the strongest check available
   short of hardware;
4. **the board's firmware booting against the converted ROMs**, behaving as it
   does with the originals. That is what `board-simulated` means.

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
