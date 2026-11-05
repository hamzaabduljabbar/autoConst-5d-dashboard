#!/usr/bin/env python3
"""One command: model + cost-loaded schedule + links -> checked 5d.html.

Usage: py scripts/run.py model.ifc [more.ifc ..] --schedule cost-loaded.xer --links mapping.csv --out outputs/<p> --project "Name"
          [--boq-map job-mapping.csv] [--elements elements.csv] [--glossary glossary.csv] [--project-id ID] [--line-map line_map.csv] [--credit "..."] [--key answer.xlsx]
          [--timing planner|answers|estimated] [--quantities line,qty,unit.csv] [--skip IfcReinforcingBar ..] [--currency R$]

Several models (structure, architecture, MEP) are exported one by one into <out>/models/ and joined.

Stops if the money does not reconcile: no dashboard from numbers that fail verify.py.
Stops if the schedule is too thin to time the money, unless --timing says where the dates came from.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_ACTIVITIES = 8


def step(*args):
    r = subprocess.run([sys.executable, os.path.join(HERE, args[0]), *args[1:]])
    if r.returncode:
        raise SystemExit(f"stopped at {args[0]}")


def thin(path, project):
    """True when the schedule cannot time the money itself: few costed activities, or costed activities with no dates."""
    sys.path.insert(0, HERE)
    import link_real
    tasks, costs, _ = link_real.read_xer(path, project) if path.lower().endswith(".xer") else link_real.read_msp(path)
    costed = {c["task"] for c in costs if c["amount"]}
    dated = [k for k in costed if k in tasks and tasks[k]["start"] and tasks[k]["finish"]]
    print({"activities": len(tasks), "costed": len(costed), "costed_with_dates": len(dated)})
    return len(dated) < MIN_ACTIVITIES or len(dated) < len(costed) * .9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc", nargs="+")
    ap.add_argument("--skip", nargs="*", default=[], help="IFC classes left out of the 3D, e.g. IfcReinforcingBar")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--links", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--project", default="")
    ap.add_argument("--credit", default="")
    ap.add_argument("--currency", default="", help="symbol shown before money, e.g. R$, AED, £")
    ap.add_argument("--key")
    ap.add_argument("--timing", choices=["planner", "answers", "estimated"])
    for k in ("boq-map", "elements", "glossary", "project-id", "line-map", "quantities"):
        ap.add_argument("--" + k)
    a = ap.parse_args()
    if thin(a.schedule, a.project_id) and a.timing in (None, "planner"):
        raise SystemExit("stopped: this schedule has too few dated, costed activities to time the money. Ask the planner for dates "
                         "(plan_from_answers.py), then rerun with --timing answers. Use --timing estimated only if the user asks.")
    model = os.path.join(a.out, "model.json")
    parts = []
    for ifc in a.ifc:
        part = os.path.join(a.out, "models", os.path.splitext(os.path.basename(ifc))[0], "model.json")
        if not os.path.exists(part) or os.path.getmtime(part) < os.path.getmtime(ifc):
            os.makedirs(os.path.dirname(part), exist_ok=True)
            step("ifc_export.py", ifc, part, *(["--skip", *a.skip] if a.skip else []))
        parts.append(part)
    step("merge_models.py", model, *parts)  # always rebuilt from the parts, so a re-saved IFC can never drop another model
    extra = [x for k, v in (("--boq-map", a.boq_map), ("--elements", a.elements), ("--glossary", a.glossary), ("--project-id", a.project_id), ("--line-map", a.line_map)) if v for x in (k, v)]
    step("link_real.py", model, "--schedule", a.schedule, "--links", a.links, *extra)
    priced = os.path.join(a.out, "priced.json")
    check = ["--project-id", a.project_id] if a.project_id else []
    step("verify.py", priced, "--schedule", a.schedule, *check, *(["--key", a.key] if a.key else []))
    step("job_check.py", priced, "--timing", a.timing or "planner", *(["--quantities", a.quantities] if a.quantities else []))
    step("build_viewer.py", priced, os.path.join(a.out, "5d.html"), "--project", a.project, "--credit", a.credit, "--timing", a.timing or "planner", "--currency", a.currency)


if __name__ == "__main__":
    main()
