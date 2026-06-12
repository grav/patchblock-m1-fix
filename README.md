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

## Connecting the device

The LPC1343's ROM bootloader only starts at **power-on**, so the device must be
powered on while USB is already connected to show up as `CRP DISABLD`. On top
of that, its 2009-era USB mass-storage implementation is flaky on modern macOS:
sometimes the device enumerates but the disk never attaches (or drops off again
after a while), traditionally fixed by unplugging and replugging the cable.

`connect_patchblock.sh` automates all of it:

```sh
./connect_patchblock.sh    # then power the Patchblock ON with USB connected
```

It waits for the bootloader, mounts the disk if macOS didn't, and if the device
gets stuck (enumerated but no disk) it forces a software USB re-enumeration —
the digital equivalent of a replug — via the bundled `usbreplug.c` helper
(compiled automatically on first run; no sudo needed).

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

## Related

[community-firmware.md](community-firmware.md) — optionally upgrade the on-chip
firmware to the community v1.5.3 template, which fixes MIDI dropped/ghost notes
(e.g. the MIDI polysynth example).

[pbp-format.md](pbp-format.md) — the reverse-engineered `.pbp` patch file
format, with [`pbp.py`](pbp.py), a tool that dumps/round-trips patch files and
extracts the patch embedded in a `firmware.bin`.

## Headless compiling (no GUI at all)

[`pbc.py`](pbc.py) replicates the IDE's code generation: it turns a `.pbp`
patch into `main.c` (block structs, functions, wiring, rate handlers), which
the app's bundled ARM toolchain then compiles. Together with the flash script
this is a complete GUI-free pipeline:

```sh
./pbc.py mypatch.pbp main.c
cp main.c /Applications/Patchblocks.app/Contents/MacOS/compile/firmware/
(cd /Applications/Patchblocks.app/Contents/MacOS/compile/firmware && ./compile.sh)
./flash_patchblock.sh       # checksum + in-place write to the connected device
```

`pbc.py` is validated by reproducing the app's own generated `main.c`
**byte-for-byte** for reference patches. One deliberate divergence: the app
demotes generator blocks whose inputs all come from control-rate sources down
to the 100 Hz control handler (rewriting `SMP_RATE` to `CTL_RATE` in their
code). That is right for LFOs but produces aliased garbage when the generator
is an audible oscillator (e.g. a Saw whose pitch comes from a Sequence block);
`pbc.py` keeps generators at audio rate, which in A/B tests on hardware sounds
correct where the app's build does not.

`flash_patchblock.sh` (with `lpccrc.py`) flashes any firmware image to a
connected device: patches the LPC boot checksum and writes in place.

## Notes

Tested on an M1 Mac, macOS 14.5, against real hardware. This edits an app bundle
and writes to flash; the LPC's USB ISP bootloader is in ROM and isn't touched, so
the worst likely outcome is "still doesn't boot," not a brick.

## License and warranty

MIT licensed — see [LICENSE](LICENSE).

There is **no warranty**. This software is provided "as is", and you use it at
your own risk. The author is not liable for any damage to your hardware,
software, or data resulting from its use.
