# MVA Pre-Litigation Workflow — Reference

This is the human-readable companion to `mva_template.json` (the machine-readable source the
script reads). It summarizes what the workflow creates and the Georgia deadlines it calendars.
Edit `mva_template.json` to change task names, owners, due-date offsets, or priorities — the
script reads that file, not this one.

## Critical Georgia deadlines calendared

The script computes each applicable deadline and stacks reminder tasks at **180 / 90 / 60 / 30
days before**. Deadlines are calendared as Clio calendar entries; reminders as high-priority tasks.

| Deadline | Time limit | Authority | Basis date | When applied |
|----------|-----------|-----------|------------|--------------|
| Personal injury SOL | 2 years | O.C.G.A. § 9-3-33 | Date of injury | Always (except minors — tolled) |
| Property damage SOL | 4 years | O.C.G.A. § 9-3-31 | Date of loss | Always |
| Ante litem — municipality | 6 months | O.C.G.A. § 36-33-5 | Date of injury | `--defendant municipal` |
| Ante litem — county | 12 months | O.C.G.A. § 36-11-1 | Date of injury | `--defendant county` |
| Ante litem — State of Georgia | 12 months | O.C.G.A. § 50-21-26 | Date of injury | `--defendant state` |
| Time-limited demand | per demand terms | O.C.G.A. § 9-11-67.1 | — | Task only (serious/trucking) |
| Minor's claim | tolled | special rules | — | `--minor` → warning, no computed date |

**These computed dates are calendaring aids, not legal advice.** Georgia law changes and edge
cases (tolling, discovery rule, government identity, multiple defendants) shift real deadlines.
The supervising attorney must verify every date against current law before relying on it. When a
government vehicle/entity is even arguably involved, the short ante litem clock controls — flag
the file the same day.

## Phase tasks created

Tasks come from the firm SOP (Phases 1–7, pre-litigation). Each carries an owner role
(`intake`, `case_manager`, `paralegal`, `attorney`) and either:
- a **due date** = matter open date + an offset (Phases 1–3, the front-loaded intake/investigation
  work), or
- a **milestone trigger** (Phases 4–7) — created with no due date and a note like "Trigger: client
  reaches MMI", because those steps are event-driven, not calendar-driven. Undated open tasks are
  intentional: they keep the whole roadmap visible without inventing false deadlines.

Conditional tasks are added only when relevant:
- `--commercial-truck` → spoliation/evidence-preservation letter and the § 9-11-67.1 time-limited
  demand task.
- `--defendant` other than `private` → a same-day "escalate ante litem to attorney" task.

Phase 8 (litigation) and Phase 9 (file closing) are intentionally **not** created by this
pre-litigation workflow — they belong to a later stage.

## Role → Clio user mapping

Clio tasks require a real assignee. Provide a mapping file with `--assignees`:

```json
{
  "attorney":     {"id": 111, "type": "User"},
  "case_manager": {"id": 222, "type": "User"},
  "intake":       {"id": 333, "type": "User"},
  "paralegal":    {"id": 444, "type": "User"}
}
```

Any unmapped role falls back to `--default-assignee <id>`, then to the matter's responsible
attorney, then to the current API user. List firm users with the clio skill
(`GET /users?fields=id,name,email`) to get the ids.
