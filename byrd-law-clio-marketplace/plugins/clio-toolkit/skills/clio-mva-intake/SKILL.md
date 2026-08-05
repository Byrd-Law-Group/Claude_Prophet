---
name: clio-mva-intake
description: "Set up the standard pre-litigation workflow on a new motor vehicle accident (MVA) matter in Clio Manage — creates the firm's intake-to-demand task checklist with due dates and calendars the critical Georgia deadlines (statute of limitations, ante litem notice) with stacked reminders. Use this whenever a new personal-injury / car-accident / MVA matter is opened and needs its tasks and deadlines set up, when the user says things like 'set up the new Jones car accident case', 'run intake on this matter', 'calendar the deadlines for the new MVA', 'apply our SOP to this new matter', or 'create the pre-litigation tasks for the new client' — even if they don't name the workflow. This skill WRITES to Clio (creates tasks and calendar entries), so it always previews the full plan for approval before creating anything. For read-only analysis of an existing matter use clio-matter-analysis; for raw Clio API calls use the clio skill."
---

# Clio MVA Intake Workflow

Stand up the firm's pre-litigation workflow on a new motor vehicle accident matter: the
Phase 1–7 task checklist (with due dates) and calendar entries for the critical Georgia
deadlines, with reminders stacked at 180/90/60/30 days out.

Built on the **clio** skill for auth/API. The task and deadline definitions live in
`references/mva_template.json` (edit that to tune the firm's process); the reasoning and the
deadline table are in `references/mva-sop.md` — read it if the user asks *why* a date or task
looks the way it does.

## This skill writes to Clio — preview first, always

Creating tasks and calendar entries changes real practice-management data, and the deadlines
here govern whether claims survive. So the flow is strictly **compute → show the user → get an
explicit yes → create**. The script enforces this: it dry-runs by default and only writes with
`--commit`. Never pass `--commit` until the user has seen the plan and approved it.

Just as important: the computed deadline dates are **calendaring aids, not legal advice**.
Georgia law changes and tolling/edge cases move real dates. When you present the plan, say
plainly that the supervising attorney must verify every deadline against current law before
relying on it — don't present the dates as settled.

## Workflow

### 1. Gather the inputs the deadlines depend on

The Georgia deadlines are computed from the **date of injury** (and date of loss for property
damage), not the matter open date — so you need those. Before running, make sure you have:

- **The matter** — name, client, or display number of the new matter (it should already exist in
  Clio; this skill doesn't open it).
- **Date of injury** (required) — drives the PI statute of limitations and ante litem clocks.
- **Date of property loss** — defaults to the injury date if not given.
- **Who the at-fault party is** — private, or a **government** entity (municipality / county /
  state)? Government identity triggers a much shorter ante litem deadline, so ask if it's not
  clear.
- **Commercial truck involved?** — adds the spoliation letter and § 9-11-67.1 demand tasks.
- **Minor's claim?** — the limitations period is tolled; the script won't guess a date and will
  flag it for the attorney.

If any of these is unknown, ask rather than assume — a wrong injury date means a wrong SOL.

### 2. Build the preview (dry run)

```bash
python "/Users/deandreabyrd/.claude/skills/clio-mva-intake/scripts/build_workflow.py" \
  "<matter name or id>" --injury-date YYYY-MM-DD \
  [--loss-date YYYY-MM-DD] [--open-date YYYY-MM-DD] \
  [--defendant municipal|county|state|private] [--commercial-truck] [--minor]
```

Outcomes:
- **`"status": "ambiguous"`** — several matters matched; show the candidates and ask which, then
  rerun with the numeric id.
- **`"status": "dry_run"`** — the full plan. Present it (see step 3).
- If the matter can't be resolved (e.g. no Clio connection), the script still returns the plan
  with a `matter_note` so the user can review the deadlines and tasks; it just can't link/commit
  until an exact matter id resolves.

### 3. Present the plan for approval

Summarize the returned JSON for the user — lead with the deadlines, since those are what matter:

```markdown
## Proposed workflow for {matter display_number} — {description}
Injury date {injury_date} · at-fault: {defendant_type}{, commercial truck}{, MINOR}

### ⚠️ Georgia deadlines to be calendared (verify against current law)
| Deadline | Date | Authority | Reminders |
|----------|------|-----------|-----------|
| Personal injury SOL | {date} | O.C.G.A. § 9-3-33 | 180/90/60/30d |
| ... only the applicable ones ... |

### Tasks to be created ({n})
Grouped by phase; show name, owner role, and due date (or "milestone — {trigger}" for undated).

{Any warnings from the plan — minor's claim, government party — surfaced prominently.}
```

Then ask: **"Create these {n} tasks and {d} deadline entries on the matter?"** Wait for a clear
yes. If the user wants changes (different owners, drop a phase, shift a date), adjust — small
tweaks can be described inline, larger firm-wide changes belong in `mva_template.json`.

Assignees: Clio tasks need a real user. If the user hasn't given a role→user mapping, list firm
users (`GET /users?fields=id,name` via the clio skill) and either build an `--assignees` JSON or
pick a `--default-assignee`. Confirm who work is going to before committing.

### 4. Commit

On approval, rerun with the same flags plus `--commit`, an **exact matter id**, and the assignee
mapping:

```bash
python ".../build_workflow.py" <matter_id> --injury-date YYYY-MM-DD [...flags...] \
  --assignees /path/to/assignees.json --commit
```

Report back what was created (task / reminder / calendar-entry counts) and surface any `errors`
in the result — e.g. calendar or task creation can fail if the connection lacks the needed OAuth
scope. Don't claim success for pieces that errored.

## Notes

- **Scope:** pre-litigation only (Phases 1–7). Litigation (Phase 8) and file closing (Phase 9)
  are deliberately excluded — they're a later stage, not new-matter intake.
- **Idempotency:** the script doesn't check for existing tasks, so running `--commit` twice
  creates duplicates. Only commit once per matter; if you must re-run, tell the user so they can
  clean up.
- **Deadlines vs. reminders:** each deadline becomes one calendar entry on the due date; the
  reminders become high-priority tasks. Reminders whose date has already passed are skipped.
- **The template is the firm's to own.** If the user's process differs (extra tasks, different
  offsets, different reminder cadence), edit `references/mva_template.json` — that's the single
  source the script builds from.
