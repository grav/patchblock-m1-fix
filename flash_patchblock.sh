#!/bin/bash
#
# Flash a compiled firmware to a Patchblock from macOS (incl. Apple Silicon).
#
# Replaces the two broken steps of the Mac Patchblocks toolchain:
#   1. `lpcrc` (can't run on M1) -> we patch the LPC boot checksum ourselves.
#   2. macOS Finder/cp deletes & recreates firmware.bin, moving its FAT
#      clusters so the bootloader doesn't program flash 0x0 -> we overwrite
#      the existing file IN PLACE (dd conv=notrunc), like the Windows IDE does.
#
# Usage: ./flash_patchblock.sh <firmware.bin>
#
set -euo pipefail

# Default to the firmware the Patchblocks app just compiled.
APP_FW="/Applications/Patchblocks.app/Contents/MacOS/compile/firmware/firmware.bin"
FW="${1:-$APP_FW}"
VOL="/Volumes/CRP DISABLD"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$FW" ]; then
  echo "firmware not found: $FW"
  echo "usage: $0 [firmware.bin]   (defaults to the app's build output)"; exit 1
fi
if [ ! -d "$VOL" ]; then
  echo "Patchblock not found at '$VOL'."
  echo "Connect the device via USB (it may need a few re-plugs) and retry."
  exit 1
fi

# Work on a copy so the source firmware is never modified.
TMP="$(mktemp -t pbfw)"
trap 'rm -f "$TMP"' EXIT
cp "$FW" "$TMP"

echo "1. Patching LPC boot checksum..."
python3 "$HERE/lpccrc.py" "$TMP"

DEV="$(diskutil info "$VOL" | awk -F: '/Device Node/{gsub(/ /,"",$2);print $2}')"

echo "2. Writing in place to $VOL/firmware.bin"
echo "   (this is slow on purpose -- the bytes are being programmed into flash)"
dd if="$TMP" of="$VOL/firmware.bin" bs=512 conv=notrunc
sync

# Don't let macOS flush metadata folders onto the flash.
rm -rf "$VOL/.fseventsd" "$VOL/.Trashes" "$VOL/.Spotlight-V100" 2>/dev/null || true
sync

echo "3. Unmounting..."
diskutil unmount "${DEV:-$VOL}"

echo
echo "Done. Power-cycle the Patchblock (unplug/replug) to run the new patch."
