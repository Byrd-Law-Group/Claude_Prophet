---
name: clio-matter-analysis
description: "Deep-dive analysis of a single legal matter in Clio Manage, with a strong focus on deadlines and task risk. Pulls the matter's tasks, calendar deadlines, time entries/activities, documents, and billing, then produces a triage-first report: what's overdue, what's due soon, what court dates are coming, how stale the matter is, and recommended next actions. Use this whenever the user wants to review, analyze, assess, or get up to speed on a Clio matter or case, check a matter's deadlines or outstanding tasks, prep for a client or status meeting on a matter, or asks 'what's the status of matter X' / 'what needs attention on the Smith case' / 'is anything overdue on this matter' — even if they don't say the word 'analyze'. For raw Clio API calls or non-analysis CRUD (creating matters, editing contacts), use the clio skill directly instead."
---

# Clio Matter Analysis

Produce a deep-dive, deadline-first analysis of one Clio matter. The goal is that a
lawyer glancing at the top of the report immediately knows *what needs attention now*
(overdue tasks, imminent deadlines, court dates), then can read down for the fuller
picture (activity, billing, documents, recommended actions).

This skill builds on the **clio** skill for authentication and the API. If `MATON_API_KEY`
isn't configured or there's no active Clio connection, read the clio skill for setup and
help the user connect before proceeding.

## Workflow

### 1. Identify the matter

The user usually names the matter loosely — a client name, a case description, or a
display number ("the Smith matter", "00123-Acme", "our patent case for Delta Corp").
Run the helper with whatever they gave you:

```bash
python "/Users/deandreabyrd/.claude/skills/clio-matter-analysis/scripts/analyze_matter.py" "<what the user said>"
```

The script resolves the matter itself. Three outcomes:

- **`"status": "ok"`** — it found a single matter and analyzed it. Go to step 3.
- **`"status": "ambiguous"`** — several matters matched. Show the `candidates` list
  (display number, description, client, status) and ask the user which one, then rerun
  with the chosen matter's numeric `id`.
- **`"status": "not_found"`** — nothing matched. Ask the user to confirm the name or
  give the display number; try again.

Pass `--soon-days N` to change what counts as "due soon" (default 14). If the user is
prepping for a specific meeting date or asks about a narrower window, adjust it.

### 2. Handle partial data honestly

Activities, documents, and bills require OAuth scopes beyond the basic Clio integration,
so those sections can come back empty with an entry in `warnings`. Don't present missing
data as "nothing there" — if a section is warned, say the data wasn't accessible (likely
a permissions/scope issue) rather than implying the matter has no time entries or bills.
Tasks and calendar entries are part of the core integration and should normally load.

### 3. Write the report

The script returns everything computed. Turn the JSON into the report below. Lead with
risk — that's the whole point. Keep tables tight; don't dump raw IDs unless they help.

```markdown
# Matter Analysis — {display_number}: {description}
*Client: {client} · Responsible attorney: {attorney} · Status: {status} · Generated {date}*

## ⚠️ Needs attention now
- **Overdue tasks:** {n} — {one-line worst offender, e.g. "Respond to discovery, 12 days overdue"}
- **Due in the next {soon_days} days:** {n}
- **Upcoming calendar deadlines / court dates:** {n} — {nearest one}
- **Staleness:** last activity {days_since_last_activity} days ago  *(flag if > ~30)*

| Item | Type | Due | Days | Priority / Owner |
|------|------|-----|------|------------------|
| ... prioritized: overdue first, then due-soon, then nearest events ... |

## Matter overview
Client, practice area, responsible attorney, open date (and close date if closed),
client reference. A sentence on what the matter is.

## Deadlines & tasks (full)
All open tasks and upcoming calendar entries, grouped overdue / due-soon / later.
Note anything with no due date — undated open tasks are a quiet risk.

## Activity & staleness
Most recent time entries/activities and the last-activity date. Call out a gap if the
matter has gone quiet.

## Billing snapshot
Estimated unbilled hours, outstanding bill balance, and bill states — only if the
billing section loaded (see step 2).

## Recommended next actions
3–6 concrete, prioritized actions grounded in the data above (e.g. "Reassign the two
unowned overdue tasks", "Confirm the {date} hearing is on the responsible attorney's
calendar", "Matter has had no activity in 47 days — consider a status check or closing").
```

Adapt to the ask. If the user only wants the deadline/task-risk picture, lead with the
"Needs attention now" section and the full deadlines table and keep the rest brief. If
they want the full deep dive, give every section its due.

### 4. Offer a dashboard (optional)

After the markdown report, offer to render an HTML dashboard artifact (status tiles for
overdue / due-soon / court dates, a color-coded deadline table) if the user would find a
visual or shareable version useful. Only build it if they say yes — the markdown report
is the default deliverable.

## Notes

- **Dates:** the script does the overdue/due-soon math in UTC and reports `days_until`
  (negative = overdue). Trust those numbers rather than re-parsing timestamps yourself.
- **Multiple Clio connections:** if the user has more than one, pass `--connection <id>`
  or set `CLIO_CONNECTION_ID`. See the clio skill's connection management section.
- **Read-only:** this skill only reads. If the analysis surfaces something to change
  (reassign a task, mark one complete, add a deadline), propose it and, on the user's
  go-ahead, use the **clio** skill's write endpoints — don't do it silently.
- **Scope:** one matter per run. For a firm-wide sweep across many matters, that's a
  different (portfolio) analysis — say so rather than looping this over every matter.
