---
name: clio-medical-tracker
description: "Track medical providers, records status, bills, and liens for a Clio personal-injury matter, and total the special damages. Use this whenever the user is managing the medical side of a PI case — 'add Grady ER to the Smith case with a $4,200 bill', 'what medical bills do we have on the Brown matter', 'which records are still outstanding', 'total the medical specials', 'log the MedPay lien', 'set records received for the chiropractor', or 'what are our special damages'. It keeps a per-matter ledger (providers, records requested/received, billed amounts, who paid, liens) stored as a tagged matter note in Clio, and computes total billed medical + wage loss + out-of-pocket = special damages. Those totals feed clio-demand. Writes only its own ledger note, and previews changes before saving. For the demand letter itself use clio-demand; for a matter overview use clio-matter-analysis."
---

# Clio Medical Tracker (PI special damages)

Maintains the medical picture of a PI matter — providers, records status, bills,
liens — and totals the **special damages** that drive settlement value and the
demand. Because Clio has no native "medical bills" object, the ledger lives as a
tagged **matter note** (`MEDICAL LEDGER [clio-medical-tracker]`), so it's both
machine-readable and visible to your team in Clio.

## Commands

```bash
python scripts/medical_tracker.py show   --matter <id|name>     # read the ledger
python scripts/medical_tracker.py totals --matter <id>          # specials summary

python scripts/medical_tracker.py add-provider --matter <id> --name "Grady ER"
python scripts/medical_tracker.py set-records  --matter <id> --name "Grady ER" \
    --requested 2026-01-10 --received 2026-02-01
python scripts/medical_tracker.py set-bill     --matter <id> --name "Grady ER" \
    --amount 4200.00 --paid-by MedPay --lien 4200.00
python scripts/medical_tracker.py set-extras   --matter <id> --wage-loss 3000 --out-of-pocket 250
python scripts/medical_tracker.py remove-provider --matter <id> --name "Grady ER"
```

Env: `MATON_API_KEY` (+ `MATON_CONNECTION` if needed). Writing the ledger note
needs the same note scope the other skills use.

## What it computes

`totals` returns: `total_billed_medical`, `total_liens`, `wage_loss`,
`out_of_pocket`, `total_special_damages` (= billed medical + wage loss +
out-of-pocket), provider count, and `records_outstanding` (providers with no
records-received date).

## How to use it well

- **Every write previews first.** Show the user the change and the resulting
  totals, then confirm. The script prints the full ledger + totals after saving so
  you can read it back.
- **Records status drives the case.** Surface `records_outstanding` prominently —
  you can't finalize specials or a demand until records are in. Offer to create
  follow-up tasks (via the `clio` skill) for outstanding providers.
- **Liens matter at disbursement.** Track `lien`/`lien_amount` as you learn them
  (MedPay, health/ERISA, hospital, Medicare/Medicaid) — these feed the reductions
  and the settlement statement later.
- **Hand off to clio-demand.** Once records are in and bills are logged, the
  `total_special_damages` and the provider/bill breakdown are exactly what the
  demand builder needs.

## Guardrails

- Numbers come from the user or from itemized bills — **don't invent amounts.** If
  a bill isn't known yet, leave it null rather than guessing.
- The ledger is the single source of truth this skill maintains; don't hand-edit
  the note's JSON in Clio (edit through the skill so it stays valid).
- This is bookkeeping, not a valuation. It totals hard specials; it does not opine
  on pain-and-suffering or case value.
