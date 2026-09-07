"""The short path: socket dumps in, replacement device images out.

`convert_set` is what `understudy convert-set` runs. It exists so a technician
never has to assemble a CPU image, know where a pointer table lives, or work out
which half of a mirrored device to burn. Everything it does is recorded in the
manifest so the result can be audited, or a bug reported, without the ROM.

It fails closed. Any condition that could produce a plausible-looking wrong ROM
-- an unidentified set, a phrase that does not terminate, a device that changed
when the profile says it holds no speech -- stops the run before anything is
written.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .chips import Chip, bundled_provenance, resolve
from .profiles import Profile, ProfileError, sha256
from .bitstream import parse
from .rom import PhraseTable, diagnose_last_byte, patch_rom, summarise
from .tables import ChipTables

#: Bumped when the manifest's shape changes. Readers should check it.
MANIFEST_SCHEMA_VERSION = 2


class ConversionRefused(RuntimeError):
    """The run stopped rather than write something that might be wrong."""


class SetResult:
    """Everything a caller needs to report on, or write out, one conversion."""

    def __init__(self) -> None:
        self.profile: Optional[Profile] = None
        self.source_chip: Optional[Chip] = None
        self.target_chip: Optional[Chip] = None
        self.inputs: Dict[str, dict] = {}
        self.outputs: List[dict] = []
        self.stats: dict = {}
        self.phrases: List[dict] = []
        self.warnings: List[str] = []
        #: True when a table file was supplied instead of the bundled data.
        self.custom_tables: bool = False
        self.overrides: List[str] = []
        self.manifest: dict = {}
        self.before: bytes = b""
        self.after: bytes = b""


def _load_tables(chip: Chip, custom: Optional[Path]):
    """Read a table file ONCE, and hash the bytes that were actually parsed.

    Loading and then hashing separately reads the file twice, so a file changed
    in between would give a manifest describing something other than what
    produced the ROM.
    """
    path = Path(custom) if custom else chip.table_path
    raw = path.read_bytes()
    return ChipTables.from_bytes(raw, path), raw, path


def _table_identity(chip: Chip, custom: Optional[Path],
                    loaded: ChipTables, raw: bytes, path: Path) -> dict:
    """Which coefficient tables were used, and how to recognise them again.

    When a custom file is supplied, `chip` is only what the user ASKED for.
    Nothing checks that the file describes that part, so both are recorded: the
    requested id, and the name the table gives itself.
    """
    identity = {
        "requested_chip": chip.id,
        "table_name": loaded.name,
        "bundled": custom is None,
        "path": str(path) if custom else "data/%s.json" % chip.table,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if custom is None:
        identity["chip"] = chip.id
        identity["provenance"] = bundled_provenance(chip.table)
    else:
        # Deliberately NOT the requested id: a reader of this manifest must not
        # be able to conclude the output was quantised to that part.
        identity["chip"] = "custom"
    return identity


def convert_set(dumps: Dict[str, bytes], profile: Profile,
                target: Chip, source: Optional[Chip] = None,
                source_tables: Optional[Path] = None,
                target_tables: Optional[Path] = None,
                allow_unterminated: bool = False) -> SetResult:
    """Convert one identified ROM set. Returns a SetResult; writes nothing."""
    # A profile whose speech devices carry no hashes cannot authenticate the
    # dumps it is handed. `--game` would then apply a layout to arbitrary
    # correct-sized bytes, and a stop frame is not authentication -- 0xF occurs
    # in ordinary data. The burnable-image path requires identifiable profiles;
    # the manual `convert` command remains for research on unhashed layouts.
    # EVERY device, not just the speech-bearing ones. A device with no speech
    # is still copied out as a burn image, and an unhashed one is accepted on
    # size alone -- so a technician could be handed a file named for a socket,
    # sized for its device, containing whatever they happened to pass in.
    if not profile.identifiable:
        missing = [d.socket for d in profile.devices if not d.sha256]
        raise ConversionRefused(
            "profile %r cannot verify what it is given: socket(s) %s carry no "
            "sha256, so nothing distinguishes the right ROM from a wrong one "
            "of the same size. Add hashes to the profile, or use the manual "
            "`convert` path." % (profile.id, ", ".join(missing)))

    result = SetResult()
    result.profile = profile
    result.source_chip = source or resolve(profile.source_chip)
    result.target_chip = target

    src_tables, src_raw, src_path = _load_tables(result.source_chip,
                                                 source_tables)
    dst_tables, dst_raw, dst_path = _load_tables(target, target_tables)

    # Every socket the profile knows must be supplied. A missing device is not
    # a warning: its bytes would be filled with 0xFF and a pointer into it would
    # convert padding as though it were speech.
    for device in profile.devices:
        if device.socket not in dumps:
            raise ConversionRefused(
                "socket %s (%s, %d bytes) is in the %s profile but no dump was "
                "given for it" % (device.socket, device.device_type,
                                  device.size, profile.id))
    for socket in dumps:
        if profile.device_for(socket) is None:
            raise ConversionRefused(
                "socket %s is not part of the %s profile" % (socket, profile.id))

    for device in profile.devices:
        data = dumps[device.socket]
        digest = sha256(data)
        entry = {"socket": device.socket, "bytes": len(data), "sha256": digest,
                 "device_type": device.device_type,
                 "expected_sha256": device.sha256,
                 "matches_profile": device.sha256 == digest if device.sha256
                                    else None}
        result.inputs[device.socket] = entry
        if device.sha256 and device.sha256 != digest:
            raise ConversionRefused(
                "socket %s does not match the %s profile: expected sha256 %s, "
                "got %s. This is a different revision or a bad read; convert it "
                "with the manual path instead of this profile."
                % (device.socket, profile.id, device.sha256[:16], digest[:16]))

    image = profile.assemble(dumps)
    result.before = image

    if profile.entry_form == "start_end_pairs":
        table = PhraseTable.from_pointer_pairs(
            image, profile.table_offset, profile.phrases,
            base_address=profile.base_address)
    else:
        table = PhraseTable.from_pointers(
            image, profile.table_offset, profile.phrases,
            address_ordered=profile.address_ordered,
            has_end_bound=profile.has_end_bound,
            base_address=profile.base_address)

    # EVERY PHRASE MUST START INSIDE A SPEECH-BEARING DEVICE.
    #
    # `assemble` fills windows no device covers with 0xFF, and 0xF is the stop
    # frame's energy code -- so a pointer into unpopulated space parses as a
    # clean, one-frame phrase. Nothing downstream catches it: it terminates, it
    # changes no bytes, its frame kinds are trivially preserved, and the
    # reconciliation only counts bytes that changed. The result is a ROM missing
    # however many phrases pointed into the gap, reported as a success.
    #
    # The test is the phrase's START, not its whole extent. A phrase's extent is
    # the DECLARED bound -- the next pointer, or the pointer table -- and the
    # speech inside it stops at its stop frame, usually well short. Real sets
    # bound the last phrase in a device with the table that lives in the NEXT
    # device, so requiring the whole extent to be speech-bearing refuses a
    # correct layout, and marking that next device as speech to satisfy it is
    # refused in turn because nothing in it changes. What the extent must not do
    # is carry speech out of the speech devices, and that is checked below,
    # against the bytes conversion actually changed.
    covered = set()
    for device in profile.speech_devices:
        at = device.cpu_address - profile.window_base
        span = device.size * (2 if device.mirrored else 1)
        covered.update(range(at, at + span))
    outside = [p for p in table.phrases if p.start not in covered]
    if outside:
        first = outside[0]
        raise ConversionRefused(
            "phrase %d starts at 0x%X, which is not inside any device the "
            "profile marks as holding speech. Unpopulated space reads as 0xFF, "
            "which parses as a stop frame, so such a phrase looks valid and "
            "converts to nothing -- the ROM would be missing it. %d of %d "
            "phrases are affected."
            % (first.index, first.start, len(outside), len(table.phrases)))

    verdicts = diagnose_last_byte(image, table, src_tables)
    stuck = sorted(i for i, v in verdicts.items() if v == "no stop")
    # A phrase the profile DECLARES unterminated is expected not to stop: in a
    # few sets the player supplies the terminator rather than the ROM. The
    # claim is checked both ways -- an undeclared phrase that does not stop is
    # still refused, and a declared one that DOES stop is refused too, so the
    # field cannot be used to wave a whole layout through.
    declared = set(profile.unterminated_phrases)
    if declared and not allow_unterminated:
        wrong = sorted(i for i in declared if verdicts.get(i) != "no stop")
        if wrong:
            raise ConversionRefused(
                "phrase(s) %s are listed in unterminated_phrases but do end in "
                "a stop frame. That list is for phrases the ROM leaves the "
                "player to terminate."
                % ", ".join(str(i) for i in wrong))
        stuck = [i for i in stuck if i not in declared]
    if stuck and not allow_unterminated:
        raise ConversionRefused(
            "%d phrase(s) in this set do not end in a stop frame (%s). The "
            "profile's layout does not fit these dumps. If the ROM really does "
            "leave the player to terminate them, name them in "
            "layout.unterminated_phrases."
            % (len(stuck), ", ".join(str(i) for i in stuck)))

    patched, results = patch_rom(
        image, table, src_tables, dst_tables,
        truncate_last_byte=profile.truncate_last_byte or False,
        allow_unterminated=(allow_unterminated
                            or sorted(declared) or False))
    result.after = patched
    result.stats = summarise(results)

    # Backstop. `patch_rom` writes only inside phrase extents, so this cannot
    # fire today -- `test_conversion_only_ever_touches_phrase_extents` is what
    # holds that. It stays because the consequence of it ever becoming reachable
    # is a ROM with non-speech bytes rewritten, which nothing downstream checks.
    inside = set()
    for phrase in table.phrases:
        inside.update(range(phrase.start, phrase.end))
    stray = [i for i, (a, b) in enumerate(zip(image, patched))
             if a != b and i not in inside]
    if stray:
        raise ConversionRefused(
            "%d byte(s) outside the phrase extents changed, first at 0x%X. "
            "Refusing to write." % (len(stray), stray[0]))

    # AND EVERY CHANGED BYTE MUST LAND IN A SPEECH-BEARING DEVICE.
    #
    # The per-device reconciliation below catches a change that lands in a
    # device the profile says holds no speech. It cannot catch one that lands
    # in no device AT ALL -- a phrase starting in the last bytes of a device
    # and running on into unmapped space. Those bytes exist only in the
    # assembled image; nothing is emitted for them, so the converted set would
    # be missing the tail of that phrase and every check downstream would pass.
    escaped = [i for i, (a, b) in enumerate(zip(image, patched))
               if a != b and i not in covered]
    if escaped:
        raise ConversionRefused(
            "%d converted byte(s) fall outside every device the profile marks "
            "as holding speech, first at 0x%X. A phrase runs past the end of "
            "its device, so the converted set would be missing it. Check the "
            "layout, and which devices hold speech."
            % (len(escaped), escaped[0]))

    result.phrases = [
        {"index": r.phrase.index, "start": r.phrase.start, "end": r.phrase.end,
         "frames": r.frames, "clamped": r.clamped,
         "approximated": r.approximated, "truncated": r.truncated,
         "last_byte_truncated": r.last_byte_truncated,
         "alias_of": r.alias_of, "changed_bytes": r.changed_bytes,
         "stopped_cleanly": r.stopped_cleanly,
         "final_byte": verdicts.get(r.phrase.index)}
        for r in results]

    # A phrase whose every byte is the fill value is not speech either, even if
    # it does sit inside a device -- an erased region of a real EPROM reads the
    # same as an unpopulated window.
    empty = [r.phrase.index for r in results
             if set(image[r.phrase.start:r.phrase.end]) == {profile.fill}]
    if empty:
        raise ConversionRefused(
            "phrase(s) %s contain nothing but 0x%02X fill bytes, which parse as "
            "a stop frame. Either the layout is wrong or those devices are "
            "erased." % (", ".join(str(i) for i in empty), profile.fill))

    # A PHRASE THAT STARTS WITH A RUN OF SILENCE IS POINTING AT PADDING.
    #
    # Zero bytes parse as silence frames, so a pointer aimed at padding produces
    # a phrase that begins with a long run of them and then continues into
    # whatever follows -- which may be code. It terminates, because some later
    # byte carries a 0xF nibble; its frame kinds survive conversion, because
    # they are re-derived from the same bytes; and nothing else notices. On the
    # real Embryon set this made a 21st "phrase" out of six zero bytes followed
    # by 6800 instructions, and converting it stopped the board booting.
    #
    # The separation is clean rather than a judgement call: across the 20 real
    # phrases of that set, every one begins with ZERO leading silence frames.
    # The padding entry begins with twelve.
    LEADING_SILENCE_LIMIT = 4
    padded = []
    hollow = []
    for record in results:
        frames, _ = parse(bytes(image[record.phrase.start:record.phrase.end]),
                          src_tables.pitch_bits, list(src_tables.k_widths))
        # A PHRASE WHOSE FIRST FRAME IS A STOP FRAME CONVERTS NOTHING.
        #
        # It reports as a clean, terminated phrase and changes not one byte, so
        # every check downstream passes it: the frame kinds are trivially
        # preserved and the reconciliation only counts bytes that changed. It is
        # what a pointer aimed at erased space looks like -- 0xFF is the stop
        # frame's energy code -- and it is what a pointer one entry past the end
        # of a table usually finds. Fathom shipped exactly this.
        #
        # There is no threshold to pick: a real phrase says something, so its
        # first frame is never the one that ends it. Across the sets here, none
        # of 481 phrases begins with a stop frame.
        if frames and frames[0].kind == "stop":
            hollow.append((record.phrase.index, record.phrase.start,
                           record.phrase.end))
            continue
        leading = 0
        for frame in frames:
            if frame.kind != "silence":
                break
            leading += 1
        silence = sum(1 for f in frames if f.kind == "silence")
        # `bool(silence)` cannot fire today: a phrase of stop-and-nothing-else
        # would have to begin with its stop frame, and the guard above already
        # refused that. It stays because the two conditions answer different
        # questions -- "was anything found here" and "is what was found only
        # silence" -- and a later change to either could separate them.
        silent = bool(silence) and all(f.kind in ("silence", "stop")
                                       for f in frames)
        if record.phrase.index in profile.silent_phrases:
            # The profile claims this one is intentional silence. Hold it to
            # that: an exemption that also covers speech would be a way to
            # switch the guard off, which is the opposite of what it is for.
            # It must be silence AND actually contain some -- a lone stop frame
            # is not a silent phrase, it is a phrase that was never found.
            if not silent:
                raise ConversionRefused(
                    "phrase %d is listed in silent_phrases but is not silence "
                    "and nothing else (%d frames, %d of them silence). That "
                    "list is for phrases that say nothing on purpose."
                    % (record.phrase.index, len(frames), silence))
            continue
        if leading >= LEADING_SILENCE_LIMIT:
            padded.append((record.phrase.index, leading))
    if hollow:
        raise ConversionRefused(
            "phrase(s) %s begin with a stop frame, so they convert nothing at "
            "all -- %d of %d phrases. Erased space reads as 0xFF, which IS a "
            "stop frame, so this is what a pointer into a gap or one entry past "
            "the end of the table looks like. The layout is finding something "
            "that is not speech."
            % (", ".join("%d (0x%X-0x%X)" % h for h in hollow[:4]),
               len(hollow), len(results)))
    if padded:
        raise ConversionRefused(
            "phrase(s) %s begin with a long run of silence frames (%s), which "
            "is what a pointer aimed at padding looks like rather than speech. "
            "That entry may be an end bound rather than a phrase -- try one "
            "fewer phrase with has_end_bound set. If the phrase really is "
            "meant to be silent, name it in layout.silent_phrases."
            % (", ".join(str(i) for i, _ in padded),
               ", ".join("%d frames" % n for _, n in padded)))

    # EVERY PHRASE MUST TERMINATE INSIDE A DEVICE.
    #
    # Where the speech STOPS says something the START test cannot. A phrase
    # whose data continues past the end of the device holding it runs into the
    # 0xFF that fills unmapped space and terminates there, because 0xFF is a
    # stop frame -- so its stop frame lands outside every device, which cannot
    # happen for a phrase whose device is present and correctly sized.
    #
    # Be clear about the limit of this. It catches a phrase CUT OFF by a missing
    # or undersized device. It does not, and no check here can, catch a profile
    # that simply declares fewer phrases than the table holds: those phrases are
    # self-contained, so nothing about the ones that ARE declared looks wrong.
    # Flash Gordon v1 was exactly that, and only the traced phrase list found it.
    # See docs/KNOWN_LIMITATIONS.md.
    #
    # In most such layouts the overrun bytes CHANGE, and the converted-bytes
    # check above names them first. This is the backstop for when they happen to
    # convert to themselves: that changes nothing, so a byte comparison cannot
    # see it, while the terminator is still sitting in unmapped space.
    #
    # This is deliberately about the TERMINATOR and not about the declared
    # extent. A phrase is bounded by the next pointer or by the table, and that
    # bound legitimately reaches across unmapped space -- Flash Gordon (French)
    # has a phrase bounded 10 KB away, whose speech stops after 207 bytes, well
    # inside its device. Testing the extent refuses that; testing where the
    # speech ends does not.
    stranded = []
    for record in results:
        if not record.stopped_cleanly:
            continue                    # already refused, or declared
        frames, _ = parse(bytes(image[record.phrase.start:record.phrase.end]),
                          src_tables.pitch_bits, list(src_tables.k_widths))
        if not frames:
            continue
        last = record.phrase.start + (frames[-1].end_bit + 7) // 8 - 1
        if last not in covered:
            stranded.append((record.phrase.index, record.phrase.start, last))
    if stranded:
        index, start, last = stranded[0]
        raise ConversionRefused(
            "phrase %d starts at 0x%X but its speech runs past the end of every "
            "device and only stops at 0x%X, in unmapped space -- %d phrase(s) "
            "do. Unmapped space is 0xFF, which is a stop frame, so this is "
            "what a phrase cut off by a missing or undersized device looks "
            "like. Some of this set's speech would be left unconverted."
            % (index, start, last, len(stranded)))

    # A MIRRORED DEVICE'S TWO WINDOWS MUST AGREE WHERE THEY OVERLAP.
    #
    # A 2 KB part answers at two addresses, and a set is free to reach some
    # phrases through the lower window and others through the mirror -- Eight
    # Ball Deluxe does, and the two groups land on different offsets of the same
    # physical ROM. `extract` merges the halves for exactly that reason.
    #
    # Where a physical offset IS reached through both windows, the two
    # conversions must want the same byte. Two entries naming the same phrase
    # through both windows are harmless: identical alignment, identical output.
    # Two phrases at different alignments are not: only one conversion could
    # survive into the burned device and the other phrase would read as corrupt.
    #
    # The test is on the VALUE each window requires, not on which bytes changed
    # and not on coverage alone. Changed-bytes misses the case where one
    # conversion leaves a byte as it was while the other rewrites it -- they
    # disagree, but only one of them looks like a change. Coverage alone would
    # refuse the harmless duplicate.
    for device in profile.devices:
        if not device.mirrored:
            continue
        at = device.cpu_address - profile.window_base
        halves = []
        for base in (at, at + device.size):
            reached = set()
            for phrase in table.phrases:
                lo = max(phrase.start, base)
                hi = min(phrase.end, base + device.size)
                reached.update(range(lo - base, hi - base))
            halves.append(reached)
        disputed = [i for i in sorted(halves[0] & halves[1])
                    if patched[at + i] != patched[at + device.size + i]]
        if disputed:
            first = disputed[0]
            raise ConversionRefused(
                "socket %s is a mirrored device, and offset 0x%X is inside a "
                "phrase in both of its windows which convert it two different "
                "ways (0x%02X at 0x%04X, 0x%02X at 0x%04X); %d offset(s) "
                "disagree. Those are the same physical byte, so only one of the "
                "two could survive into the burned device and the other phrase "
                "would be read as corrupt. The layout is wrong."
                % (device.socket, first, patched[at + first],
                   profile.window_base + at + first,
                   patched[at + device.size + first],
                   profile.window_base + at + device.size + first,
                   len(disputed)))

    # Split back out, and cross-check each device against what the profile says
    # it should be.
    total_changed = 0
    for device in profile.devices:
        extracted = profile.extract(patched, device, image)
        changed_bytes = sum(1 for a, b in zip(dumps[device.socket],
                                              extracted.data) if a != b)
        # Reconciliation counts WINDOWS, not devices. A mirrored device appears
        # at two addresses, so if a layout converts through both, the image
        # changes in twice as many places as the single physical device holds.
        # Comparing the device's own count against the image total would then
        # fail on a layout that is perfectly valid.
        at = device.cpu_address - profile.window_base
        span = device.size * (2 if device.mirrored else 1)
        window_changed = sum(1 for i in range(at, at + span)
                             if image[i] != patched[i])
        total_changed += window_changed
        if device.holds_speech and not extracted.changed:
            raise ConversionRefused(
                "socket %s is marked as holding speech but nothing in it "
                "changed. The layout is not finding its phrases."
                % device.socket)
        if not device.holds_speech and extracted.changed:
            raise ConversionRefused(
                "socket %s is marked as holding no speech but it changed. "
                "Refusing to write." % device.socket)
        # What FRACTION of a speech-bearing device the layout actually reached.
        # A layout that finds only a corner of the speech still converts, still
        # boots, and still leaves most of the ROM unconverted -- one real set
        # was measured converting 1.5% of its speech while behaving normally in
        # board simulation. Correct layouts across the sets checked ran 33-70%.
        # Reported rather than gated: the range is too wide for a threshold,
        # and a low number is something a technician should see and judge.
        # Union of the extents, not the sum of them. Duplicate pointers are
        # legal -- two commands can name one phrase -- and adding their lengths
        # counted the same bytes twice, which produced coverage above 100% on a
        # real set and would have read as "more than the whole device".
        spans = []
        for phrase in sorted(table.phrases, key=lambda p: p.start):
            lo = max(phrase.start, at)
            hi = min(phrase.end, at + span)
            if hi <= lo:
                continue
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], hi)
            else:
                spans.append([lo, hi])
        covered = sum(hi - lo for lo, hi in spans)
        result.outputs.append({
            "socket": device.socket,
            "speech_coverage_percent": (round(100.0 * covered / span, 1)
                                        if span and device.holds_speech
                                        else None),
            "device_type": device.device_type,
            "bytes": len(extracted.data),
            "sha256": sha256(extracted.data),
            "changed_bytes": changed_bytes,
            "window_changed_bytes": window_changed,
            "changed": extracted.changed,
            "taken_from_mirror": extracted.from_mirror,
            "window": [extracted.window[0], extracted.window[1]],
            "data": extracted.data,
        })

    # Backstop, like the stray-byte check above: a well-formed profile's devices
    # span every window a pointer can reach, so this cannot fire today.
    # `TestBackstops` holds that property. It stays because the consequence is a
    # byte count that does not describe what was actually burned.
    if total_changed != result.stats["bytes_changed"]:
        raise ConversionRefused(
            "changed bytes do not reconcile: %d across the devices, %d in the "
            "image. Some change lies outside every device window."
            % (total_changed, result.stats["bytes_changed"]))

    if result.stats["frames_clamped"]:
        result.warnings.append(
            "%d frame(s) (%.1f%%) sit below the %s pitch floor and were raised; "
            "those will sound higher than the original."
            % (result.stats["frames_clamped"], result.stats["clamped_percent"],
               target.id))
    if profile.status != "silicon-verified":
        result.warnings.append(
            "profile status is %r: no converted ROM from this profile has been "
            "played on a real board." % profile.status)
    if allow_unterminated:
        result.overrides.append("allow_unterminated")
    if source_tables or target_tables:
        result.overrides.append("custom_tables")
        result.warnings.append(
            "CUSTOM COEFFICIENT TABLES were used (%s). Nothing checks that a "
            "supplied table describes the part you named, so this output is NOT "
            "known to be quantised for a %s. The files are named and recorded "
            "as `custom`."
            % (", ".join(str(t) for t in (source_tables, target_tables) if t),
               target.id))
    result.custom_tables = bool(source_tables or target_tables)

    result.manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "tool": "understudy",
        "understudy_version": __version__,
        "profile": {"id": profile.id, "version": profile.version,
                    "title": profile.label, "status": profile.status,
                    # By content, not just by name. An id and a version say
                    # which profile was MEANT; the hash says which one actually
                    # authorised this conversion, which is what a later bug
                    # report needs.
                    "sha256": profile.digest,
                    "applies_to": profile.revisions,
                    # A package-relative identity for bundled profiles: an
                    # absolute path is not portable, leaks a workstation layout,
                    # and makes a manifest look like a record of one machine.
                    "source": profile.identity},
        "chips": {
            "source": ("custom" if source_tables else result.source_chip.id),
            "target": ("custom" if target_tables else target.id),
            "requested_source": result.source_chip.id,
            "requested_target": target.id,
        },
        "tables": {
            "source": _table_identity(result.source_chip, source_tables,
                                      src_tables, src_raw, src_path),
            "target": _table_identity(target, target_tables, dst_tables,
                                      dst_raw, dst_path),
        },
        "layout": {"table_offset": profile.table_offset,
                   "phrases": profile.phrases,
                   "base_address": profile.base_address,
                   "address_ordered": profile.address_ordered,
                   "has_end_bound": profile.has_end_bound,
                   "truncate_last_byte": list(profile.truncate_last_byte),
                   "window_base": profile.window_base,
                   "window_size": profile.window_size},
        "inputs": list(result.inputs.values()),
        "outputs": [{k: v for k, v in o.items() if k != "data"}
                    for o in result.outputs],
        "image": {"before_sha256": sha256(image),
                  "after_sha256": sha256(patched),
                  "bytes": len(image)},
        "summary": result.stats,
        "phrase_rows": ("one row per pointer in the layout; a row with alias_of "
                        "set repeats an earlier row's phrase and is excluded "
                        "from the summary totals"),
        "phrases": result.phrases,
        "warnings": result.warnings,
        "overrides": result.overrides,
    }
    return result


def output_name(source_name: str, device, target: Chip,
                custom_tables: bool = False) -> str:
    """A filename that says what the file is and what to burn it into.

    It carries the socket AND the device type, because those are the two things
    a technician needs at the programmer, and a file named only for the socket
    invites burning a 2716 image into a 2532.

    With custom tables the target is named `custom` rather than the part that
    was requested: nothing checked that the supplied table describes that part,
    and a file called `..._tsp5220c.bin` says it did.
    """
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix or ".bin"
    label = "custom" if custom_tables else target.id
    return "%s_%s_%s_%s%s" % (stem, device.socket, device.device_type, label,
                              suffix)
