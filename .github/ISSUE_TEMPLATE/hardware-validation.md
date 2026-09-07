---
name: Hardware validation report
about: You fitted a converted ROM set to a real board. Tell us what happened.
title: "[hardware] <game> on <replacement chip>"
labels: hardware-validation
---

**This is the most valuable report this project can receive.** A failure is
worth more than silence. Do not attach ROM images.

Most of the fields below are in the manifest `convert-set` wrote; attaching it
answers most of them at once. The manifest contains no ROM data.

## Machine and board

- Game:
- Board and revision:
- Anything non-standard (repairs, mods, sockets):
- Did it speak correctly before, with the original chip and ROMs?

## Chips

| | original | replacement |
|---|---|---|
| Marked part number | | |
| Date code | | |

Board changes needed to fit the replacement (jumpers, sockets, wiring):

## ROMs and tool versions

- Understudy version:
- Profile id and version:
- Target chip:
- Device types and jumper settings (2532 vs 2732 especially):
- Manifest attached? (please do)

## Power-on

- Comes out of reset normally?
- READY / Speak External behaviour as before?
- Any new noise, hum or click?

## Phrase by phrase

| phrase / command | intelligible? | pitch vs original | notes |
|---|---|---|---|
| | | | |

Some phrases sounding higher is expected — Understudy raises frames the
replacement cannot reach, and the manifest says how many. Flag anything cut
short, garbled, silent, or playing at the **wrong speed**.

## Conclusion

- [ ] PASS
- [ ] PARTIAL (say which phrases)
- [ ] FAIL (say how)

Anything else worth knowing:
