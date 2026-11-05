---
name: five-d-dashboard
description: Turn an IFC model, a cost-loaded schedule (P6 XER or MS Project XML) and 4D links into one checked offline 5D HTML dashboard showing money on every element and month. Use when someone wants 5D, cost on a BIM model, a cash-flow view linked to a model, or BC3/BOQ money placed on elements.
---

# 5D dashboard

Inputs: an IFC model; a cost-loaded schedule (`.xer` or MS Project `.xml`); a links CSV of activity to elements. BOQ lines come from the schedule's costs. A BC3 budget can be read with `scripts/bc3_read.py budget.bc3 outputs/<job>/`.

## Steps

1. Check the three files belong to one job. Compare element counts and quantities with the budget before going further. Tell the user if they do not.
2. Check timing before anything else. Dates come from the planner, never from Claude.
   - **Real activity schedule:** use it. Ask only about gaps, such as activities with no dates.
   - **Monthly or no schedule:** `run.py` stops. Do not invent a plan. Run `py scripts/plan_from_answers.py lines.csv answers.csv --questions`, then ask the planner at most six short questions: is this the current approved programme and what are its start and finish; what comes first and what overlaps; dates for each package, biggest value first; how site overheads spread; whether big items are paid when ordered or installed; whether a target curve or payment schedule exists. Put the dates in `answers.csv`, run the script again with `--xer`, show the planner the draft monthly curve, apply corrections, then run `run.py` with `--timing answers`.
   - **Estimated dates:** only when the user explicitly asks. Use `--timing estimated`. The dashboard then says it is not for cash-flow forecasting.
3. First run, no line map. Pass every discipline model in one go (structure, architecture, MEP); they are exported into `<out>/models/` and joined. Leave rebar geometry out with `--skip IfcReinforcingBar` when the BOQ prices rebar by weight, and set `--currency` (R$, AED, £):
   `py scripts/run.py structure.ifc architecture.ifc --skip IfcReinforcingBar --schedule loaded.xer --links links.csv --out outputs/<job> --project "Name"`
   Add `--boq-map`, `--elements`, `--glossary`, `--project-id` where the job needs them.
4. Claude matching. Keyword rules are only a fallback and were poor on real wording.
   Run `py scripts/line_brief.py` (see its header), read every line, and write `line_map.csv` with columns `line,activity,groups,reason`. Use `*` for all, `NONE` for no model element. Group names must match exactly: the build stops on a group the model does not have. Structural marks (beams, columns, piles) are one group each, so use `*` on structural activities rather than listing marks. Give a reason on every row. Never guess a line: mark it NONE and list it for the user.
5. Rerun step 3 with `--line-map line_map.csv`. Add `--quantities lines.csv` (line, qty, unit) whenever the BOQ has quantities: the job check then compares every matched line with what the model measures.
   **Job check.** Every build writes `job_check.md`: quantity fit, money on activities with no elements, services with no model, coded names, unpriced elements, date source. Before showing the dashboard:
   - Read it. Fix what the files already answer: a line whose model quantity is 10x the BOQ is matched too broadly, so narrow its groups; two-sided formwork at x0.5 is expected.
   - Ask the user at most five questions, biggest money first: which elements a line covers, what a code means (ask for the finishes or wall-type schedule), whether an activity with no elements builds anything, whether MEP models exist (add them with `scripts/merge_models.py`).
   - Apply the answers, rebuild, and report the before and after of each check. Never hide a REVIEW.
   - Append a short note to `outputs/<job>/run_notes.md`: what did not fit and how it was settled. If the same issue appears on two jobs, tell the user it belongs in the skill.
6. Open `outputs/<job>/5d.html` and report its Checks tab: money outside the model, undated activities, dead links.

## Rules

- `run.py` stops if money does not reconcile with the schedule. Never bypass this; fix the cause.
- A blind AI-written plan ran 30 points behind a contractor's real curve at month 5. Never present estimated dates as a forecast.
- Say that costs on elements are estimated shares unless the budget's measurements name the elements.
- Large models: exports can take 30+ minutes. Models heavy in rebar take longer.
- Keep client files private. Dashboards built from licensed sample files stay private unless the licence allows sharing.

## What is proven

Job check: model within 20% of the BOQ quantity for 94% of matched money on a building whose budget was measured from its model. On a real tender priced from a standard design it was 51% after the end-to-end run: most misses were lines matched to a whole wall or floor group when the work covers only part of it, which is what the questions are for. Quantities come from the model's own figures (base or layer quantities) when it has them; the mesh is the fallback.


Blind tests put 91-96% of money on the right line and element on one building and 99.3% on a viaduct (an easy case). Concrete volumes came within 0.2% of the QS. It has NOT been tested on one real job with a model, a real budget and a real activity-level schedule together. State this limit whenever accuracy is claimed. Results are a checked draft for human review, not a bid figure.
