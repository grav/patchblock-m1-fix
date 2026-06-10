# The Patchblocks `.pbp` patch file format (reverse-engineered)

The Patchblocks IDE saves patches as `.pbp` files, an undocumented binary
format. This describes the format, reverse-engineered from the 35 example and
tutorial patches shipped with the app (format versions 3 and 4) plus patches
saved by the current Mac app (version 6).

Confidence: a parser/serializer built from this spec round-trips **all 36
sample files byte-identically**, and every wire in every file resolves to a
valid block. See [`pbp.py`](pbp.py) in this repo:

```sh
./pbp.py dump  mypatch.pbp        # human-readable dump
./pbp.py json  mypatch.pbp        # JSON
./pbp.py dump  firmware.bin       # extract the patch embedded in a firmware
./pbp.py roundtrip mypatch.pbp    # verify parse->serialize is lossless
```

All integers are **big-endian**. A *string* is a `u16` length followed by that
many bytes (latin-1; may be empty; comments may contain HTML and newlines).

## Container

| field | type | notes |
|---|---|---|
| version | u16 | 3, 4 or 6 observed, depending on app era |
| payload size | u32 | size of the decompressed payload |
| payload | zlib stream | deflate of the structure below |
| trailer | u32 | usually 0; nonzero in a few old patches (purpose unknown) |

(`file` misidentifies `.pbp` as "TTComp archive" — it is just zlib at offset 6.)

The same container is **embedded in compiled `firmware.bin`** between the ASCII
markers `[>` and `<]`. That is how the IDE reads a patch back from a connected
device — and why a patch survives even when the firmware fails to boot.

## Payload

### Header

| field | type | notes |
|---|---|---|
| name | string | patch name |
| canvas x, y | u16 ×2 | scroll position of the editor canvas |
| ? | u8 | usually 0 |
| ? | u16 | usually 0 |
| timestamp | u32 | save time, unix epoch (UTC) |
| counter | u16 | counter, purpose not pinned down |
| zoom? | u8 | 0x1F in almost all files |
| extra | u16 | **only version ≥ 6**; 0x0001 observed |
| selection? | u16 | 0xFFFF in all files |
| ? | u8 | 0 |

### Comment list (canvas annotations)

Records repeat until the next u16 would be `0xFFFF` (terminator, then consumed):

| field | type | notes |
|---|---|---|
| id | u16 | object id (ascending with holes — ids are not reused) |
| x, y | u16 ×2 | canvas position |
| text | string | may be empty, plain text or HTML |
| flag | u8 | **only version 3**; 0 or 1 |

### Group list

After the comment terminator: `u16` unknown (0) and `u32` unknown
(counter-like), then records until a `0xFFFF` terminator:

| field | type | notes |
|---|---|---|
| id | u8 | group id, referenced by blocks |
| ? | u32 | unknown (often 0) |

Then one unknown `u8` (0).

### Block list

Records repeat until end of payload:

| field | type | notes |
|---|---|---|
| name | string | display name, e.g. `MIDI Clock In` |
| type id | string | 4 hex chars, e.g. `65af` — stable per block definition across patches and years; derivation unknown, treat as an opaque key |
| group | u8 | group id from the group list, 0 = none |
| instance | u16 | unique instance id, the target of connections |
| x, y | u16 ×2 | canvas position |
| values | string | `;`-separated values of the block's editable inputs/variables, in socket order (e.g. `1;0;0;0`) |
| n | u8 | number of outgoing connections |
| connections | n × 4 bytes | `u8 srcOut, u16 dest instance, u8 destIn` |

Wires are stored only on their source block.

## Worked example

A small test patch (v6) decodes to:

```
patch 'patch'  (format v6, saved 2026-05-25 20:56 UTC)
  [4] MIDI Clock In (type 65af)  values='1;0;0;0'   out0 --> [5] Split.in0
  [5] Split         (type 5a91)  values='0;0;0;0'   out0 --> [1] LEDs.in1
                                                    out1 --> [3] Audio Output.in0
  [1] LEDs          (type e31e)  values='0;0;0'
  [2] Controls      (type f085)  values='0;0;0;0;1' out2 --> [1] LEDs.in0
  [3] Audio Output  (type e86f)  values='0;0;0;0;0'
```

## Open questions

- Derivation of the 4-hex block **type id**. It is not a CRC16/CRC32/Adler of
  the block's XML file, name, file name, data/function name or function body
  (all tested). In practice, harvest ids by name from existing patches.
- Exact meaning of `counter`, the v6 `extra` field, the group `u32`, the
  container trailer, and the v3 comment flag.
- Block *definitions* are plain XML in
  `Patchblocks.app/Contents/MacOS/blocks/<category>/*.xml`. Patches saved with
  embedded custom blocks may use additional structures not covered here.

Since the format can be both read and written, patches can be generated
programmatically and then opened in the IDE to compile and upload.
