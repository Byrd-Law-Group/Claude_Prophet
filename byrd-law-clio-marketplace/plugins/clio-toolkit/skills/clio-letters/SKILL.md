---
name: clio-letters
description: "Generate standard firm letters for a Clio matter — Letter of Representation to insurers, HIPAA medical-records authorization, and evidence-preservation (spoliation) letters — auto-filled from the matter and client data. Use this whenever the user wants a routine letter drafted from a case's data — 'draft a letter of representation for the Smith carrier', 'generate a HIPAA authorization for the client to sign', 'send an LOR to the at-fault insurer', 'prepare a spoliation letter for the trucking case', or 'do the rep letters for the new matter'. It pulls the client name/address, responsible attorney, and case details from Clio, fills the chosen template (leaving unverified items bracketed to confirm), and can save the finished letter to the matter via clio-documents. It drafts for review and does not send. For the demand letter use clio-demand; to upload a finished letter use clio-documents."
---

# Clio Letters (standard correspondence)

Fills the firm's routine letters from a matter's Clio data, so a 15-minute task
takes seconds. Drafts for review — it does not send, and it brackets anything it
can't verify rather than guessing.

## Available templates (`templates/`)

- **letter_of_representation.md** — LOR to a carrier/adjuster (do-not-contact + coverage/limits request)
- **hipaa_authorization.md** — HIPAA authorization for the client to sign
- **spoliation_letter.md** — evidence-preservation letter (serious / commercial-truck cases)

## Workflow

1. **Gather the merge fields:**

   ```bash
   python scripts/letter_data.py --matter "Brown, Dawn"
   ```

   Returns `merge_fields` (client name/address/phone/email, responsible attorney,
   matter number) and `liability_notes` (where adjuster/claim/carrier details often
   live).

2. **Pick the template** the user asked for and fill the `{{placeholders}}` from the
   merge fields. Fill `{{today_date}}` with today's date.

3. **Resolve the `[CONFIRM …]` items.** These are things Clio usually doesn't hold
   in a structured field — carrier name, adjuster, claim number, date of loss,
   client DOB, provider address. Look for them in `liability_notes`, and **ask the
   user for anything still missing** before finalizing. Never invent them.

4. **Produce the letter** as a Word document with the **docx** skill (or plain text
   if the user prefers), on firm letterhead (ask for the firm block once).

5. **Preview**, marked **DRAFT — for review**, then on approval offer to save it to
   the matter with **clio-documents** (`--file <letter> --matter <id>`).

## Guardrails

- **Don't guess the [CONFIRM] fields.** A wrong claim number or carrier on a legal
  letter is worse than a blank — leave the bracket and ask.
- **Don't alter fixed legal language** (the HIPAA authorization/revocation text, the
  spoliation preservation list) — fill parties only; the attorney owns scope.
- **The client signs their own documents** (HIPAA); the firm never signs for them.
- **Draft only — no send.** Sending is the user's action. Attorney review before
  anything goes to an insurer or third party.
