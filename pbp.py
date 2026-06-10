#!/usr/bin/env python3
"""
pbp.py — read/write Patchblocks .pbp patch files (reverse-engineered).

Usage:
  pbp.py dump  <file.pbp|firmware.bin>     human-readable dump
  pbp.py json  <file.pbp|firmware.bin>     JSON dump
  pbp.py roundtrip <file.pbp>              parse + re-serialize, verify identical

Works on .pbp files saved by the IDE (format versions 3, 4 and 6) and on
compiled firmware.bin images, which embed the same serialized patch between
"[>" and "<]" markers (that is how the IDE loads a patch back from a device).

Format summary (see PBP-FORMAT.md for details):
  container: u16be version | u32be payload size | zlib(payload) | u32be trailer
  payload:   patch name, canvas pos, save timestamp, then three lists:
             comments, groups, blocks (with typed connections).
All integers big-endian. Strings are u16be-length-prefixed.
"""
import sys, json, struct, zlib, datetime


def _extract_container(raw):
    """Return container bytes from a .pbp file or a firmware image."""
    if raw[:2] in (b'\x00\x03', b'\x00\x04', b'\x00\x06') and raw[2:6] != b'':
        # plausible bare .pbp container
        ver, size = struct.unpack('>HI', raw[:6])
        if 0 < size < 10_000_000:
            return raw
    i = raw.find(b'[>')
    if i >= 0:
        return raw[i+2:]
    raise SystemExit("not a .pbp container and no '[>' firmware marker found")


def parse(raw):
    raw = _extract_container(raw)
    ver, size = struct.unpack('>HI', raw[:6])
    z = zlib.decompressobj()
    d = z.decompress(raw[6:]); d += z.flush()
    if len(d) != size:
        raise ValueError(f"payload size mismatch: header says {size}, got {len(d)}")
    trailer = struct.unpack('>I', z.unused_data[:4])[0] if len(z.unused_data) >= 4 else 0

    p = [0]
    def u8():  v = d[p[0]]; p[0] += 1; return v
    def u16(): v = struct.unpack('>H', d[p[0]:p[0]+2])[0]; p[0] += 2; return v
    def u32(): v = struct.unpack('>I', d[p[0]:p[0]+4])[0]; p[0] += 4; return v
    def rs():
        n = u16(); v = d[p[0]:p[0]+n]; p[0] += n
        return v.decode('latin1')
    def peek16(): return struct.unpack('>H', d[p[0]:p[0]+2])[0]

    r = {'version': ver, 'trailer': trailer}
    r['name'] = rs()
    r['canvas_x'], r['canvas_y'] = u16(), u16()
    r['h1'] = u8(); r['h2'] = u16()
    r['timestamp'] = u32()
    r['counter'] = u16()
    r['zoom'] = u8()
    if ver >= 6:
        r['extra'] = u16()
    r['sel'] = u16()           # 0xFFFF observed everywhere = no selection
    r['h3'] = u8()

    r['comments'] = []
    while peek16() != 0xFFFF:
        c = {'id': u16(), 'x': u16(), 'y': u16(), 'text': rs()}
        if ver <= 3:
            c['flag'] = u8()
        r['comments'].append(c)
    u16()

    r['m1'] = u16(); r['m2'] = u32()
    r['groups'] = []
    while peek16() != 0xFFFF:
        r['groups'].append({'id': u8(), 'val': u32()})
    u16()
    r['sep2'] = u8()

    r['blocks'] = []
    while p[0] < len(d):
        b = {'name': rs(), 'type_id': rs(), 'group': u8(), 'inst': u16(),
             'x': u16(), 'y': u16(), 'values': rs()}
        n = u8()
        b['conns'] = []
        for _ in range(n):
            b['conns'].append({'out': u8(), 'dest': u16(), 'in': u8()})
        r['blocks'].append(b)
    return r


def serialize(r):
    out = bytearray()
    def u8(v):  out.append(v)
    def u16(v): out.extend(struct.pack('>H', v))
    def u32(v): out.extend(struct.pack('>I', v))
    def ws(s):
        b = s.encode('latin1'); u16(len(b)); out.extend(b)
    ws(r['name'])
    u16(r['canvas_x']); u16(r['canvas_y']); u8(r['h1']); u16(r['h2'])
    u32(r['timestamp']); u16(r['counter']); u8(r['zoom'])
    if r['version'] >= 6:
        u16(r['extra'])
    u16(r['sel']); u8(r['h3'])
    for c in r['comments']:
        u16(c['id']); u16(c['x']); u16(c['y']); ws(c['text'])
        if r['version'] <= 3:
            u8(c['flag'])
    u16(0xFFFF)
    u16(r['m1']); u32(r['m2'])
    for g in r['groups']:
        u8(g['id']); u32(g['val'])
    u16(0xFFFF); u8(r['sep2'])
    for b in r['blocks']:
        ws(b['name']); ws(b['type_id']); u8(b['group']); u16(b['inst'])
        u16(b['x']); u16(b['y']); ws(b['values'])
        u8(len(b['conns']))
        for c in b['conns']:
            u8(c['out']); u16(c['dest']); u8(c['in'])
    payload = bytes(out)
    comp = zlib.compress(payload, 9)
    return struct.pack('>HI', r['version'], len(payload)) + comp + struct.pack('>I', r['trailer'])


def dump(r):
    ts = datetime.datetime.fromtimestamp(r['timestamp'], datetime.timezone.utc)
    print(f"patch {r['name']!r}  (format v{r['version']}, saved {ts:%Y-%m-%d %H:%M} UTC)")
    print(f"canvas ({r['canvas_x']},{r['canvas_y']})  zoom={r['zoom']}  counter={r['counter']}")
    if r['comments']:
        print(f"\ncomments ({len(r['comments'])}):")
        for c in r['comments']:
            t = c['text'].replace('\n', '\\n')
            print(f"  [{c['id']}] at ({c['x']},{c['y']}): {t[:70]!r}")
    if r['groups']:
        print(f"\ngroups ({len(r['groups'])}):")
        for g in r['groups']:
            members = [b['inst'] for b in r['blocks'] if b['group'] == g['id']]
            print(f"  group {g['id']} (val={g['val']:#x}) members: {members}")
    byinst = {b['inst']: b for b in r['blocks']}
    print(f"\nblocks ({len(r['blocks'])}):")
    for b in r['blocks']:
        grp = f" group={b['group']}" if b['group'] else ""
        print(f"  [{b['inst']}] {b['name']} (type {b['type_id']}) at ({b['x']},{b['y']}){grp}  values={b['values']!r}")
        for c in b['conns']:
            dest = byinst.get(c['dest'])
            dn = dest['name'] if dest else '??'
            print(f"        out{c['out']} --> [{c['dest']}] {dn}.in{c['in']}")


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] not in ('dump', 'json', 'roundtrip'):
        raise SystemExit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    raw = open(path, 'rb').read()
    r = parse(raw)
    if cmd == 'dump':
        dump(r)
    elif cmd == 'json':
        print(json.dumps(r, indent=2))
    else:
        orig = _extract_container(raw)
        z = zlib.decompressobj()
        orig_payload = z.decompress(orig[6:]); orig_payload += z.flush()
        rt = serialize(r)
        z2 = zlib.decompressobj()
        rt_payload = z2.decompress(rt[6:]); rt_payload += z2.flush()
        if rt_payload == orig_payload:
            print(f"round-trip OK: payload identical ({len(orig_payload)} bytes)")
        else:
            raise SystemExit("round-trip MISMATCH")
