#!/usr/bin/env bash
#
# patch-patchblocks.sh
#
# Makes Patchblocks.app able to compile AND flash patches from a modern Mac,
# including Apple Silicon (M1/M2/M3). See README.md for the full story.
#
# It fixes two steps inside the app bundle
# (<App>.app/Contents/MacOS/compile/firmware/):
#
#   compile.sh : the `./lpcrc` step is a dead Intel binary on Apple Silicon
#                ("Bad CPU type in executable"), so the firmware shipped with an
#                empty LPC boot checksum and the chip refused to start. We write
#                the checksum inline with perl instead.
#
#   copy.sh    : `cp firmware.bin /Volumes/CRP DISABLD/...` makes macOS delete &
#                recreate the file, relocating its FAT clusters so flash 0x0 is
#                never programmed. We overwrite the existing file IN PLACE with
#                `dd conv=notrunc`, like the Windows IDE does.
#
# Originals are saved next to each file as *.orig. Re-running is safe.
# Revert with:  ./patch-patchblocks.sh --revert [/Applications/Patchblocks.app]
#
set -euo pipefail

PROG="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $PROG [--revert] [APP_PATH ...]

  APP_PATH   Path to a Patchblocks.app bundle.
             Defaults to /Applications/Patchblocks.app

  --revert   Restore the original compile.sh and copy.sh from the .orig backups.
  -h, --help Show this help.

Examples:
  $PROG                                   # patch /Applications/Patchblocks.app
  $PROG /Applications/Patchblocks_copy.app
  $PROG --revert /Applications/Patchblocks.app
EOF
}

REVERT=0
APPS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --revert|--unpatch) REVERT=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "$PROG: unknown option: $1" >&2; usage >&2; exit 1 ;;
    *) APPS+=("$1") ;;
  esac
  shift
done
[ ${#APPS[@]} -gt 0 ] || APPS=("/Applications/Patchblocks.app")

# The LPC boot checksum: vector 8 (offset 0x1C) = two's complement of the first
# 7 interrupt vectors, so the first 8 little-endian words sum to zero. This is a
# drop-in replacement for the `lpcrc` tool. Kept identical in compile.sh & copy.sh.
CKSUM_PERL='/usr/bin/perl -e '\''open(F,"+<","firmware.bin")or die "no firmware.bin: $!";binmode F;read(F,$h,32);@v=unpack("V8",$h);$s=0;$s=($s+$v[$_])&0xFFFFFFFF for 0..6;seek(F,0x1C,0);print F pack("V",(-$s)&0xFFFFFFFF);close F;'\'''

# Replace the './lpcrc firmware.bin' line in compile.sh with the inline checksum.
# Done as a literal line swap in bash so the perl one-liner's $-vars survive.
replace_lpcrc_line() {
  local f="$1" line tmp replaced=0
  tmp="$(mktemp)"
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$replaced" -eq 0 ] && [ "${line#./lpcrc }" != "$line" ]; then
      printf '%s\n' "# lpcrc replaced (dead Intel binary on Apple Silicon) -- write LPC boot checksum inline:" >> "$tmp"
      printf '%s\n' "$CKSUM_PERL" >> "$tmp"
      replaced=1
    else
      printf '%s\n' "$line" >> "$tmp"
    fi
  done < "$f"
  cat "$tmp" > "$f"   # overwrite content, keep original file perms/inode
  rm -f "$tmp"
}

write_copy_sh() {
  cat > "$1" <<EOF
#!/bin/bash
#
# Patchblocks upload step, fixed for macOS / Apple Silicon by patch-patchblocks.sh.
# Original (broken) version did a plain cp + eject, which wrote no LPC checksum
# and relocated the file so flash 0x0 was never programmed. Original: copy.sh.orig
#
cd "\$(dirname "\$0")"
VOL="/Volumes/CRP DISABLD"

# 1. Write the LPC boot checksum (replacement for the dead \`lpcrc\`).
$CKSUM_PERL

# 2. Overwrite the device file IN PLACE so the flash sectors at 0x0 are
#    actually reprogrammed (a plain cp relocates the file and bricks boot).
if [ -d "\$VOL" ]; then
  dd if=firmware.bin of="\$VOL/firmware.bin" bs=512 conv=notrunc 2>&1
  sync
  rm -rf "\$VOL/.fseventsd" "\$VOL/.Trashes" "\$VOL/.Spotlight-V100" 2>/dev/null
  sync
  diskutil unmount "\$VOL" 2>&1
fi
EOF
  chmod +x "$1"
}

patch_app() {
  local app="$1"
  local dir="$app/Contents/MacOS/compile/firmware"
  local compile="$dir/compile.sh"
  local copy="$dir/copy.sh"

  if [ ! -d "$dir" ]; then
    echo "  ✗ not a Patchblocks app (missing $dir)"; return 1
  fi

  # --- compile.sh: replace the dead lpcrc call ---
  if [ -f "$compile" ]; then
    if grep -q 'lpcrc replaced' "$compile"; then
      echo "  • compile.sh already patched"
    else
      [ -f "$compile.orig" ] || cp "$compile" "$compile.orig"
      if grep -qE '^\./lpcrc ' "$compile"; then
        replace_lpcrc_line "$compile"
        echo "  ✓ compile.sh patched (lpcrc -> inline checksum)"
      else
        echo "  ! compile.sh has no './lpcrc' line; left unchanged"
      fi
    fi
  else
    echo "  ! no compile.sh found"
  fi

  # --- copy.sh: in-place flash instead of cp + eject ---
  if [ -f "$copy" ]; then
    if ! grep -q 'fixed for macOS / Apple Silicon' "$copy"; then
      [ -f "$copy.orig" ] || cp "$copy" "$copy.orig"
    fi
  fi
  write_copy_sh "$copy"
  echo "  ✓ copy.sh installed (checksum + in-place flash)"
}

revert_app() {
  local app="$1"
  local dir="$app/Contents/MacOS/compile/firmware"
  local n=0
  for f in compile.sh copy.sh; do
    if [ -f "$dir/$f.orig" ]; then
      cp "$dir/$f.orig" "$dir/$f"
      echo "  ✓ restored $f"
      n=$((n+1))
    fi
  done
  [ "$n" -gt 0 ] || echo "  • nothing to revert (no .orig backups found)"
}

for app in "${APPS[@]}"; do
  echo "==> $app"
  if [ "$REVERT" -eq 1 ]; then revert_app "$app"; else patch_app "$app"; fi
done

echo
if [ "$REVERT" -eq 1 ]; then
  echo "Reverted. The app is back to its original (broken-on-Mac) behaviour."
else
  echo "Done. In Patchblocks.app: connect the device, hit Compile & Upload"
  echo "(the upload takes ~30s -- that is the flash being programmed), then"
  echo "power-cycle the Patchblock to run your patch."
fi
