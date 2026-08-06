---
name: clio-deadline-radar
description: "Firm-wide deadline and statute-of-limitations radar across ALL matters in Clio Manage. Use this whenever the user wants a book-wide sweep of critical legal deadlines rather than one matter — 'what deadlines are coming up across the firm', 'any statutes of limitation about to run', 'show me everything overdue', 'what SOLs or ante litem notices are approaching', 'which cases are missing a statute of limitations date', 'run the deadline radar', or 'what needs attention this month firm-wide'. It pulls every open matter's SOL, Georgia ante litem, court/hearing/trial/mediation, and demand-response deadlines from calendar entries and tasks, buckets them by urgency (overdue / 30 / 60 / 90 / 180 days), and flags open matters with NO statute of limitations calendared — the highest malpractice risk in a plaintiff's practice. Read-only. For a deep dive on ONE matter use clio-matter-analysis; to set up deadlines on a new matter use clio-mva-intake."
---

# Clio Deadline Radar (firm-wide)

A single triage view of the hard legal deadlines across your entire open book —
built for a plaintiff's PI practice where a missed statute of limitations or
Georgia ante litem notice is a malpractice event.

This is the firm-wide complement to `clio-matter-analysis` (which drills into one
matter). It is **read-only**.

## Run it

```bash
python scripts/deadline_radar.py
# wider/narrower reporting window, or include pending matters:
python scripts/deadline_radar.py --horizon-days 180 --include-pending
```

Env: `MATON_API_KEY` (and `MATON_CONNECTION` if multiple Clio connections).

The script returns JSON with `counts`, a flat sorted `deadlines` list, `buckets`
(overdue / d30 / d60 / d90 / d180 / beyond / undated), and `matters_missing_sol`.

## What counts as a deadline

It classifies calendar entries and open tasks by keyword against your firm's own
labels (from the MVA intake workflow):

- **statute_of_limitations** — "Statute of Limitations…", "limitation period", "SOL"
- **ante_litem** — Georgia ante litem notices (municipal 6mo, county/state 12mo)
- **court** — hearing, trial, mediation, deposition, arbitration, court dates
- **filing** — file suit, complaint/answer, discovery/response due
- **demand_response** — demand response deadlines, time-limited demands

## How to present the report

Lead with risk, in this order — stop the reader on what can hurt them:

1. **🚨 Missing SOL** — list every matter in `matters_missing_sol` first. These are
   open matters with no statute of limitations found on the calendar or tasks
   within the scan window. Frame it as "verify/calendar the SOL immediately," not
   as a certainty the SOL is truly unset (it could be beyond the scan window or
   labeled unusually — say so).
2. **⏰ Overdue** — anything in the `overdue` bucket, with matter, client, attorney,
   the deadline label, and how many days past due.
3. **Next 30 / 60 / 90 days** — grouped, soonest first. Call SOL and ante litem
   items out distinctly from routine court dates.
4. **Later (90–180 days)** — brief.

For each deadline show: matter (display number + client), the deadline type and
label, the date, days until, and the responsible attorney. Group by matter when a
matter has several. Note the `horizon_days` / `sol_scan_days` used so the reader
knows the window.

## Honesty guardrails

- **"Missing SOL" means "not found," not "definitely unset."** The date may sit
  beyond the scan window or under a non-standard label. Always phrase it as
  "confirm the SOL is calendared," and offer to widen `--sol-scan-days`.
- If `warnings` is non-empty (e.g. a scope error fetching tasks or calendar),
  surface it — an incomplete fetch could hide a real deadline.
- This reads existing Clio data; it does not create or move deadlines. To calendar
  a missing SOL, hand off to `clio-mva-intake`.
