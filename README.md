# 5D Dashboard (a Claude skill)

Your IFC model, your cost-loaded schedule and your BOQ in one offline HTML file.
Click an element to see what it costs, which BOQ lines it carries, and when it gets built.
Drag the date slider to watch the job go up and the money add up.

It is a first pass for planners, QSs and project teams, not a bid number.

## What goes in

- **IFC models**: one or several (structure, architecture, MEP). They are joined into one model.
- **Cost-loaded schedule**: Primavera P6 XER or MS Project XML. The money comes from the schedule.
- **4D links**: `activity_id,guid` (from your 4D tool, or from the [P6 to Revit 4D skill](https://github.com/hamzaabduljabbar/autoConst-p6-revit-4d)).
- **BOQ quantities** (optional but recommended): `line,qty,unit`.

## What Claude does

1. **Checks the dates.** A schedule with too few dated activities stops the build. Claude asks the planner instead of inventing dates.
2. **Matches every BOQ line** to the activity and the element groups that carry it, with a reason on each row, and `NONE` when nothing in the model does.
3. **Builds and reconciles.** If the money on elements plus the money outside the model does not equal the schedule total, the build stops.
4. **Runs the job check.** How well do your three files fit each other?
   - does the model measure what the BOQ bills, line by line?
   - which activities build nothing in the model?
   - which services money has no MEP model behind it?
   - which elements carry no cost?
   - where did the dates come from?
5. **Asks you about the biggest gaps first** (at most five questions), applies your answers and rebuilds.

## What you get

`5d.html`, one file that opens offline in any browser:

- 3D model with a date slider and cost to date
- Breakdown, Estimate, Programme and Procurement views of the same elements
- Checks: everything that does not tie out, listed rather than hidden

The badge on top says where the dates came from: the planner's schedule, the planner's answers, or Claude's draft. Only the planner's schedule makes the monthly curve a forecast.

## Setup

```
py -m pip install -r requirements.txt
```

Copy this folder into `~/.claude/skills/five-d-dashboard/` (or your project's `.claude/skills/`), put your files in a folder, open Claude Code there and say *"build the 5D dashboard for this job"*.

Manual run:

```
py scripts/run.py structure.ifc architecture.ifc --skip IfcReinforcingBar ^
  --schedule loaded.xer --links links.csv --quantities boq_quantities.csv ^
  --out outputs/job --project "Job name" --currency "£"
```

## What was tested

- Money on the right BOQ line and element, blind: 64% with keyword rules, 91% with Claude, on a public sample building whose budget was measured from its model.
- Concrete volumes within 0.2% of the QS on the same building.
- Job check: model within 20% of the BOQ for 94% of matched money on that building; 51% on a real tender priced from a standard design, where the misses became questions.
- Full run by a fresh agent from the skill alone, on a real public tender budget with two discipline models: money reconciled to the cent.
- A Claude-drafted plan for that tender ran 30 points behind the contractor's real curve at month 5. That is why it asks the planner for dates.

## Honest limits

- Not yet tested on one job with all three files from the same project. That is why it checks your files first.
- Finishes and services need the most review. MEP money stays outside the model until MEP models are added.
- Treat the output as a checked draft for review.

## Licence

AutoConst Source Available Licence: see [LICENSE](LICENSE). three.js is MIT, see [scripts/vendor/THIRD_PARTY.md](scripts/vendor/THIRD_PARTY.md).

Built by [Hamza Jabbar](https://hamzajabbar.online) · AutoConst
