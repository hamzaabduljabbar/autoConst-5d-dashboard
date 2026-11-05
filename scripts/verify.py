#!/usr/bin/env python3
"""Check priced.json against the schedule it came from, without using the viewer's sums.

Usage: py scripts/verify.py outputs/<p>/priced.json --schedule cost-loaded.xer [--key answer.xlsx --key-sheet "Cost To P6"]

1 every activity's cost in the dashboard = its cost in the schedule (optionally = a planner's answer key)
2 element costs + outside-model costs = total, no element negative
3 cost curve built from the schedule alone ends on the same total, month by month
"""
import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from link_real import read_msp, read_xer


def spread(cost, a, b, months):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    n = (b - a).days + 1
    for i in range(n):
        months[(a + dt.timedelta(i)).isoformat()[:7]] += cost / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("priced")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--key")
    ap.add_argument("--key-sheet", default="Cost To P6")
    ap.add_argument("--project-id")
    a = ap.parse_args()
    m = json.load(open(a.priced, encoding="utf-8"))
    tasks, costs, _ = read_msp(a.schedule) if a.schedule.lower().endswith(".xml") else read_xer(a.schedule, a.project_id)
    src = defaultdict(float)
    for c in costs:
        src[c["task"]] += c["amount"]
    mine = defaultdict(float)
    for e in m["elements"]:
        for l in e.get("lines", []):
            mine[l["task"]] += l["cost"]
    for s in m["scope"]:
        mine[s["task"]] += s["cost"]
    bad = [(k, round(src[k], 2), round(mine[k], 2)) for k in set(src) | set(mine) if abs(src[k] - mine[k]) > .01]
    fails = 0
    print(f"1 activities: {len(src)} costed, {len(bad)} differ from schedule", bad[:5])
    fails += bool(bad)
    if a.key:
        from openpyxl import load_workbook
        truth = {}
        for r in load_workbook(a.key, data_only=True, read_only=True)[a.key_sheet].iter_rows(values_only=True):
            if r and isinstance(r[0], str) and isinstance(r[2], (int, float)) and not r[0].lower().startswith("grand"):
                truth[r[0]] = float(r[2])
        wrong = [k for k in truth if abs(truth[k] - mine[k]) > .02]
        print(f"1b planner's answer key: {len(truth) - len(wrong)}/{len(truth)} activities match", wrong[:5])
        fails += bool(wrong)
    total = sum(src.values())
    els = sum(e.get("cost", 0) for e in m["elements"])
    out = sum(s["cost"] for s in m["scope"])
    neg = sum(1 for e in m["elements"] if e.get("cost", 0) < 0)
    print(f"2 total {total:,.2f} = elements {els:,.2f} + outside {out:,.2f} (diff {total - els - out:.2f}), negative {neg}")
    fails += abs(total - els - out) > .01 or neg > 0
    p0, p1 = min(t["start"] for t in tasks.values() if t["start"]), max(t["finish"] for t in tasks.values() if t["finish"])
    want, got = defaultdict(float), defaultdict(float)
    for c in costs:
        t = tasks[c["task"]]
        spread(c["amount"], t["start"] or p0, t["finish"] or p1, want)
    for e in m["elements"]:
        for l in e.get("lines", []):
            t = tasks[l["task"]]
            spread(l["cost"], t["start"] or p0, t["finish"] or p1, got)
    for s in m["scope"]:
        t = tasks[s["task"]]
        spread(s["cost"], t["start"] or p0, t["finish"] or p1, got)
    off = {k: round(want[k] - got[k], 2) for k in want if abs(want[k] - got[k]) > .01}
    print(f"3 cost curve: {len(want)} months, {len(off)} differ from schedule", off)
    fails += bool(off)
    print("PASS" if not fails else f"FAIL ({fails})")
    sys.exit(bool(fails))


if __name__ == "__main__":
    main()
