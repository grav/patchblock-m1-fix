# patchblock-m1-fix

Fixes the Patchblocks IDE so it can compile and upload patches on Apple Silicon
Macs. On recent macOS, **Compile & Upload** produces a device that doesn't boot.

```sh
./patch-patchblocks.sh                 # patches /Applications/Patchblocks.app
./patch-patchblocks.sh --revert        # undo
```

You can also pass a specific bundle, e.g. `./patch-patchblocks.sh /Applications/Patchblocks_copy.app`.

Then in the app: connect the Patchblock, hit **Compile & Upload**, wait for the
upload (~30 s), and power-cycle the device. Uses only tools already on macOS
(`bash`, `perl`, `dd`, `diskutil`).

## What was broken

Patchblocks use an NXP LPC13xx (Cortex-M3). The device shows up over USB as a FAT
drive named `CRP DISABLD`; you flash it by writing `firmware.bin` to that drive.
Two steps of the Mac toolchain broke, both needed fixing:

1. **No boot checksum.** The LPC bootloader only starts the firmware if the word
   at offset `0x1C` (the 8th exception vector) is the two's complement of the
   first 7 vectors, so the first eight 32-bit words sum to zero. Patchblocks
   wrote this with `lpcrc`, an Intel binary that fails on Apple Silicon
   (`Bad CPU type in executable`), leaving the checksum at `00000000`. Replaced
   with an inline `perl` computation.

2. **The file gets relocated.** On the LPC's emulated FAT volume the firmware
   maps directly onto flash sectors, so it must be overwritten in place. macOS's
   `cp` deletes and recreates the file, allocating different clusters, so flash
   `0x0` is never reprogrammed. Replaced with `dd … conv=notrunc`.

## What the patcher changes

Inside `<App>.app/Contents/MacOS/compile/firmware/`:

| file | before | after |
|------|--------|-------|
| `compile.sh` | runs `./lpcrc` (fails on M1) | writes the checksum inline with `perl` |
| `copy.sh` | `cp` + unmount | writes the checksum, then `dd … conv=notrunc` in place, then unmounts |

Originals are saved as `compile.sh.orig` / `copy.sh.orig`. Re-running is safe;
`--revert` restores them.

## Manual flashing

If you build firmware outside the app, the same two steps by hand:

```sh
# write the LPC boot checksum
perl -e 'open(F,"+<","firmware.bin");binmode F;read(F,$h,32);@v=unpack("V8",$h);
         $s=0;$s=($s+$v[$_])&0xFFFFFFFF for 0..6;
         seek(F,0x1C,0);print F pack("V",(-$s)&0xFFFFFFFF);close F;'

# write it to the device in place
dd if=firmware.bin of="/Volumes/CRP DISABLD/firmware.bin" bs=512 conv=notrunc
sync && diskutil unmount "/Volumes/CRP DISABLD"
```

## Notes

Tested on an M1 Mac, macOS 14.5, against real hardware. This edits an app bundle
and writes to flash; the LPC's USB ISP bootloader is in ROM and isn't touched, so
the worst likely outcome is "still doesn't boot," not a brick.

## License and warranty

MIT licensed — see [LICENSE](LICENSE).

There is **no warranty**. This software is provided "as is", and you use it at
your own risk. The author is not liable for any damage to your hardware,
software, or data resulting from its use.
