# Writing a workflow template

A template is one JSON file in this folder. The filename (minus `.json`) is the template name
used with `--template`. The engine (`scripts/apply_workflow.py`) reads every file here — add a
new workflow by adding a file, no code changes. Copy `new-client-onboarding.json` (simplest) or
`mva-prelit.json` (full, with statutory deadlines) as a starting point.

## Top-level fields

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Template id (match the filename). |
| `description` | yes | One line; shown in `--list`. |
| `practice_area` | no | Free text label. |
| `anchor_date` | no | Which `date_input` key task offsets count from. Default `open_date`. |
| `reminder_offsets_days` | no | Days-before values for deadline reminder tasks, e.g. `[180,90,60,30]`. Omit for no reminders. |
| `date_inputs` | no | Dates the template needs (see below). |
| `flags` | no | Conditions that turn tasks/deadlines on or off (see below). |
| `deadlines` | no | Calculated calendar deadlines (see below). |
| `tasks` | yes | The checklist (see below). |

## date_inputs

Each date the workflow needs. Provided at run time with `--date key=YYYY-MM-DD`.

```json
{"key": "injury_date", "label": "Date of injury", "required": true}
```
- `default: "today"` — fill with today's date if not supplied.
- `default_from: "other_key"` — fall back to another input's value (e.g. loss date defaults to injury date).
- `required: true` — the engine refuses to run until it's provided.

## flags

Named conditions. Provided with `--flag key=value`.

```json
{"key": "defendant", "type": "enum", "choices": ["private","municipal","county","state"], "default": "private"}
{"key": "commercial_truck", "type": "bool", "default": false}
```
`bool` flags accept true/false/yes/no/1/0.

## Conditions (`applies`, `applies_if`, `skip_if`)

A small expression evaluated against the flags:
- `"always"` or omitted → always true
- `"commercial_truck"` → true when that bool flag is set
- `"defendant==state"` → true when the enum equals a value
- `"defendant!=private"` → true when it does not

## deadlines

Calculated dates that become Clio calendar entries, each with reminder tasks at
`reminder_offsets_days`.

```json
{"key": "sol_pi", "label": "Statute of Limitations — Personal Injury",
 "authority": "O.C.G.A. § 9-3-33", "basis": "injury_date", "months": 24,
 "applies": "always", "skip_if": "minor"}
```
- `basis` — which `date_input` the clock runs from.
- `months` (or `years`) — the period added to the basis date.
- `applies` — only create this deadline when the condition is true.
- `skip_if` — suppress it when the condition is true (e.g. tolled minor's claim), with a warning.

## tasks

Each item becomes a Clio task assigned to a role.

```json
{"phase": 1, "name": "Run conflict check", "owner": "intake", "offset_days": 0,
 "priority": "High", "applies_if": "always"}
```
- `owner` — a role string mapped to a Clio user at run time (`--assignees`).
- `offset_days` — due date = anchor date + N days. **Omit** `offset_days` and use `trigger`
  instead for milestone tasks that have no fixed date (e.g. `"trigger": "Client reaches MMI"`).
  Those are created as open tasks with no due date — a visible reminder without a false deadline.
- `priority` — `High` / `Normal` / `Low`.
- `phase` — optional grouping; prefixed as `[P1]` on the created task name.
- `applies_if` — only create the task when the condition is true.

## Legal deadlines are the firm's responsibility

Any statutory period baked into a template is a calendaring aid, not legal advice. Verify the
authority and current law before relying on computed dates, and re-review templates when the law
changes.
