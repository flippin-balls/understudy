# From a dead speech chip to two burned EPROMs

Start to finish, assuming you have never used a command line. If you have, the
whole thing is one command and you can read [the README](../README.md) instead.

You will need:

- the sound ROMs out of your machine, as files (see [If you have not read your
  ROMs yet](#if-you-have-not-read-your-roms-yet));
- a blank EPROM of the right type for each device that holds speech — for many
  games that is **two**, and they are often **different types**;
- a TMS5220, TMS5220C or TSP5220C. All three give identical converted data;
- an EPROM programmer, and whatever software came with it;
- a computer with Python. Ten minutes if you already have it.

---

## 1. Check whether you have Python

Open a terminal. On **Windows**: press the Start button, type `powershell`, and
press Enter. On **macOS**: Applications → Utilities → Terminal.

Type this and press Enter:

```
py --version
```

If you see something like `Python 3.12.1`, you are ready — skip to step 2.

If you see `Python was not found` or similar, install it:

- **Windows**: get it from [python.org/downloads](https://www.python.org/downloads/).
  On the first screen of the installer, tick **"Add python.exe to PATH"** before
  clicking Install. That box is the single most common reason the commands below
  do not work. Close and reopen PowerShell afterwards, then try `py --version`
  again.
- **macOS / Linux**: use `python3 --version`, and install Python 3.9 or newer
  from your usual source if it is missing.

Throughout this page, Windows users type `py` and everyone else types `python3`.

## 2. Get Understudy

On the repository page, click the green **Code** button, then **Download ZIP**.
Unzip it somewhere you can find again — your Desktop is fine. You will get a
folder called `understudy-main` containing `understudy.py`.

There is nothing to install. No `pip`, no setup, no dependencies.

## 3. Put your ROMs where you can reach them

Copy your ROM files **into that same folder**, next to `understudy.py`. That
saves you typing paths.

If your ROMs are still inside a **zip**, copy the zip in as it is — do not
unzip it. You will point at the zip by name. (Pointing at a *folder* does not
look inside archives, so a zip sitting in the folder would be skipped.)

## 4. Open a terminal in that folder

On **Windows**: open the folder, hold **Shift**, right-click an empty part of the
window, and choose **Open PowerShell window here**.

On **macOS**: right-click the folder → Services → **New Terminal at Folder**.

Check you are in the right place:

```
py understudy.py --version
```

A version number means everything is working.

## 5. See what you have

If your ROMs are **loose files** in the folder:

```
py understudy.py identify .
```

The `.` means "everything in this folder". If they are **in a zip**, name the
zip instead:

```
py understudy.py identify mygame.zip
```

Either way, use the same thing in step 6.

It will either name your game, or tell you it does not recognise the set. If it
names it, it also prints the exact command to run next — you can copy that.

## 6. Convert

```
py understudy.py convert-set .
```

...or, if your ROMs are in a zip:

```
py understudy.py convert-set mygame.zip
```

That is the whole job. It works out which game it is, which file belongs in which
socket, which chip to convert for, and where to put the results.

It writes the files, then prints a report. **Read the report before you burn
anything.** The part that matters:

```
output devices
  U4   2716       2048 bytes  1560 changed  100% converted
       burn into 2716: understudy-out/841-01_4_U4_2716_tms5220.716
  U5   2532       4096 bytes  1948 changed  61% converted
       burn into 2532: understudy-out/841-02_5_U5_2532_tms5220.532
```

Each line tells you the **socket** (`U4`), the **chip type to burn**
(`2716`), and the **file**. A new folder called `understudy-out` now holds them.

If it prints a warning about frames "below the pitch floor", that is normal and
explained in [the README](../README.md#silicon-validation). It is not an error.

## 7. Burn them

For each output file, in your programmer's software:

- select the **device type printed on that line** — `2716` for the U4 file,
  `2532` for the U5 file in the example above. **They are often not the same
  type**, and selecting the wrong one is the most common way to waste a chip;
- load the file as a **raw binary image**. Not Intel HEX, not S-record. If your
  software asks for a format and "binary" is an option, that is the one;
- program, then **verify**. Every programmer has a verify function. Use it;
- label the chip with its socket while it is in your hand.

**Do not burn `embryon.manifest.json`.** That file is a record of what was
converted, not something to program. Keep it — if you ever need help, nearly
every question anyone will ask you is answerable from it, and it contains no
ROM data.

**Keep your original chips.** Do not erase them. If anything is wrong you want
to be able to put the machine back exactly as it was.

## 8. Fit them

Both the new EPROMs and the replacement speech chip go in together. Two things
this tool cannot check for you:

- **The sockets may be jumpered for a particular device type.** Many boards can
  take more than one EPROM type per socket, selected by jumpers, and the types
  are *not* pin-compatible — a 2532 and a 2732 disagree, and so do a 2716 and a
  2532. Check your board's jumpers against its schematic before fitting a type
  that differs from what came out.
- **Whether your replacement speech chip drops in electrically** is between you,
  the datasheet and the schematic. See [CHIPS.md](CHIPS.md). One TMS5220 has
  been fitted to one board for this project and worked, with no board change.
  That is not a substitution guarantee.

## 9. Tell us how it went

Whether it worked or not: [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).
Only one game has ever been tested on a real machine. A failure report is worth
more than silence, and a partial one ("phrases 1–14 fine, 15 sounds wrong") is
worth more than either.

---

## When something goes wrong

### "Python was not found" / "py is not recognised"

Python is not installed, or the **Add python.exe to PATH** box was not ticked
during installation. Reinstall with that box ticked, then close and reopen the
terminal. Try `python` or `python3` instead of `py` before reinstalling.

### "this does not match any game understudy knows"

Three different causes, and the message cannot tell them apart:

- **Your game is not one of the sixteen covered.** Run
  `py understudy.py profiles` to see the list. If yours is not there, the tool
  cannot convert it automatically, and that is not a fault in your files.
- **You are missing a device.** Some games hold speech in two chips. If you only
  read one, no profile can match. `py understudy.py identify .` lists what it
  found and what it expected.
- **A ROM was read badly.** Re-read the chip, making sure your programmer is set
  to the right device type. A single wrong bit changes the hash.

### "nothing that looks like a ROM dump was found"

Three causes:

- **Your ROMs are inside a zip.** Point at the zip by name, not at the folder
  holding it — scanning a folder does not look inside archives.
- **You pointed one level too high.** Sub-folders are not searched. Point at the
  folder that directly contains the files.
- **The files have names that look like documentation** (`.txt`, `.md`, a file
  called `README`). Those are skipped while scanning. Name them directly if you
  really mean them.

### "these files are not part of the ... speech set"

You named a file that is not part of the speech set — often a CPU ROM. Either
remove it from the command, or point at the whole folder instead: when you point
at a folder, extra files are ignored rather than refused.

### "refusing to write over a file this run reads"

An output would land on one of your input files. Convert into a different
folder: `py understudy.py convert-set . -o converted/`.

### The output folder already exists

Understudy will not silently overwrite. Either delete `understudy-out`, or send
the results somewhere else with `-o`.

### Anything else

Open an issue with the command you ran and everything it printed. Attach the
manifest if you got one. It contains no ROM data.

---

## If you have not read your ROMs yet

You need the contents of the ROM chips already in your machine, as files. That
means pulling them from their sockets and reading them in an EPROM programmer —
the same device you will use to burn the new ones. Select the correct device
type when reading; the wrong one gives a file that looks plausible and is wrong.

Read every ROM on the sound board, not just the ones you think hold speech.
Understudy works out which are which, and having them all lets it identify your
game by content.
