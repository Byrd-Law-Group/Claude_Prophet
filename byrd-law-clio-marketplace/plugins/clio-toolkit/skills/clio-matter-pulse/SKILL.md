---
name: clio-matter-pulse
description: "Firm-wide 'matter pulse' report that finds open Clio matters going quiet — no client contact or activity in a while. Use this whenever the user wants to catch neglected cases before clients churn — 'which matters have gone quiet', 'what cases haven't been touched in a while', 'show me stale matters', 'which clients haven't heard from us', 'run the matter pulse', 'what needs follow-up', or 'any cases falling through the cracks'. It scans every open matter, computes the most recent touch (activity, note, or logged communication), flags anything past a staleness threshold (and matters with no contact at all), and sorts by most-neglected. Read-only. Pairs with clio-client-update to draft check-in texts for the quiet ones. For a single matter's full status use clio-matter-analysis; for deadlines firm-wide use clio-deadline-radar."
---

# Clio Matter Pulse (firm-wide staleness)

Finds the open matters that have gone quiet — the ones most likely to generate an
anxious client call or a bar complaint. Read-only.

## Run it

```bash
python scripts/matter_pulse.py                 # default: stale = no touch in 21 days
python scripts/matter_pulse.py --stale-days 14 --include-pending
```

Env: `MATON_API_KEY` (and `MATON_CONNECTION` if multiple connections).

Returns JSON with `counts`, `stale_matters` (most-neglected first), and
`all_matters`. A "touch" is the most recent of: an activity/time entry, a matter
note, or a logged communication (phone/email/text).

## How to present it

1. **🔴 No contact ever** — matters where `last_touch_source` is `none`. Newest-opened
   with zero logged touches. List these first; they may be brand-new (fine) or
   genuinely abandoned (not fine) — say which by looking at how old they are.
2. **🟠 Stale** — matters past the threshold, most days-since-touch first. Show
   matter (display number + client), responsible attorney, days since last touch,
   and what that last touch was.
3. Offer the obvious next step: for any stale matter, hand off to
   **clio-client-update** to draft a client check-in text from the matter notes.

## Honesty guardrails

- **Staleness measures *logged* activity, not reality.** A lawyer may have called
  the client without logging it. Frame results as "no *recorded* contact in N
  days — worth confirming," not "nobody did anything."
- If `warnings` shows a scope error on `activities` or `communications`, the touch
  signal is weaker (it may be relying on notes alone) — say so, because a matter
  could look staler than it is.
- Newly opened matters naturally have little activity; don't alarm over a
  three-day-old file. Weigh days-since-touch against how long the matter's been open.
