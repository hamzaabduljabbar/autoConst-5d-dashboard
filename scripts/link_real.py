#!/usr/bin/env python3
"""Real inputs -> priced.json: cost-loaded schedule + element links (p6-revit-4d).

Usage: py scripts/link_real.py outputs/<p>/model.json --schedule cost-loaded.xer --links mapping.csv
          [--boq-map job-mapping.csv] [--elements elements.csv] [--glossary glossary.csv] [--project-id ID]

--schedule  P6 XER (expenses + resource budgets) or MS Project XML (task Cost). The schedule holds the money:
            whoever loaded it, the cost loader or a planner, each activity's cost is read as it stands
--links     activity_id,guid from the 4D skill. guid = IFC GlobalId, or a Revit UniqueId with --elements
--elements  Revit dump with guid,element_id: joins UniqueId to the IFC Tag
--boq-map   job-mapping.csv from boq_to_p6.py: adds the BOQ total and the lines that were never loaded
--glossary  nl,en,phase table for schedules in another language
--line-map  line,activity,groups,reason from a review of line_brief.py's brief: which element groups each line
            covers ("A | B"), * for all, NONE for work not in the model. Replaces the wording rules for those lines

Money path: activity cost -> the elements its text names (a door line goes to doors) -> shared by the line's
unit (m3, m2, m, each), by volume when it has none. No element = outside the model.
"""
import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from price import BLOB, base_name, geometry

csv.field_size_limit(10 ** 7)


KIND = {r"Door": r"door|subframe", r"Window": r"window|glaz|velux|skylight|roof dome|subframe", r"Stair.*": r"stair|landing", r"Railing": r"rail|balustrade",
        r"Covering": r"tiling|tiles?|ceiling|plasterboard|coping|sill|flashing|cladding|insulation", r"Footing|Pile": r"footing|foundation|piles?|pad",
        r"Wall.*": r"wall|masonry|masonary|block|brick|partition|plaster|paint|leaf|frame panel", r"Slab": r"slab|floor|screed|deck|balcon|topping|roof",
        r"Roof": r"roof", r"Column": r"column|pier", r"Beam|Member": r"beam|steel|truss|rafter|purlin"}


def named(els, text):
    """The elements this line's words point at, if any. Covering beats the slab or wall under it."""
    text = text.lower()
    hit = [t for t, w in KIND.items() if re.search(w, text)]
    keep = [e for e in els if any(re.fullmatch(t, e["type"]) for t in hit)]
    finish = [e for e in keep if e["type"] == "Covering"]
    return finish or keep or els


def group_of(e):
    """Same kind of element: name without the trailing Revit id."""
    return f"{e['type']}: {re.sub(r'[:_ ]\d{4,}$', '', e['base'])}"


def weights(els, unit):
    """Share by what the line is measured in, falling back when the model has no such measure."""
    u = (unit or "").strip().lower().rstrip(".")
    key = {"m³": "m3", "m²": "m2", "m3": "m3", "cum": "m3", "cu.m": "m3", "t": "m3", "ton": "m3", "tonne": "m3", "kg": "m3", "m2": "m2", "sqm": "m2", "sq.m": "m2",
           "m": "len", "lm": "len", "rm": "len", "ml": "len"}.get(u)
    if u in ("ea", "each", "no", "nr", "nos", "pcs", "pc", "unit", "units", "item", "un", "und", "u", "pç", "pt", "cj", "jg", "vb"):
        return [1.0] * len(els)
    for k in ([key] if key else []) + ["m3", "m2"]:
        w = [e[k] for e in els]
        if sum(w) > 0:
            return w
    return [0.0] * len(els)


def _ok(raw, enc):
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def read_xer(path, project=None):
    raw = open(path, "rb").read()
    text = next(raw.decode(e) for e in ("utf-8", "cp1252", "latin-1") if _ok(raw, e))
    tables, name, cols = defaultdict(list), None, []
    for line in text.split("\n"):  # splitlines also cuts on the control characters XER memos carry
        p = line.rstrip("\r").split("\t")
        if p[0] == "%T":
            name = p[1]
        elif p[0] == "%F":
            cols = p[1:]
        elif p[0] == "%R":
            tables[name].append(dict(zip(cols, p[1:])))
    projects = {r["proj_id"]: r.get("proj_short_name", "") for r in tables["PROJECT"]}
    if len(projects) > 1 and project not in projects and project not in projects.values():
        raise SystemExit(f"XER holds {len(projects)} projects, pick one with --project-id: {projects}")
    keep = next((k for k, v in projects.items() if project in (k, v)), None)
    wbs = {w["wbs_id"]: w for w in tables["PROJWBS"]}
    tasks, by_id = {}, {}
    for t in tables["TASK"]:
        if keep and t["proj_id"] != keep:
            continue
        start = t.get("act_start_date") or t.get("restart_date") or t.get("early_start_date") or t.get("target_start_date")
        end = t.get("act_end_date") or t.get("reend_date") or t.get("early_end_date") or t.get("target_end_date")
        code = t["task_code"].strip()
        by_id[t["task_id"]] = code
        tasks[code] = {"id": code, "name": t["task_name"].strip(), "nl": t["task_name"].strip(),
                       "phase": wbs.get(t["wbs_id"], {}).get("wbs_name", "").strip(),
                       "start": (start or "")[:10] or None, "finish": (end or "")[:10] or None}
    costs = []
    for r in tables["PROJCOST"]:
        if r["task_id"] in by_id:
            costs.append({"task": by_id[r["task_id"]], "name": r.get("cost_name", "").strip(), "desc": r.get("cost_descr", "").strip(),
                          "unit": r.get("qty_name", ""), "amount": float(r.get("target_cost") or 0)})
    rsrc = {r["rsrc_id"]: r.get("rsrc_name", "") for r in tables["RSRC"]}
    for r in tables["TASKRSRC"]:
        if r["task_id"] in by_id and float(r.get("target_cost") or 0):
            costs.append({"task": by_id[r["task_id"]], "name": "Resource " + rsrc.get(r.get("rsrc_id"), ""), "desc": "",
                          "amount": float(r["target_cost"])})
    has_pred = {by_id[r["task_id"]] for r in tables["TASKPRED"] if r["task_id"] in by_id}
    return tasks, costs, [k for k in tasks if k not in has_pred]


def read_msp(path):
    root = ET.parse(path).getroot()
    q = lambda t, f: t.findtext(root.tag.split("}")[0] + "}" + f)
    tasks, costs, open_ends, phase = {}, [], [], {}
    for t in root.iter(root.tag.split("}")[0] + "}Task"):
        code, name = q(t, "ID"), (q(t, "Name") or "").strip()
        out = q(t, "OutlineNumber") or ""
        if q(t, "Summary") == "1":
            phase[out] = name
            continue
        if not name:
            continue
        parent = phase.get(out.rpartition(".")[0], "")
        tasks[code] = {"id": code, "name": name, "nl": name, "phase": parent,
                       "start": (q(t, "Start") or "")[:10] or None, "finish": (q(t, "Finish") or "")[:10] or None}
        cost = float(q(t, "Cost") or 0) / 100  # MSPDI stores money in cents
        if cost:
            costs.append({"task": code, "name": name, "desc": "", "amount": cost})
        if t.find(root.tag.split("}")[0] + "}PredecessorLink") is None:
            open_ends.append(code)
    return tasks, costs, open_ends


def boq_lines(costs, rows):
    """Tie expenses back to BOQ lines: by ref ('BOQ 12 ...'), or by heading when the loader grouped them."""
    lines, of_cost, refs = {}, {}, {r["ref"].strip(): r for r in rows}
    heads = defaultdict(list)
    for r in rows:
        heads[re.sub(r"\s+", " ", r["heading"]).strip().lower()].append(r)
    for c in costs:
        m = re.match(r"BOQ (?:Div \S+ )?(.*)", c["name"])
        ref = c["name"].split()[1] if c["name"].startswith("BOQ ") and len(c["name"].split()) > 1 else None
        if ref in refs:
            key, src = ref, [refs[ref]]
        elif m and m.group(1).strip().lower() in heads:
            src = heads[m.group(1).strip().lower()]
            key = "H:" + m.group(1).strip().lower()
        else:
            key, src = c["name"], []
        if key not in lines:
            lines[key] = {"ref": src[0]["ref"] if len(src) == 1 else "", "heading": src[0]["heading"] if src else c["name"],
                          "desc": src[0]["description"] if len(src) == 1 else c["desc"], "conf": src[0]["confidence"] if len(src) == 1 else "",
                          "amount": sum(float(r["amount"] or 0) for r in src), "model": 0.0, "outside": 0.0, "src": [r["ref"] for r in src]}
        of_cost[id(c)] = lines[key]
    return lines, of_cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--links", required=True)
    ap.add_argument("--boq-map")
    ap.add_argument("--elements")
    ap.add_argument("--glossary")
    ap.add_argument("--project-id")
    ap.add_argument("--line-map")
    a = ap.parse_args()
    m = json.load(open(a.model, encoding="utf-8"))
    geometry(m, os.path.splitext(a.model)[0] + ".bin")
    tasks, costs, open_ends = read_msp(a.schedule) if a.schedule.lower().endswith(".xml") else read_xer(a.schedule, a.project_id)
    if a.glossary:
        gloss = {r["nl"].strip(): r for r in csv.DictReader(open(a.glossary, encoding="utf-8"))}
        for t in tasks.values():
            g = gloss.get(t["name"])
            if g:
                t.update(name=g["en"], phase=g.get("phase") or t["phase"])

    by_key = {}
    for e in m["elements"]:
        e["base"], e["tasks"] = base_name(e["name"]), []
        for k in [e["guid"], e.get("tag")] + e.get("parents", []):
            if k:
                by_key.setdefault(str(k), []).append(e)
    rid = {}
    if a.elements:
        rid = {r["guid"]: r["element_id"] for r in csv.DictReader(open(a.elements, encoding="utf-8-sig"))}
    missed, dead = set(), set()
    for r in csv.DictReader(open(a.links, encoding="utf-8-sig")):
        els = by_key.get(r["guid"]) or by_key.get(rid.get(r["guid"], ""))
        if r["activity_id"] not in tasks:
            dead.add(r["activity_id"])
        elif not els:
            missed.add(r["guid"])
        for e in els or []:
            if r["activity_id"] in tasks and r["activity_id"] not in e["tasks"]:
                e["tasks"].append(r["activity_id"])

    n_links = defaultdict(int)
    for e in m["elements"]:
        for t in e["tasks"]:
            n_links[t] += 1
    blobs = {k for k, n in n_links.items() if n > len(m["elements"]) * BLOB}
    of_task = defaultdict(list)
    for e in m["elements"]:
        own = [t for t in e["tasks"] if t not in blobs]
        e["blob_only"] = not own and bool(e["tasks"])
        e["tasks"] = own or e["tasks"]
        use = [tasks[t] for t in e["tasks"] if tasks[t]["start"]]
        e["a"] = min((t["start"] for t in use), default=None)
        e["b"] = max((t["finish"] for t in use), default=None)
        e["lines"] = []
        for t in e["tasks"]:
            of_task[t].append(e)

    rows = list(csv.DictReader(open(a.boq_map, encoding="utf-8-sig"))) if a.boq_map else []
    lines, of_cost = boq_lines(costs, rows)
    scope = []
    picks = {}
    if a.line_map:
        for r in csv.DictReader(open(a.line_map, encoding="utf-8-sig")):
            picks[(r["line"], r["activity"] or "*")] = [g.strip() for g in r["groups"].split("|")]
        known = {group_of(e).strip() for e in m["elements"]} | {"*", "NONE"}
        bad = sorted({g for v in picks.values() for g in v if g not in known})
        if bad:
            raise SystemExit(f"stopped: line map names {len(bad)} groups the model does not have: {bad[:8]}")
    for c in costs:
        line, t = of_cost[id(c)], c["task"]
        if not line["src"]:  # no BOQ line behind it: resource budgets or anything the planner loaded by hand
            line["amount"] += c["amount"]
        pick = picks.get((c["name"], t), picks.get((c["name"], "*")))
        els = of_task.get(t, [])
        if pick is None:
            els = named(els, f"{line['heading']} {c['name']} {c['desc']}")
        elif pick == ["NONE"]:
            els = []
        elif pick != ["*"]:
            els = [e for e in els if group_of(e).strip() in pick]
        weight = weights(els, c.get("unit")) if els else []
        total = sum(weight)
        if total <= 0:
            line["outside"] += c["amount"]
            scope.append({"item": line["heading"], "package": line["heading"], "cost": c["amount"], "a": tasks[t]["start"], "b": tasks[t]["finish"], "task": t,
                          "note": f"{c['name']}: {tasks[t]['name']} has no element in the model", "basis": tasks[t]["name"]})
            continue
        line["model"] += c["amount"]
        for e, w in zip(els, weight):
            if w > 0:
                e["lines"].append({"ref": line["ref"], "heading": line["heading"], "desc": line["desc"], "task": t, "cost": c["amount"] * w / total})

    loaded = {r for l in lines.values() for r in l["src"]}
    unalloc = [{"ref": r["ref"], "heading": r["heading"], "amount": float(r["amount"] or 0),
                "why": "LOW match, planner to place" if r["confidence"] == "LOW" else "Not in the schedule's costs"}
               for r in rows if r["ref"] not in loaded]
    undated = sorted({c["task"] for c in costs if not tasks[c["task"]]["start"]})
    for e in m["elements"]:
        if e["lines"]:
            top = max(e["lines"], key=lambda x: x["cost"])
            e.update(item=(top["desc"] or top["heading"])[:60], group=top["heading"], package=top["heading"], cost=sum(x["cost"] for x in e["lines"]))
    dated = [t for t in tasks.values() if t["start"] and t["finish"]]
    if not dated:
        raise SystemExit("no dates in the schedule")
    out = {**m, "tasks": tasks, "scope": scope, "leads": {}, "boq": list(lines.values()), "unalloc": unalloc, "mode": "boq", "map": bool(rows),
           "start": min(t["start"] for t in dated), "finish": max(t["finish"] for t in dated),
           "blob_tasks": [tasks[k]["name"] for k in blobs], "open_ends": open_ends, "undated": undated,
           "links_missed": len(missed), "links_dead": sorted(dead)}
    json.dump(out, open(os.path.join(os.path.dirname(a.model), "priced.json"), "w", encoding="utf-8"))
    boq = sum(x["amount"] for x in lines.values()) + sum(u["amount"] for u in unalloc)
    model = sum(e.get("cost", 0) for e in m["elements"])
    outside = sum(s["cost"] for s in scope)
    left = sum(u["amount"] for u in unalloc)
    print({"elements": len(m["elements"]), "linked": sum(1 for e in m["elements"] if e["tasks"]), "costed": sum(1 for e in m["elements"] if "cost" in e),
           "links_not_found": len(missed), "links_to_dead_activities": len(dead), "total": round(boq, 2), "on_elements": round(model, 2),
           "outside_model": round(outside, 2), "in_schedule_not_boq": round(sum(x["amount"] for x in lines.values() if not x["src"]), 2) if rows else 0, "not_loaded": round(left, 2), "difference": round(boq - model - outside - left, 2),
           "no_predecessor": len(open_ends), "undated_cost_tasks": len(undated)})


if __name__ == "__main__":
    main()
