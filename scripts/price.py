#!/usr/bin/env python3
"""Quantities from model geometry + rate table -> the one element list everything else groups.

Usage: py scripts/price.py outputs/<p>/model.json scripts/rates_demo.csv scripts/scope_demo.csv [--glossary scripts/glossary_nl.csv]

Writes outputs/<p>/priced.json. Net quantities only: no waste or balancing in the breakdown.
A rule either matches an element or the element stays unpriced and goes to Checks. Nothing is forced.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re

import numpy as np

BLOB = 0.5  # a task linked to more than this share of the model says nothing about one element


def base_name(n):
    return re.sub(r"_?\(#\d+\)$", "", n or "").strip()


def face_area(cr):
    """One face of a wall or slab: skin facing its main direction, halved, so ends and reveals stay out."""
    area = np.linalg.norm(cr, axis=1) / 2
    ok = area > 0
    if not ok.any():
        return 0.0
    n, area = cr[ok] / (2 * area[ok, None]), area[ok]
    axis = np.linalg.eigh((n * area[:, None]).T @ n)[1][:, -1]
    face = np.abs(n @ axis) > .7
    if area[face].sum() < .6 * area.sum():  # curved or chunky: half the skin is the better measure
        return float(area.sum() / 2)
    return float(area[face].sum() / 2)


def geometry(m, binf):
    b = open(binf, "rb").read()
    P = np.frombuffer(b, "<f4", m["nv"] * 3).reshape(-1, 3)
    I = np.frombuffer(b, "<u4", m["nt"] * 3, m["nv"] * 12).reshape(-1, 3)
    for e in m["elements"]:
        t = P[I[e["t0"]: e["t0"] + e["tn"]]]
        c = t.reshape(-1, 3).mean(axis=0) if len(t) else 0  # local origin: an open mesh would otherwise depend on where it sits
        e["m3"] = float(abs(np.einsum("ij,ij->i", t[:, 0] - c, np.cross(t[:, 1] - c, t[:, 2] - c)).sum()) / 6)
        e["len"] = float(np.ptp(t.reshape(-1, 3), axis=0).max())
        e["m2"] = face_area(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]))
        for k in ("m2", "m3", "len"):  # the authoring tool's figure, when the model carries one
            if e.get("q_" + k):
                e["mesh_" + k], e[k] = e[k], e["q_" + k]


def qty(e, unit):
    return {"m3": e["m3"], "m2": e["m2"], "t": e["m3"] * 7.85, "ea": 1.0}[unit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("rates")
    ap.add_argument("scope")
    ap.add_argument("--glossary")
    a = ap.parse_args()
    m = json.load(open(a.model, encoding="utf-8"))
    geometry(m, os.path.splitext(a.model)[0] + ".bin")
    rules = list(csv.DictReader(open(a.rates, encoding="utf-8")))
    gloss = {r["nl"].strip(): r for r in csv.DictReader(open(a.glossary, encoding="utf-8"))} if a.glossary else {}

    tasks = {}
    for k, t in m["tasks"].items():
        g = gloss.get((t["name"] or "").strip())
        if t["name"] and a.glossary and not g:
            raise SystemExit(f"not in glossary: {t['name']}")
        tasks[k] = {**t, "nl": t["name"], "name": g["en"] if g else t["name"], "phase": g["phase"] if g else ""}
    n_links = {}
    for e in m["elements"]:
        for t in e["tasks"]:
            n_links[str(t)] = n_links.get(str(t), 0) + 1
    blobs = {k for k, n in n_links.items() if n > len(m["elements"]) * BLOB}

    for e in m["elements"]:
        e["base"] = base_name(e["name"])
        rule = next((r for r in rules if re.fullmatch(r["type"], e["type"]) and re.search(r["name"], e["base"])), None)
        own = [str(t) for t in e["tasks"] if str(t) not in blobs]
        e["blob_only"] = not own and bool(e["tasks"])
        use = [tasks[k] for k in (own or map(str, e["tasks"])) if tasks[k]["start"]]
        e["a"] = min((t["start"] for t in use), default=None)
        e["b"] = max((t["finish"] for t in use), default=None)
        e["tasks"] = own or [str(t) for t in e["tasks"]]
        if rule:
            q, rate = qty(e, rule["unit"]), float(rule["rate"])
            e.update(item=rule["item"], group=rule["group"], package=rule["package"], unit=rule["unit"], q=round(q, 3),
                     rate=rate, cost=round(q * rate, 2), mix=[int(rule[k]) for k in ("labour", "material", "subcontract")])
    leads = {r["package"]: int(r["lead_weeks"]) for r in rules}

    dates = [t for t in tasks.values() if t["start"] and t["nl"]]
    p0, p1 = min(t["start"] for t in dates), max(t["finish"] for t in dates)
    weeks = ((dt.date.fromisoformat(p1) - dt.date.fromisoformat(p0)).days + 1) / 7
    by_id = {t["id"]: t for t in tasks.values()}
    scope = []
    for r in csv.DictReader(open(a.scope, encoding="utf-8")):
        weekly = r["basis"] == "weekly"
        cost = round(float(r["amount"]) * weeks, 2) if weekly else float(r["amount"])
        s = by_id[r["start_task"]]["start"] if r["start_task"] else p0
        f = by_id[r["finish_task"]]["finish"] if r["finish_task"] else p1
        scope.append({"item": r["item"], "package": r["package"], "cost": cost, "a": s, "b": f, "note": r["note"],
                      "basis": f"{float(r['amount']):,.0f} / week x {weeks:.1f} weeks" if weekly else "Lump sum"})
    out = {**m, "tasks": tasks, "scope": scope, "leads": leads, "start": p0, "finish": p1,
           "blob_tasks": [tasks[k]["name"] for k in blobs]}
    path = os.path.join(os.path.dirname(a.model), "priced.json")
    json.dump(out, open(path, "w", encoding="utf-8"))
    priced = [e for e in m["elements"] if "cost" in e]
    print({"elements": len(m["elements"]), "priced": len(priced), "model_cost": round(sum(e["cost"] for e in priced)),
           "scope_cost": round(sum(s["cost"] for s in scope)), "weeks": round(weeks, 1)})
    un = {}
    for e in m["elements"]:
        if "cost" not in e:
            un[(e["type"], e["base"])] = un.get((e["type"], e["base"]), 0) + 1
    print("unpriced:", sorted(un.items(), key=lambda kv: -kv[1])[:20])


if __name__ == "__main__":
    main()
