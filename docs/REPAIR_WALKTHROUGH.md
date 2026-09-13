# From a dead speech chip to two burned EPROMs

Start here if you have never used Understudy or a command line. If you are
comfortable in a terminal, the [README](../README.md) has the shorter path.

You will need:

- the sound ROMs from your machine, saved as files;
- a blank EPROM of the right type for each speech device;
- a TMS5220, TMS5220C or TSP5220C;
- an EPROM programmer;
- a computer with Python 3.9 or newer.

## 1. Check Python

On **Windows**, open PowerShell and run:

```text
py --version
```

On **macOS/Linux**:

```text
python3 --version
```

If Windows says Python was not found, install it from
[python.org/downloads](https://www.python.org/downloads/) and select **Add
python.exe to PATH** in the installer. Reopen PowerShell afterward.

The examples below use `py` on Windows and `python3` elsewhere.

## 2. Get Understudy

On the repository page, click **Code → Download ZIP**, then unzip it somewhere
easy to find. The folder should contain `understudy.py`.

There is nothing else to install: no `pip`, setup step, or dependency download.

## 3. Put the ROM files nearby

For the simplest commands, copy your ROM dumps into the Understudy folder next
to `understudy.py`.

If they are already in a zip, leave the zip intact and copy it there. Understudy
can read a zip directly.

## 4. Open a terminal in the folder

On Windows, open the folder, Shift+right-click an empty area, and choose the
PowerShell/Terminal option. On macOS, use **Services → New Terminal at Folder**.

Check the tool:

```text
py understudy.py --version
```

Use `python3 understudy.py --version` on macOS/Linux.

## 5. Identify the ROM set

For loose files in the current folder:

```text
py understudy.py identify .
```

For a zip:

```text
py understudy.py identify mygame.zip
```

If Understudy recognizes the set, it names the game and prints the next command.

### Optional: inspect the phrase table

You do **not** need to find or enter a pointer-table address for a supported
game. The profile already contains it.

Use the profile name printed by `identify`:

```text
py understudy.py inspect --game NAME .
```

For example:

```text
py understudy.py inspect --game eballdlx .
py understudy.py inspect --game flashgdn .
```

A **phrase** here means one encoded speech stream referenced by the game's phrase
table. `inspect` does not turn it into English text or a phoneme transcript. It
shows where each phrase lives and how it is encoded: addresses, length, frame
count and frame kinds. It writes nothing.

This step is optional; skip it if you only want to make replacement ROMs.

## 6. Convert

Loose files:

```text
py understudy.py convert-set .
```

Zip file:

```text
py understudy.py convert-set mygame.zip
```

Understudy identifies the game, assigns files to sockets, converts the speech,
and writes the result to `understudy-out/`.

By default the output is converted for a **TMS5220**. The same converted speech
data is used by the TMS5220C and TSP5220C. Do not put the converted ROMs back in
a board that still has its original TMS5200; keep using the original ROMs with
the TMS5200.

**Read the report before burning anything.** The lines that matter most look
like this:

```text
output devices
  U4   2716       2048 bytes  1560 changed  100% converted
       burn into 2716: understudy-out/841-01_4_U4_2716_tms5220.716
  U5   2532       4096 bytes  1948 changed  61% converted
       burn into 2532: understudy-out/841-02_5_U5_2532_tms5220.532
```

Each line gives the **socket**, the **EPROM type**, and the **file to burn**.

A warning about frames below the pitch floor is not a conversion failure. The
TMS5220 cannot reproduce the TMS5200's lowest pitch values; see
[PITCH_CEILING.md](PITCH_CEILING.md).

### Optional audio optimization

For a first hardware test, use the normal conversion above. Sixteen of the
seventeen profiles also have measured optimization data that you can opt into:

```text
py understudy.py convert-set . --optimize-audio
```

The optimizer is still experimental at the whole-phrase level: some phrases
score worse after optimization even when their individual frames score better.
Use the normal conversion as the baseline and check your game's results in
[AUDIO_OPTIMIZATION.md](AUDIO_OPTIMIZATION.md) before testing optimized ROMs.
No optimized ROM has yet been tested on real hardware.

## 7. Burn the EPROMs

For each output file:

- select the **device type printed in the report**;
- load the file as a **raw binary** image;
- program it, then run your programmer's **verify** function;
- label the chip with its socket before putting it down.

Do not burn the `.manifest.json` file. Keep it with the originals; it records the
input/output hashes and conversion settings without containing ROM data.

**Do not erase the original chips.**

## 8. Fit the EPROMs and speech chip

Check the board's EPROM jumpers before fitting a device type different from the
one you removed. A 2532 and 2732 are both 4 KB devices but are not pin-compatible
without the proper jumper configuration.

The replacement speech chip is a separate electrical question from the ROM
conversion. See [CHIPS.md](CHIPS.md) and check the board schematic and the
datasheet for the exact part you are fitting.

## 9. Tell us how it went

Real-board results are valuable whether they pass or fail. Use
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), especially if you test a game
other than Embryon or use `--optimize-audio`.

## When something goes wrong

### "Python was not found" / "py is not recognised"

Install Python or reopen the terminal after installation. On Windows, make sure
**Add python.exe to PATH** was selected. You can also try `python` or `python3`
instead of `py`.

### "this does not match any game understudy knows"

Usually one of these:

- the game is not in `py understudy.py profiles`;
- one of the required ROM devices is missing;
- a ROM was read incorrectly.

Re-read the chips using the exact device type marked on them. A single wrong bit
changes the hash.

### "nothing that looks like a ROM dump was found"

- If the dumps are in a zip, point at the zip itself.
- If you used a folder, point at the folder that directly contains the dumps.
- Files that look like documentation (`.txt`, `.md`, `README`) are skipped during
  folder scans; name one explicitly if it really is a ROM dump.

### "these files are not part of the ... speech set"

You explicitly named a file that is not part of the speech set, often a CPU ROM.
Remove it from the command, or point at the containing folder so unrelated files
can be ignored.

### "refusing to write over a file this run reads"

Choose another output directory:

```text
py understudy.py convert-set . -o converted/
```

### The output folder already exists

Delete the old `understudy-out/` after checking it, or use `-o` to choose another
folder. Understudy does not overwrite existing output unless explicitly told to.

### Anything else

Open an issue with the command you ran and its complete output. Attach the
manifest if one was produced; it contains no ROM data.

## If you have not read your ROMs yet

Pull the ROMs from the sound board and read them with your EPROM programmer.
Select the device type printed on each chip; using the wrong type can produce a
file of the expected size with incorrect contents.

Read every ROM on the sound board, not only the ones you expect to contain
speech. Understudy uses the complete set to identify the game and decide which
files matter.
