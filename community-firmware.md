# Upgrading the Patchblocks on-chip firmware (MIDI fixes)

The firmware that ships inside Patchblocks.app (Mindflood template **v0.5.1**) has
MIDI bugs. With the stock firmware, the bundled **MIDI polysynth** example drops
notes and produces ghost (stuck) notes.

The community-maintained firmware template (**v1.5.3**, by Theo Niessink and
Chris Jeffery) fixes this. After installing it and re-flashing, the same MIDI
polysynth example works perfectly — no dropped or ghost notes.

It is the same base firmware with a focused set of MIDI changes added:

- Fixed hanging/ghost notes with controllers that send Channel Pressure
  (after-touch) or Program Change.
- Fixed 2-byte MIDI message handling.
- Fixed Pitch Bend on MIDI channels other than channel 1.
- Added MIDI note priority (low / high / last-note) for mono patches.
- Added MIDI running status support.
- Added runtime MIDI-Through control.

The non-MIDI parts of the firmware (audio engine, pots, GPIO, LEDs) are
unchanged, so this is a low-risk upgrade.

Source: <https://github.com/patchblocks/Community-Firmware>

## Install

The app builds firmware from a single template file,
`Contents/MacOS/compile/templ_chip.txt`. Installing the community firmware means
replacing that file.

```sh
APP="/Applications/Patchblocks.app/Contents/MacOS/compile"

# 1. Retrieve the community template from GitHub
curl -L -o /tmp/templ_chip.txt \
  https://raw.githubusercontent.com/patchblocks/Community-Firmware/master/templ_chip.txt

# 2. Back up the stock template (once), then install the community one
[ -f "$APP/templ_chip.txt.orig" ] || cp "$APP/templ_chip.txt" "$APP/templ_chip.txt.orig"
cp /tmp/templ_chip.txt "$APP/templ_chip.txt"
```

Then in Patchblocks.app: quit and reopen it, open a patch, and **Compile &
Upload** as usual. (On Apple Silicon you also need the upload fix from this repo
— see the main [README](README.md).)

## Revert

```sh
APP="/Applications/Patchblocks.app/Contents/MacOS/compile"
cp "$APP/templ_chip.txt.orig" "$APP/templ_chip.txt"
```

## Notes

- Verifying the version: the community template defines
  `COMMUNITY_FIRMWARE_VERSION 10503` (= 1.5.3); the stock template has no such
  define.
- The app prints `Content Not Found!` around compile time. That is unrelated —
  it is the app failing to reach the long-dead `mindflood.de` online patch
  database, and is harmless.
- Tested on an M1 Mac, macOS 14.5, against real hardware.
