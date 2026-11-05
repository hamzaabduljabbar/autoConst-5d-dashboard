#!/usr/bin/env python3
"""How well the model, schedule and BOQ fit each other, before anyone trusts the dashboard.

Usage: py scripts/job_check.py outputs/<p>/priced.json [--quantities lines.csv] [--timing planner|answers|estimated] [--out outputs/<p>/job_check.md]

lines.csv (optional): line, qty, unit. With it, every matched line's BOQ quantity is compared with what the model measures.
Each check says OK or REVIEW, with the money it touches. Nothing here changes the numbers: it tells Claude what to ask the user.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from link_real import group_of

COUNT = {"ea", "each", "no", "nr", "nos", "pcs", "pc", "unit", "units", "item", "un", "und", "u", "pç", "pt"}
MEASURE = {"m3": "m3", "cum": "m3", "m³": "m3", "m2": "m2", "sqm": "m2", "m²": "m2", "m": "len", "lm": "len", "rm": "len", "ml": "len"}
SERVICES = ("Pipe", "Duct", "Flow", "Cable", "LightFixture", "Sanitary", "Waste", "ElectricAppliance", "Outlet", "Switching", "Distribution", "Tank", "Valve", "Fan", "Pump")
FIT = (0.8, 1.25)
MARKED = ("Beam", "Column", "Footing", "Pile", "Slab", "Member", "Plate")  # beam and column marks are normal names


def money(v):
    return f"{v:,.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("priced")
    ap.add_argument("--quantities")
    ap.add_argument("--out")
    ap.add_argument("--timing", default="")
    a = ap.parse_args()
    p = json.load(open(a.priced, encoding="utf-8"))
    E, B = p["elements"], p["boq"]
    code = {l["heading"]: l.get("heading_code", l["heading"]) for l in B}
    total = sum(l["amount"] for l in B) or 1
    on = defaultdict(list)
    for e in E:
        for c in e.get("lines", []):
            on[code.get(c["heading"], c["heading"])].append((e, c["cost"]))
    linked = {t for e in E for t in e.get("tasks", [])}
    checks = []

    def check(ok, title, detail, rows=()):
        checks.append({"ok": ok, "title": title, "detail": detail, "rows": list(rows)})

    # 1 quantities: does the model measure what the BOQ bills?
    if a.quantities:
        Q = {r["line"]: r for r in csv.DictReader(open(a.quantities, encoding="utf-8-sig"))}
        fit, off, nomeasure = 0.0, [], 0.0
        for l in B:
            k = code.get(l["heading"], l["heading"])
            q = Q.get(k)
            els = on.get(k)
            if not q or not els or not float(q["qty"] or 0):
                continue
            u = (q["unit"] or "").strip().lower().rstrip(".")
            m = {e["guid"]: e for e, _ in els}.values()
            if u in COUNT:
                got = len(m)
            elif u in MEASURE:
                got = sum(e.get(MEASURE[u], 0) for e in m)
            else:
                nomeasure += l["model"]
                continue
            r = got / float(q["qty"])
            if FIT[0] <= r <= FIT[1] or (u in MEASURE and .45 <= r <= .55 and re.search(r"(?i)form|f[oô]rma|encofr", l["desc"])):  # formwork: both faces
                fit += l["model"]
            else:
                off.append((l["model"], k, l["desc"].split(" / PT: ")[0][:70], f"BOQ {float(q['qty']):,.2f} {q['unit']} vs model {got:,.2f}", r))
        off.sort(key=lambda x: -x[0])
        tested = fit + sum(x[0] for x in off)
        share = fit / tested if tested else 0
        check(share >= .8, f"Quantities: {share:.0%} of tested money has the model within 20% of the BOQ",
              f"{money(tested)} tested by quantity; {money(sum(x[0] for x in off))} on {len(off)} lines where model and BOQ disagree; "
              f"{money(nomeasure)} in units the model cannot measure (kg, sums). Ask which elements those lines really cover.",
              [f"{k} {d}: {s} (x{r:.2f}), {money(v)} on the model" for v, k, d, s, r in off[:12]])
    else:
        check(False, "Quantities not compared", "No BOQ quantities given (--quantities). Matches are by wording only.")

    # 2 money outside the model, split by why
    by_task = defaultdict(float)
    for s in p["scope"]:
        by_task[s["task"]] += s["cost"]
    unlinked = {t: v for t, v in by_task.items() if t not in linked}
    gap = sum(unlinked.values())
    outside = sum(by_task.values())
    names = p["tasks"]
    check(gap / total < .05, f"Money on activities with no elements linked: {money(gap)} ({gap / total:.0%})",
          f"Of {money(outside)} outside the model, {money(gap)} sits on activities with no elements at all. Some is real (site costs, external works); "
          "the rest means the links are missing. Ask whether those activities build anything in the model.",
          [f"{t} {names.get(t, {}).get('name', '')}: {money(v)}" for t, v in sorted(unlinked.items(), key=lambda x: -x[1])[:10]])

    # 3 disciplines: services money with no services model
    types = {e["type"] for e in E}
    have = sorted(t for t in types if t.startswith(SERVICES))
    words = re.compile(r"(?i)electric|cabl|lighting|lumin|plumb|pipe|drain|sewer|water|hvac|duct|air.?cond|fire|sprinkler|el[eé]tric|hidr|esgoto|tubo|cabo|clima")
    svc = sum(l["amount"] for l in B if words.search(l["desc"]))
    svc_out = sum(l["outside"] for l in B if words.search(l["desc"]))
    check(svc_out / max(svc, 1) < .5, f"Services: {money(svc_out)} of {money(svc)} has no element",
          f"Model element types for services: {', '.join(have) or 'none'}. If MEP models exist, export and add them (merge_models.py) before trusting this money.")

    # 4 group names Claude could not read
    vague = defaultdict(lambda: [0, 0.0])
    for e in E:
        g = group_of(e)
        name = g.split(": ", 1)[1] if ": " in g else ""
        decoded = e.get("type_name") and e.get("type_name") != e.get("name")
        if not e.get("name_en") and not decoded and not e["type"].startswith(MARKED) and (len(name) <= 4 or re.fullmatch(r"[A-Z]{1,3}[-_ ]?\d{1,3}[A-Z]?", name)):
            vague[g][0] += 1
            vague[g][1] += sum(c["cost"] for c in e.get("lines", []))
    vm = sum(v[1] for v in vague.values())
    check(vm / total < .05, f"Coded element names: {money(vm)} sits on {len(vague)} groups named only by a code",
          "Codes like AL14 or L26 come from the design's schedules. Ask the user for the finishes or wall-type schedule before trusting these lines.",
          [f"{g}: {n} elements, {money(v)}" for g, (n, v) in sorted(vague.items(), key=lambda x: -x[1][1])[:10]])

    # 5 elements nobody pays for, and where the dates came from
    free = [e for e in E if not e.get("lines")]
    check(len(free) / max(len(E), 1) < .1, f"{len(free)} of {len(E)} elements carry no cost",
          "Not linked to a costed activity, or no BOQ line was matched to them. Furniture and fittings are often fine; walls, slabs and frames are not.",
          [f"{k}: {n}" for k, n in sorted(((k, sum(1 for e in free if e['type'] == k)) for k in {e['type'] for e in free}), key=lambda x: -x[1])[:8]])
    t = a.timing or p.get("timing") or "not stated"
    check(t == "planner", f"Dates: {t}", "Only a planner's schedule makes the monthly curve a forecast.")

    ok = sum(c["ok"] for c in checks)
    lines = [f"# Job check: {ok} of {len(checks)} OK", "", f"BOQ total {money(total)}. Model elements {len(E)}.", ""]
    for c in checks:
        lines += [f"## {'OK' if c['ok'] else 'REVIEW'}: {c['title']}", "", c["detail"], ""] + [f"- {r}" for r in c["rows"]] + [""]
    out = a.out or os.path.join(os.path.dirname(a.priced), "job_check.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    p["job_check"] = [{k: c[k] for k in ("ok", "title", "detail")} for c in checks]
    json.dump(p, open(a.priced, "w", encoding="utf-8"))
    print("\n".join(f"{'OK    ' if c['ok'] else 'REVIEW'} {c['title']}" for c in checks))
    print(out)


if __name__ == "__main__":
    main()
