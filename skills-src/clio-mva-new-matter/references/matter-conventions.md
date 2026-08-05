# Byrd Law Group — new MVA matter conventions

Defaults the `create_matter.py` script applies when opening a motor vehicle accident matter,
and why. Edit the script's defaults if the firm's conventions change.

## Field defaults

| Field | Default | Notes |
|-------|---------|-------|
| Description | `<client> — Motor Vehicle Accident` | Keeps MVA matters findable/consistent. Override per case. |
| Practice area | `Personal Injury` | Looked up by name in Clio; matter is still created if it can't be resolved (with a warning). |
| Status | `open` | New signed cases go straight to Open. Use `pending` if the retainer/conflict check isn't cleared yet. |
| Billing method | `contingency` | Standard for PI/MVA. Change to `hourly`/`flat`/`pro_bono` if a case differs. |
| Responsible attorney | current Clio user | The person running intake, unless a name/id is given. |
| Originating attorney | = responsible attorney | Override when the originating attorney differs (referrals, etc.). |
| Open date | today | Intake date. |

## Client contact

- Person is the default contact type; a company client (e.g. a commercial plaintiff) uses
  `--client-type company`.
- The script reuses an existing contact on an exact name match (or a single search hit) to
  avoid duplicate clients. Multiple matches are returned for a human to pick.
- Email/phone are only written when a **new** contact is created; they are not used to edit
  an existing contact.

## What this skill deliberately does NOT do

- No tasks, no deadlines, no calendar entries. Georgia SOL (O.C.G.A. § 9-3-33), ante litem
  notices, and the phase task checklist are owned by the **clio-mva-intake** skill. This
  skill opens the matter and hands off the injury date to that workflow.
- No conflict check and no existing-matter check — it will happily open a second matter for
  the same client. Confirm the case isn't already open before committing.
