---
name: New game profile
about: Add support for a game, or ask for help working one out
title: "[profile] <game>"
labels: profile
---

**Do not attach ROM images.** A profile is layout facts and hashes; none of it
reproduces a ROM. See [docs/CONTRIBUTING_PROFILES.md](../../docs/CONTRIBUTING_PROFILES.md).

## Game

- Title, manufacturer, year:
- Board:
- ROM set / revision identifiers, if known:

## Sockets

| socket | device type | size | CPU address | mirrored? | holds speech? | SHA-256 |
|---|---|---|---|---|---|---|
| | | | | | | |

`understudy identify <files>` prints the hashes.

## Layout, as far as you have got

- Pointer table offset:
- Phrase count:
- Base address:
- Address- or command-ordered:
- End bound present:

## What you tried

Paste the output of:

```
understudy inspect <image> --table-offset ... --phrases ... --base-address ...
```

## Status

- [ ] I have a working profile and will open a PR
- [ ] I have a partial layout and am stuck (say where)
- [ ] I have the ROMs and would like help starting

A partial layout or a clear description of where it stops making sense is a
useful contribution — several documented gotchas were found that way.
