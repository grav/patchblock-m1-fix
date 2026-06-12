#!/usr/bin/env python3
"""
Drop-in replacement for the Patchblocks `lpcrc` tool, which is an old Intel
binary that won't run on Apple Silicon ("Bad CPU type in executable").

NXP LPC13xx (Cortex-M3) bootloaders validate a checksum stored in the 8th
interrupt vector (offset 0x1C): the two's complement of the sum of the first
7 vectors, so that vectors[0..7] sum to zero. Without a valid value the chip
stays in its USB ISP "CRP DISABLD" bootloader and never runs the app.

Usage: python3 lpccrc.py <firmware.bin>   # patches the file in place
"""
import sys, struct

def patch(path: str) -> int:
    data = bytearray(open(path, "rb").read())
    if len(data) < 32:
        raise SystemExit(f"{path}: too small to be LPC firmware")
    v = list(struct.unpack("<8I", data[:32]))
    cksum = (-sum(v[0:7])) & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x1C, cksum)
    open(path, "wb").write(data)
    return cksum

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    ck = patch(sys.argv[1])
    print(f"patched {sys.argv[1]}: checksum @0x1C = 0x{ck:08X}")
