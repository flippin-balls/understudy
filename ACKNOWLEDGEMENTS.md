# Acknowledgements

This tool exists because other people did the hard part first.

## The coefficient tables

The TMS5200 and TMS5220 tables Understudy bundles come from **MAME**, and are
credited there to **Frank Palazzolo, Couriersud and Jonathan Gevaryahu**. They
are not transcriptions of a datasheet — they were established by opening the
chips:

- **digshadow**, who decapped and imaged the TMS5200NL (March 2013), the
  TMS5220NL and the TMS5220CNL (April 2013). The verification that the 5220C's
  LPC table exactly matches the 5220's is what lets this tool emit the same
  converted data for all three targets — which matters, because the TSP5220C is
  the most findable of them today.
- **PlgDavid**, for the PROMOUT dumps that independently corroborate them.
- **Sean Riddle** and **Jarek Burczynski**, for related decaps and dumps
  recorded in the same file.

Without that work there would be no trustworthy target tables and no way to know
which parts are equivalent.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the licence and exact
provenance.

## The emulators

The **MAME** and **PinMAME** teams, whose reverse engineering of the TMS52xx
family is the foundation under everything here — including the ability to check
this tool's output before anyone risks a real board.

## Prior art

**QBoxPro**, and the projects written to replace it: **BlueWizard**
(Patrick Kelly), **python_wizard** (Peter Turczak), **TMS Express**, **speakie**
(Raph Levien), and **Talkie** (originally Peter Knight, latterly Armin
Joachimsmeyer). They solve the harder and more general problem — audio in, LPC
out. Understudy only re-indexes data that already exists.
[docs/PRIOR_ART.md](docs/PRIOR_ART.md) says what is in each.

## Preservation and documentation

- **Stuart Conner**, for the most careful surviving documentation of TI speech
  hardware and its development systems.
- The **Internet Pinball Database**, without which finding a machine's manual,
  schematic and ROM details would be far harder.
- **Gene Helms and Steve Petersen**, whose 1982 *Electronics* article describes
  how this speech data was originally produced.

## Hardware validation

The first real-board validation was Embryon, 2026-09-11, by Flashback Fleet LLC:
a converted set fitted to a Bally Squawk & Talk AS-2518-61A with a TMS5220 and
compared by ear against a TMS5200 baseline on the same board.

Fifteen profiles are still unheard. This is where the name of the next person to fit a converted set to
a real Squawk & Talk and report what happened will go — see
[docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md).
