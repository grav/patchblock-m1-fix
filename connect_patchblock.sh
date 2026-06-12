#!/bin/bash
#
# Wait for a Patchblock bootloader ("CRP DISABLD") and make sure it mounts.
#
# Usage: ./connect_patchblock.sh   then power the Patchblock ON with USB
# already connected (the LPC1343 ROM only enters the bootloader at power-on).
#
# Handles both macOS failure modes of the LPC's quirky USB mass storage:
#  - disk attaches but doesn't auto-mount        -> mounts it explicitly
#  - device enumerates but disk never attaches,
#    or the disk drops off after a while         -> forces a USB re-enumeration
#                                                   (./usbreplug, the software
#                                                   equivalent of a replug)
set -u
VOL="/Volumes/CRP DISABLD"
HERE="$(cd "$(dirname "$0")" && pwd)"
STUCK=0

# build the re-enumeration helper on first run
if [ ! -x "$HERE/usbreplug" ] && [ -f "$HERE/usbreplug.c" ]; then
  echo "building usbreplug..."
  clang -o "$HERE/usbreplug" "$HERE/usbreplug.c" -framework IOKit -framework CoreFoundation
fi

echo "Waiting for Patchblock... (power it ON with USB connected)"
for i in $(seq 1 90); do
  if [ -d "$VOL" ]; then
    echo "mounted: $VOL"
    exit 0
  fi
  DEV=$(diskutil list 2>/dev/null | awk '/CRP DISABLD/{print $NF}' | head -1)
  if [ -n "${DEV:-}" ]; then
    STUCK=0
    diskutil mount "$DEV" >/dev/null 2>&1
    [ -d "$VOL" ] && { echo "mounted: $VOL"; exit 0; }
  elif ioreg -p IOUSB -l 2>/dev/null | grep -qi "LPC13XX"; then
    # bootloader on the bus but no disk: give it 8s, then software-replug
    STUCK=$((STUCK+1))
    if [ "$STUCK" -ge 8 ]; then
      echo "stuck (USB up, no disk) - forcing re-enumeration..."
      "$HERE/usbreplug" || true
      STUCK=0
    fi
  fi
  sleep 1
done
echo "timed out after 90s. Power-cycle the device with USB connected and retry."
exit 1
