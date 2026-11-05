#!/usr/bin/env python3
"""Join discipline models exported by ifc_export.py into one model.json + model.bin, in the same coordinates.

Usage: py scripts/merge_models.py outputs/<p>/model.json arch/model.json struct/model.json ..
"""
import json
import os
import struct
import sys


def main():
    out, *src = sys.argv[1:]
    base = None
    els, pos, idx, nv, nt, seen = [], bytearray(), bytearray(), 0, 0, set()
    for path in src:
        m = json.load(open(path, encoding="utf-8"))
        raw = open(os.path.splitext(path)[0] + ".bin", "rb").read()
        base = base or m["origin"]
        p = struct.unpack(f"<{m['nv'] * 3}f", raw[:m["nv"] * 12])
        i = struct.unpack(f"<{m['nt'] * 3}I", raw[m["nv"] * 12:])
        shift = [m["origin"][k] - base[k] for k in range(3)]
        pos += struct.pack(f"<{len(p)}f", *[x + shift[n % 3] for n, x in enumerate(p)])
        idx += struct.pack(f"<{len(i)}I", *[x + nv for x in i])
        for e in m["elements"]:
            if e["guid"] in seen:
                raise SystemExit(f"same element in two models: {e['guid']}")
            seen.add(e["guid"])
            els.append({**e, "t0": e["t0"] + nt, "model": os.path.basename(os.path.dirname(path))})
        nv += m["nv"]
        nt += m["nt"]
    with open(os.path.splitext(out)[0] + ".bin", "wb") as b:
        b.write(pos)
        b.write(idx)
    json.dump({"nv": nv, "nt": nt, "elements": els, "tasks": {}, "origin": base}, open(out, "w"))
    print({"models": len(src), "elements": len(els), "verts": nv, "tris": nt})


if __name__ == "__main__":
    main()
