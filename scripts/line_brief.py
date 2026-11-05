#!/usr/bin/env python3
"""Brief for matching cost lines to element groups: one row per line + activity, with the groups linked to it.

Usage: py scripts/line_brief.py outputs/<p>/priced.json --schedule cost-loaded.xer out.csv

Whoever reviews it (Claude, then the planner) writes line,activity,groups,reason for link_real.py --line-map.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from link_real import group_of, read_msp, read_xer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("priced")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("out")
    a = ap.parse_args()
    m = json.load(open(a.priced, encoding="utf-8"))
    tasks, costs, _ = read_msp(a.schedule) if a.schedule.lower().endswith(".xml") else read_xer(a.schedule)
    of = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
    for e in m["elements"]:
        for t in e["tasks"]:
            g = of[t][group_of(e)]
            g[0] += 1; g[1] += e.get("m3", 0); g[2] += e.get("m2", 0)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["line", "activity", "activity_name", "description", "unit", "amount", "groups_on_activity"])
        for c in costs:
            gs = " | ".join(f"{k} [{n} no, {v:.1f} m3, {s:.0f} m2]" for k, (n, v, s) in sorted(of[c["task"]].items()))
            w.writerow([c["name"], c["task"], tasks[c["task"]]["name"], c["desc"], c.get("unit", ""), round(c["amount"], 2), gs])
    print(len(costs), "rows ->", a.out)


if __name__ == "__main__":
    main()
