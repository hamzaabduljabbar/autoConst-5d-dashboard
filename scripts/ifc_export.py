#!/usr/bin/env python3
"""IFC with task links -> mesh + element/task data for the 5D viewer.

Usage: py scripts/ifc_export.py model.ifc outputs/<p>/model.json [--skip IfcReinforcingBar]

Writes model.json (elements, tasks) + model.bin (float32 positions, uint32 indices, one element after another).
"""
import json
import multiprocessing
import os
import struct
import sys

import re

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as util

AREA = re.compile(r"(?i)^net ?(side ?)?area$|projected.*net|net.*projected|proje.*l[ií]quid|l[ií]quid.*proje")
VOLUME = re.compile(r"(?i)^net ?volume$|volume.*(net|l[ií]quid)")
LENGTH = re.compile(r"(?i)^length$|^comprimento$")


def quantities(e):
    """Quantities the authoring tool wrote: one face area and the net volume, layer by layer when the element is layered.
    A mesh of a 13-layer wall has 13 skins; the authoring tool's own figures do not."""
    area = vol = length = 0.0
    for q in util.get_psets(e, qtos_only=True).values():
        for k, v in q.items():
            if isinstance(v, dict) and "properties" in v:  # one layer of a layered element
                for a, b in v["properties"].items():
                    if isinstance(b, (int, float)):
                        area = max(area, b) if AREA.search(a) else area
                        vol += b if VOLUME.search(a) else 0
            elif isinstance(v, (int, float)):
                area = max(area, v) if AREA.search(k) else area
                vol = max(vol, v) if VOLUME.search(k) else vol
                length = max(length, v) if LENGTH.search(k) else length
    return {k: round(v, 6) for k, v in (("q_m2", area), ("q_m3", vol), ("q_len", length)) if v > 0}


def task_dates(f):
    out = {}
    if f.schema != "IFC2X3":  # dates come from the XER on real jobs
        return out
    for r in f.by_type("IfcRelAssignsTasks"):
        tc = r.RelatingControl if r.RelatingControl and r.RelatingControl.is_a("IfcScheduleTimeControl") else r.TimeForTask
        if not tc:
            continue
        for t in r.RelatedObjects:
            if t.is_a("IfcTask"):
                s, e = tc.ScheduleStart or tc.ActualStart, tc.ScheduleFinish or tc.ActualFinish
                out[t.id()] = (s, e)
    return out


def d(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v[:10]
    c = getattr(v, "DateComponent", v)  # IFC2x3 IfcDateAndTime -> IfcCalendarDate
    return f"{c.YearComponent:04d}-{c.MonthComponent:02d}-{c.DayComponent:02d}"


def chain(e):
    out = []
    while True:
        r = next(iter(getattr(e, "Decomposes", None) or []), None)
        e = r.RelatingObject if r else None
        if not e or not e.is_a("IfcElement"):
            return out
        out.append(e)


def parents(e):
    """Stairs, railings and roofs are often a parent with the geometry on its parts: links name the parent."""
    return [k for p in chain(e) for k in (p.GlobalId, getattr(p, "Tag", None)) if k]


def main():
    src, out = sys.argv[1:3]
    skip = sys.argv[4:] if sys.argv[3:4] == ["--skip"] else []
    f = ifcopenshell.open(src)
    dates = task_dates(f)
    tasks = {}
    for t in f.by_type("IfcTask"):
        s, e = dates.get(t.id(), (None, None))
        tasks[t.id()] = {"id": t.TaskId or t.Identification or "", "name": t.Name, "start": d(s), "finish": d(e)}
    links = {}
    for r in f.by_type("IfcRelAssignsToProcess"):
        for o in r.RelatedObjects:
            links.setdefault(o.id(), []).append(r.RelatingProcess.id())

    st = ifcopenshell.geom.settings()
    st.set(st.USE_WORLD_COORDS, True)
    it = ifcopenshell.geom.iterator(st, f, min(8, multiprocessing.cpu_count()), exclude=[e for t in skip for e in f.by_type(t)] or None)
    els, nv, nt, origin = [], 0, 0, None
    pos, idx = bytearray(), bytearray()
    if not it.initialize():
        raise SystemExit("no geometry")
    while True:
        g = it.get()
        e = f.by_id(g.id)
        if not e.is_a("IfcOpeningElement") and not e.is_a("IfcSpace"):
            v, fa = g.geometry.verts, g.geometry.faces
            if len(fa):
                ts = [t for k in [e] + chain(e) for t in links.get(k.id(), [])]
                kind = util.get_type(e)
                els.append({"id": g.id, "guid": e.GlobalId, "type": e.is_a()[3:], "name": e.Name or "", "type_name": kind.Name if kind else "", **quantities(e),
                            "tag": getattr(e, "Tag", None), "parents": parents(e), "tasks": ts, "v0": nv, "t0": nt, "tn": len(fa) // 3})
                if origin is None:  # georeferenced models sit far from zero: float32 and volumes need them near it
                    origin = v[:3]
                pos += struct.pack(f"<{len(v)}f", *[x - origin[i % 3] for i, x in enumerate(v)])
                idx += struct.pack(f"<{len(fa)}I", *[i + nv for i in fa])
                nv += len(v) // 3
                nt += len(fa) // 3
        if not it.next():
            break
    used = {t for e in els for t in e["tasks"]}
    for e in els:
        for k in ("v0",):
            e.pop(k)
    base = os.path.splitext(out)[0]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(base + ".bin", "wb") as b:
        b.write(pos)
        b.write(idx)
    json.dump({"nv": nv, "nt": nt, "elements": els, "tasks": {str(k): v for k, v in tasks.items()}, "origin": list(origin)}, open(out, "w"))
    print({"elements": len(els), "linked": sum(1 for e in els if e["tasks"]), "verts": nv, "tris": nt,
           "tasks": len(tasks), "tasks_used": len(used), "dated": sum(1 for t in tasks.values() if t["start"]),
           "bin_mb": round((len(pos) + len(idx)) / 1e6, 1)})


if __name__ == "__main__":
    main()
