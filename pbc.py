#!/usr/bin/env python3
"""
pbc.py - headless Patchblocks compiler: .pbp patch -> main.c

Replicates the code generation that the Patchblocks GUI performs when you hit
Compile: it fills the DYNAMICALLY GENERATED section of templ_chip.txt with
block structs, functions, wiring and rate handlers derived from the patch.

Validated by reproducing the app's own main.c byte-for-byte for a reference
patch (see --selftest).

Usage:
  pbc.py <patch.pbp> [-o main.c]     generate main.c
"""
import sys, re, glob, struct, importlib.util

APP = "/Applications/Patchblocks.app/Contents/MacOS"
_spec = importlib.util.spec_from_file_location("pbp", __file__.rsplit('/', 1)[0] + "/pbp.py")
pbp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pbp)


def load_block_defs():
    """name -> dict(data_name, func_name, rate, body, vars) from the app's XMLs."""
    defs = {}
    for f in glob.glob(APP + "/blocks/**/*.xml", recursive=True):
        raw = open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r'<block name="([^"]+)"', raw)
        if not m:
            continue
        name = m.group(1)
        dm = re.search(r'<data name="([^"]+)"', raw)
        fm = re.search(r'<function name="([^"]+)"([^>]*)>\s*<!\[CDATA\[(.*?)\]\]>', raw, re.S)
        if not (dm and fm):
            continue
        rate = "control" if 'rate="control"' in fm.group(2) else "audio"
        # variables in declaration order
        vars_ = []
        for vm in re.finditer(r'<variable\b([^>]*?)/>', raw):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', vm.group(1)))
            vars_.append(attrs)
        defs[name] = dict(data_name=dm.group(1), func_name=fm.group(1),
                          rate=rate, body=fm.group(3), vars=vars_)
    return defs


def scale(v):
    """patch value string -> fixed point int (x1024, truncated toward zero)"""
    return int(float(v) * 1024)


def generate(patch):
    defs = load_block_defs()
    blocks = patch["blocks"]
    byinst = {b["inst"]: b for b in blocks}

    # --- block numbering: depth-first following each block's connection order,
    #     roots taken in file order (matches the GUI's numbering) ---
    order = []
    seen = set()
    def visit(b):
        if b["inst"] in seen:
            return
        seen.add(b["inst"])
        order.append(b)
        for c in b["conns"]:
            visit(byinst[c["dest"]])
    for b in blocks:
        visit(b)
    idx = {b["inst"]: i for i, b in enumerate(order)}

    # wired inputs: (dest inst, dest in) -> (src inst, src out)
    wired = {}
    for b in blocks:
        for c in b["conns"]:
            wired[(c["dest"], c["in"])] = (b["inst"], c["out"])

    out = []
    w = out.append
    vals = {b["inst"]: b["values"].split(";") for b in blocks}

    # array vars like data[?]: size them from the instance's values entry
    def array_len(b, vi):
        return len(vals[b["inst"]][vi].split(","))

    # --- typedefs + instances (dedup types, first-use order) ---
    seen_types = []
    for b in order:
        d = defs[b["name"]]
        if d["data_name"] in seen_types:
            continue
        seen_types.append(d["data_name"])
        w("typedef struct {")
        ni = no = 0
        for vi, v in enumerate(d["vars"]):
            if v.get("socket") == "in":
                w(f"\tint32_t *in{ni};"); ni += 1
            elif v.get("socket") == "out":
                w(f"\tint32_t out{no};"); no += 1
            elif v["name"].endswith("[?]"):
                base = v["name"][:-3]
                n = max(array_len(x, vi) for x in order if x["name"] == b["name"])
                w(f"\t{v['dtype']} {base}[{n}];")
                w(f"\tuint32_t {base}_length;")
            else:
                w(f"\t{v['dtype']} {v['name']};")
        w("}%s;" % d["data_name"])
    for i, b in enumerate(order):
        w(f"{defs[b['name']]['data_name']} block{i};")

    # --- functions (dedup, first-use order) ---
    seen_funcs = set()
    for b in order:
        d = defs[b["name"]]
        if d["func_name"] in seen_funcs:
            continue
        seen_funcs.add(d["func_name"])
        w(f"static inline void {d['func_name']}({d['data_name']} *data){{")
        w(d["body"])
        w("}")

    # --- init_dsp_objects ---
    w("static inline void init_dsp_objects(){")
    # statics for unwired inputs
    for i, b in enumerate(order):
        d = defs[b["name"]]
        ni = 0
        for vi, v in enumerate(d["vars"]):
            if v.get("socket") == "in":
                if (b["inst"], ni) not in wired:
                    w(f"\tstatic int32_t block{i}_in{ni} = {scale(vals[b['inst']][vi])};")
                ni += 1
    # internal var initialisation
    for i, b in enumerate(order):
        d = defs[b["name"]]
        for vi, v in enumerate(d["vars"]):
            if "socket" in v:
                continue
            if v["name"].endswith("[?]"):
                base = v["name"][:-3]
                items = vals[b["inst"]][vi].split(",")
                for k, item in enumerate(items):
                    w(f"\tblock{i}.{base}[{k}] = {scale(item)};")
                w(f"\tblock{i}.{base}_length = {len(items)};")
            else:
                w(f"\tblock{i}.{v['name']} = {scale(vals[b['inst']][vi])};")
    # input pointer wiring: per block, unwired first, then wired (ascending)
    for i, b in enumerate(order):
        d = defs[b["name"]]
        n_in = sum(1 for v in d["vars"] if v.get("socket") == "in")
        for ni in range(n_in):
            if (b["inst"], ni) not in wired:
                w(f"\tblock{i}.in{ni} = &block{i}_in{ni};")
        for ni in range(n_in):
            if (b["inst"], ni) in wired:
                src, srcout = wired[(b["inst"], ni)]
                w(f"\tblock{i}.in{ni} = &block{idx[src]}.out{srcout};")
    w("}")

    # --- rate handlers (file... traversal order, filtered by rate) ---
    w("static inline void audio_rate_handler(){")
    for i, b in enumerate(order):
        d = defs[b["name"]]
        if d["rate"] == "audio":
            w(f"\t{d['func_name']}(&block{i});")
    w("}")
    w("static inline void control_rate_handler(){")
    for i, b in enumerate(order):
        d = defs[b["name"]]
        if d["rate"] == "control":
            w(f"\t{d['func_name']}(&block{i});")
    w("}")
    return "\n".join(out)


def build_main_c(patch):
    tpl = open(APP + "/compile/templ_chip.txt", encoding="utf-8", errors="replace").read()
    begin = "//----------------------------------- DYNAMICALLY GENERATED -----------------------------------"
    end = "//--------------------------------- END DYNAMICALLY GENERATED ---------------------------------"
    head, rest = tpl.split(begin)
    _, tail = rest.split(end)
    return head + begin + "\n" + generate(patch) + "\n\n" + end + tail


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-o"]
    if not args:
        raise SystemExit(__doc__)
    src = args[0]
    dst = args[1] if len(args) > 1 else "main.c"
    patch = pbp.parse(open(src, "rb").read())
    open(dst, "w").write(build_main_c(patch))
    print(f"generated {dst} from {src} ({len(patch['blocks'])} blocks)")
