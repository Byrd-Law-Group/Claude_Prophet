---
name: clio-mva-new-matter
description: "Open a brand-new motor vehicle accident (MVA) / car-accident / personal-injury matter in Clio Manage — finds or creates the client contact, then creates the matter record itself (description, practice area, responsible attorney, status, open date, file reference). Use this when a new client signs up or a new case comes in and needs a matter opened in Clio: 'open a new MVA matter for Jane Smith', 'create a new car accident case', 'set up a new client and matter in Clio', 'intake a new PI client', 'start a new matter for the Jones accident' — even if they don't say 'matter'. This skill WRITES to Clio, so it always previews the full plan for approval before creating anything. It only OPENS the matter; to then add the intake task checklist and calendar the Georgia deadlines, hand off to the clio-mva-intake skill. For applying the workflow to a matter that already exists use clio-mva-intake; for read-only review use clio-matter-analysis; for arbitrary Clio API calls use the clio skill."
---

# Clio — Open a New MVA Matter

Open a new motor vehicle accident matter in Clio Manage for the Byrd Law Group: find or
create the **client contact**, then create the **matter** (description, practice area,
responsible/originating attorney, status, open date, firm file number).

Built on the **clio** skill for auth/API (Maton gateway, `MATON_API_KEY`). This skill is
narrow on purpose — it *opens* the matter. Setting up the intake task checklist and
calendaring the Georgia SOL / ante litem deadlines is the job of the **clio-mva-intake**
skill, which you run next on the matter this one creates.

## This skill writes to Clio — preview first, always

Creating a contact and a matter changes real practice-management data, so the flow is
strictly **plan → show the user → get an explicit yes → create**. The script enforces it:
it dry-runs by default and only writes with `--commit`. Never pass `--commit` until the
user has seen the plan and approved it.

## Workflow

### 1. Gather the inputs

To open the matter you need:

- **Client** (required) — the person or company the matter is *for*. Give a full name; the
  script searches Clio for an existing contact and reuses it, or plans to create a new one.
  If you already know the contact, pass its id with `--client-id`.
- **Client type** — `person` (default) or `company`. For a person you can pass
  `--first-name`/`--last-name` explicitly; otherwise the name is split on the last space.
- **Contact details** (optional, only used when creating a *new* contact) — `--email`,
  `--phone`.
- **Matter description** — defaults to `"<client> — Motor Vehicle Accident"`; override with
  `--description`.
- **Responsible / originating attorney** — id or name. Responsible defaults to the current
  Clio user; originating defaults to the responsible attorney. If a name is ambiguous the
  script reports the candidates so you can pass an id.
- **Firm file number** — `--client-reference` (optional).
- **Date of injury** — `--injury-date`. It is *not* stored on the matter; it's carried into
  the plan and echoed as the value to feed **clio-mva-intake** in step 4.

Defaults worth knowing: `--practice-area "Personal Injury"`, `--status open`,
`--billing-method contingency`, `--open-date` today. Ask about anything that materially
changes the record (client identity, attorney, description) rather than assuming.

### 2. Build the preview (dry run)

```bash
python "/Users/deandreabyrd/.claude/skills/clio-mva-new-matter/scripts/create_matter.py" \
  "<client name>" [--client-id ID] [--client-type person|company] \
  [--first-name F --last-name L] [--email E] [--phone P] \
  [--description TEXT] [--practice-area NAME] [--status open|pending|closed] \
  [--responsible-attorney ID|NAME] [--originating-attorney ID|NAME] \
  [--client-reference TEXT] [--open-date YYYY-MM-DD] [--injury-date YYYY-MM-DD]
```

Outcomes:
- **`"status": "ambiguous_client"`** — several contacts matched the name. Show the
  candidates and ask which; rerun with `--client-id`, or force a distinct new contact.
- **`"status": "dry_run"`** — the full plan (client action + matter fields). Present it
  (step 3). If the API is unreachable the plan still renders with `warnings`; it just can't
  confirm the client or attorney until a connection resolves.

### 3. Present the plan for approval

Summarize the returned JSON for the user:

```markdown
## New MVA matter to open
**Client:** {create new | use existing #id} — {display_name}{ email/phone if new}
**Matter:** {description}
· status {status} · practice area {practice_area.name or "none"} · billing {billing_method}
· responsible {responsible_attorney.name} · originating {originating_attorney.name}
· open date {open_date}{ · file # client_reference}

{Any warnings — unresolved attorney/practice area, or "will create a new contact".}
```

Surface warnings prominently — especially "will create a new contact" (so a duplicate
client isn't made by mistake) and any unresolved attorney or practice area. If the user
wants changes, adjust the flags and re-run the dry run. Then ask: **"Open this matter (and
create the client contact) in Clio?"** and wait for a clear yes.

### 4. Commit, then hand off to intake

On approval, rerun with the same flags plus `--commit`:

```bash
python ".../create_matter.py" "<client name>" [...same flags...] --commit
```

Report what was created — the new **contact id** (if any) and the **matter id / display
number** — and surface any `errors` (e.g. missing OAuth scope, validation). Don't claim
success for pieces that errored.

Then offer the natural next step: **run the `clio-mva-intake` skill on the new matter** to
create the pre-litigation task checklist and calendar the Georgia deadlines. If an injury
date was given, pass it through — the commit result's `next_step` echoes the exact
`--injury-date` to use.

## Notes

- **Scope:** opens the matter only (contact + matter record). Tasks, deadlines, and the
  Georgia SOL / ante litem calendaring belong to **clio-mva-intake** — this skill hands off
  to it, it does not duplicate it.
- **De-duplication:** an exact name match (or a single search hit) is reused as the client;
  multiple hits return `ambiguous_client` for you to resolve. There is *no* check for an
  existing matter for that client, so confirm you're not opening a duplicate case.
- **Idempotency:** running `--commit` twice creates a second matter (and possibly a second
  contact). Commit once; if you must re-run, tell the user so they can clean up.
- **Attorney/practice-area lookups** are by id or name. Names that match more than one
  record are reported, not guessed — pass an id to disambiguate.
