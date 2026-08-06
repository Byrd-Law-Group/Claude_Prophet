---
name: clio-demand
description: "Draft a personal-injury demand letter (and specials summary) for a Clio matter, built from the matter's liability facts and the medical special damages. Use this whenever the user wants to assemble or draft a demand — 'draft a demand letter for the Smith case', 'put together the demand package for the Brown matter', 'write the demand to the insurer', 'start the settlement demand', or 'we're ready to demand on this case'. It pulls the accident/liability facts and the medical specials (from the clio-medical-tracker ledger), drafts a structured demand letter for attorney review, and can save it to the matter via clio-documents. It NEVER sends the demand and requires attorney sign-off — firm policy is no demand goes out without approval. For tracking the underlying bills use clio-medical-tracker; to upload the finished letter use clio-documents."
---

# Clio Demand Builder

Assembles a PI demand letter from what's already in Clio: the liability story and
the medical special damages. It **drafts for attorney review** — it does not set a
demand number on its own, does not send anything, and follows the firm rule that
**no demand leaves without supervising-attorney sign-off**.

## Workflow

1. **Gather the data:**

   ```bash
   python scripts/demand_data.py --matter "Brown, Dawn"
   ```

   Returns: matter + responsible attorney, client (name/phone/email/address),
   `liability_notes` (accident facts from the matter notes), `specials` (the
   medical-tracker totals + provider/bill breakdown), and `documents_on_file`.

2. **Check readiness.** If `specials` is `null`, no medical ledger exists yet —
   route the user to **clio-medical-tracker** to log providers/bills first, or ask
   them to supply the numbers. If `specials.records_outstanding` is non-empty, warn
   that the demand is premature — you don't demand before records are in.

3. **Draft the letter** using the structure below. Produce it as a Word document
   with the **docx** skill (professional letter formatting) unless the user wants
   plain text.

4. **Preview for attorney review**, clearly marked **DRAFT — for attorney review,
   not sent.** Present the liability summary, the specials table, and any figure you
   want the attorney to set (the demand amount).

5. **On approval**, offer to save it to the matter with **clio-documents**
   (`--file <letter> --matter <id>`). Sending remains a human action.

## Demand letter structure

- **Heading / recipient** — to the at-fault carrier/adjuster and claim number
  (pull from the liability notes; ask if not on file).
- **Re: line** — client, date of loss, claim number.
- **Liability** — a clear narrative of how the collision happened and why the
  insured is at fault, from the accident facts. Cite the police report if on file.
- **Injuries & treatment** — a plain-language medical narrative built from the
  provider list and records.
- **Special damages** — an itemized table: each provider and billed amount, wage
  loss, out-of-pocket, and the **total special damages** from `specials`.
- **Demand** — leave the demand **amount blank or bracketed `[ATTORNEY TO SET]`**;
  do not invent a number.
- **Response deadline** — if a time-limited demand (O.C.G.A. § 9-11-67.1), flag
  that the attorney must set the terms; don't assert a statutory deadline yourself.

## Guardrails (important)

- **No invented facts or numbers.** Every special comes from the ledger; every
  liability fact from the notes. If something's missing, mark it `[CONFIRM]` and
  ask — never fabricate an injury, treatment, bill, or claim number.
- **Never set the demand amount.** Case valuation and the demand figure are the
  attorney's call. Draft everything else; bracket the number.
- **Attorney sign-off required, and no auto-send.** Label the draft accordingly.
- Surface `warnings` (e.g. couldn't read documents/notes) so the attorney knows the
  draft may be missing inputs.
