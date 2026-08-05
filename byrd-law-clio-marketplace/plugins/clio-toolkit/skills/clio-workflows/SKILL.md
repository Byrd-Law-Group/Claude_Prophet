---
name: clio-workflows
description: "Apply a reusable task/workflow template to a Clio Manage matter — creates the whole checklist of tasks (with due dates, owners, priorities) and any calculated deadlines with reminders, in one step. Use this whenever the user wants to set up, apply, run, or 'kick off' a standard process on a matter, create a batch of tasks from a checklist or SOP, apply a case-type workflow (MVA, slip-and-fall, onboarding, or any custom one), or asks 'set up the standard tasks for this new case' / 'apply our intake workflow' / 'add the whole checklist to this matter'. It's the general engine — templates live in a folder and new workflows are added as JSON, no code. This skill WRITES to Clio, so it always previews the full plan for approval before creating anything. For a single one-off task use the clio skill directly; for read-only matter review use clio-matter-analysis."
---

# Clio Workflows

Apply a saved workflow template to a matter: the engine reads a template (a checklist of tasks
plus optional calculated deadlines), computes the dates, shows a plan, and — only after the user
approves — creates everything in Clio. New workflows are JSON files in `templates/`; you never
edit code to add one.

Built on the **clio** skill for auth/API. Templates and the format guide live in `templates/`
(`templates/_TEMPLATE_GUIDE.md` explains how to write one).

## This skill writes to Clio — preview first, always

Creating a batch of tasks and calendar deadlines changes real practice data. The flow is
strictly **compute → show the user → explicit yes → create**. The engine enforces it: dry-run by
default, writes only with `--commit`. Never pass `--commit` before the user has seen and approved
the plan. And any legal deadline a template computes is a **calendaring aid, not legal advice** —
say so, and note the attorney must verify dates against current law.

## Workflow

### 1. Pick the template

If the user names a workflow ("run our MVA intake", "the onboarding checklist"), map it to a
template. If unsure what exists, list them:

```bash
python "/Users/deandreabyrd/.claude/skills/clio-workflows/scripts/apply_workflow.py" --list
```

Bundled templates: `mva-prelit` (MVA pre-litigation, with Georgia deadlines), `slip-and-fall`
(premises liability), `new-client-onboarding` (generic). If none fits, offer to create a new
template — see step 5.

### 2. Find out what inputs the template needs

Templates declare their required dates and flags. Check before running so you can ask the user
for what's missing rather than guessing:

```bash
python ".../apply_workflow.py" --template mva-prelit --describe
```

This lists `date_inputs` (e.g. `injury_date` — required) and `flags` (e.g. `defendant`,
`commercial_truck`). Dates like a statute-of-limitations basis are worth getting exactly right —
a wrong date means a wrong deadline, so confirm them with the user.

### 3. Build the preview (dry run)

```bash
python ".../apply_workflow.py" "<matter name or id>" --template mva-prelit \
  --date injury_date=YYYY-MM-DD [--date loss_date=YYYY-MM-DD] \
  [--flag defendant=state] [--flag commercial_truck=true]
```

Outcomes:
- **`"status": "missing_inputs"`** — a required date wasn't supplied; ask the user and rerun.
- **`"status": "ambiguous"`** — several matters matched; show candidates and ask which, then use
  the numeric id.
- **`"status": "dry_run"`** — the full plan. Present it (step 4).
- If the matter can't be resolved (e.g. no Clio connection), the plan still returns with a
  `matter_note` so the user can review tasks/deadlines; it just can't link/commit until an exact
  id resolves.

### 4. Present the plan and get approval

Summarize the returned JSON — lead with deadlines if the template has any:

```markdown
## {template} for {matter display_number} — {description}
{key dates and flags used}

### ⚠️ Deadlines to be calendared (verify against current law)   ← only if any
| Deadline | Date | Authority | Reminders |

### Tasks to be created ({n})
Grouped by phase; name · owner role · due date (or "milestone — {trigger}" for undated).

{Surface any warnings — e.g. a skipped/tolled deadline — prominently.}
```

Then ask: **"Create these {n} tasks{ and d deadlines} on the matter?"** Wait for a clear yes.
Small tweaks the user asks for can be handled by adjusting flags/dates and re-previewing;
lasting changes to the process belong in the template JSON.

Assignees: tasks need real Clio users. If the user hasn't provided a role→user mapping, list
firm users (`GET /users?fields=id,name` via the clio skill) and build an `--assignees` JSON
(keys are the `owner` roles: intake, case_manager, paralegal, attorney) or pick a
`--default-assignee`. Confirm who work goes to before committing.

### 5. Commit

On approval, rerun with the same inputs plus `--commit`, an **exact matter id**, and assignees:

```bash
python ".../apply_workflow.py" <matter_id> --template mva-prelit \
  --date injury_date=YYYY-MM-DD [...] --assignees /path/to/roles.json --commit
```

Report what was created (task / reminder / calendar-entry counts) and surface any `errors` (e.g.
a section failing for lack of OAuth scope). Don't claim success for pieces that errored.

## Creating a new workflow template

When the user has a process not covered by an existing template, make one: read
`templates/_TEMPLATE_GUIDE.md`, then write a new `templates/<name>.json` following an existing
file. Confirm the tasks, owners, offsets, and any deadlines with the user, then apply it the same
way (steps 2–5). This is the main way the toolkit grows — most requests to "add our X workflow"
are a new template, not new code.

## One-off tasks (not a workflow)

For a single task or two ("add a task to call the adjuster Friday"), this engine is overkill —
use the **clio** skill directly:

```
POST /tasks  {"data": {"name": "Call adjuster", "due_at": "2026-08-07T17:00:00Z",
                        "priority": "Normal", "assignee": {"id": <user>, "type": "User"},
                        "matter": {"id": <matter>}}}
```

## Notes

- **Idempotency:** the engine doesn't check for existing tasks, so committing twice creates
  duplicates. Commit once per matter+template; if you must rerun, tell the user so they can clean
  up.
- **Relationship to other skills:** `clio-mva-intake` is the dedicated MVA experience; this skill
  is the general engine and includes an MVA template too. Prefer this one when the user wants a
  reusable/parameterized workflow or a non-MVA process.
