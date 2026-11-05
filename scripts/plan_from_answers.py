#!/usr/bin/env python3
"""Planner's answers -> cost-loaded schedule, for jobs with no activity schedule. The dates are the planner's, never guessed.

Questions: py scripts/plan_from_answers.py lines.csv answers.csv --questions
    writes one row per package, biggest value first, with start and finish blank for the planner.
Schedule:  py scripts/plan_from_answers.py lines.csv answers.csv --xer outputs/<p>/plan.xer
    stops if a package has no dates.

lines.csv columns: line, package, desc, unit, amount. answers.csv columns: package, value, start, finish, predecessors (YYYY-MM-DD; package names split by ;).
"""
import argparse
import csv
from collections import defaultdict


def rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lines")
    ap.add_argument("answers")
    ap.add_argument("--questions", action="store_true")
    ap.add_argument("--xer")
    a = ap.parse_args()
    L = rows(a.lines)
    value = defaultdict(float)
    for l in L:
        value[l["package"]] += float(l["amount"])
    if a.questions:
        with open(a.answers, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["package", "value", "start", "finish", "predecessors"])
            for k, v in sorted(value.items(), key=lambda x: -x[1]):
                w.writerow([k, f"{v:.2f}", "", "", ""])
        print(len(value), "packages to date:", a.answers)
        return
    if not a.xer:
        raise SystemExit("give --questions or --xer")
    A = {r["package"]: r for r in rows(a.answers)}
    gaps = [k for k in value if k not in A or not A[k]["start"] or not A[k]["finish"]]
    if gaps:
        raise SystemExit(f"stopped: {len(gaps)} packages have no planner dates: {gaps[:8]}")
    ids = {k: str(100 + i) for i, k in enumerate(value)}
    X = ["ERMHDR\t8.0", "%T\tPROJECT", "%F\tproj_id\tproj_short_name", "%R\t1\tPLANNER", "%T\tPROJWBS", "%F\twbs_id\twbs_name", "%R\t1\tPlanner answers",
         "%T\tTASK", "%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttarget_start_date\ttarget_end_date"]
    X += ["\t".join(["%R", i, "1", "1", f"P{i}", k, A[k]["start"] + " 08:00", A[k]["finish"] + " 17:00"]) for k, i in ids.items()]
    X += ["%T\tTASKPRED", "%F\ttask_id\tpred_task_id"]
    for k, i in ids.items():
        X += [f"%R\t{i}\t{ids[p.strip()]}" for p in (A[k].get("predecessors") or "").split(";") if p.strip()]
    X += ["%T\tPROJCOST", "%F\ttask_id\tcost_name\tcost_descr\tqty_name\ttarget_cost"]
    X += ["\t".join(["%R", ids[l["package"]], l["line"], l.get("desc", ""), l.get("unit", ""), l["amount"]]) for l in L]
    open(a.xer, "w", encoding="utf-8").write("\n".join(X) + "\n%E\n")
    print(len(ids), "activities", len(L), "cost rows", a.xer)


if __name__ == "__main__":
    main()
