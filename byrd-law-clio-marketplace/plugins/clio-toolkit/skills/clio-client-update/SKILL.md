---
name: clio-client-update
description: "Draft a short client text-message (SMS) update about a Clio matter, built from the matter's recent notes. Use this whenever the user wants to text or message a client an update on their case — 'text the client an update on the Smith matter', 'send Jones a status update', 'draft a text to the client about the accident case', 'let the client know what's happening on their matter', 'message the client the latest', or 'update the client on matter 12345'. The skill pulls the client's name and phone number and the matter's recent notes from Clio, then composes a concise, plain-language, client-safe message and PREVIEWS it (recipient, phone, exact text) for the user to send themselves via Clio's texting or their phone. It is READ-ONLY and does NOT send anything and does NOT write to Clio. For deadline/task analysis use clio-matter-analysis; to upload documents use clio-documents; for raw Clio API calls use the clio skill."
---

# Clio Client Update (text draft)

Turn a Clio matter's recent notes into a short, client-ready text update, then
preview it for the user to send. This skill **reads** from Clio and **drafts** a
message. It never sends the text and never writes to Clio — sending stays a
deliberate human action (via Clio's texting feature or the user's phone).

## Setup

Reads the Clio Manage API v4 through the Maton gateway:

```
Base URL:  https://gateway.maton.ai/clio/api/v4
Auth:      Authorization: Bearer $MATON_API_KEY
```

Set `MATON_API_KEY` (and `MATON_CONNECTION` if there are multiple Clio connections).

## Workflow

1. **Gather the data.** Run the helper to pull the client's name + phone and the
   matter's recent notes:

   ```bash
   python scripts/draft_client_update.py --matter 12345
   # or, if you only have the name:
   python scripts/draft_client_update.py --matter-name "Smith" --limit 5
   ```

   Options: `--limit N` (how many recent notes, default 5), `--since YYYY-MM-DD`
   (only notes on/after a date). If a name matches multiple matters, the script
   lists them and asks you to re-run with `--matter <id>`.

   The script prints JSON: `{matter, client:{name,phone}, notes:[{date,subject,detail}]}`.

2. **Compose the message** from the notes (see rules below). Keep it to what the
   client needs to know.

3. **Preview for approval — always.** Show the user this block and stop:

   ```
   To:      <client name>  <phone>
   Matter:  <display number> — <description>
   Message: <the exact SMS text>
   ```

   Then say the message is ready to send and that they can copy it into Clio's
   texting (or their phone). Do not claim it was sent — this skill does not send.

## How to write the message

- **Audience is the client, not the file.** Plain language, no legalese, no docket
  jargon. Warm and professional.
- **Short.** Aim for 1–4 sentences / under ~300 characters where possible. It's a
  text, not a letter. (Clio's SMS limit is 2,048 chars, but shorter is better.)
- **Summarize; don't paste.** Translate the notes into what changed and any next
  step or ask (e.g. "we filed your complaint", "the insurer requested records —
  can you send X?", "your deposition is being scheduled").
- **Lead with the person and the case in a natural way**, e.g. "Hi Jane, quick
  update on your case —". Include a firm sign-off if the firm uses one.
- **One update, most recent first.** If several notes cover the same development,
  merge them into one coherent update rather than a list of entries.

## Guardrails (important — this is a law firm texting a client)

- **Strip anything internal or privileged.** Matter notes routinely contain
  attorney work product, strategy, candid assessments, staff-to-staff instructions,
  fee/billing internals, or third-party info. NONE of that goes in a client text.
  If a note is clearly internal ("call opposing counsel's bluff", "client is
  difficult", "write off 2 hrs"), do not surface it — and if the notes contain
  **only** internal content with nothing client-appropriate, say so and draft
  nothing rather than inventing an update.
- **Flag, don't guess.** If something is ambiguous or sensitive (a settlement
  number, medical detail, a deadline you're not sure is confirmed), call it out in
  your preview and ask the user before including it.
- **Verify the recipient.** Show the exact phone number and client name so the user
  can confirm it's the right person before sending. If no phone is on file, say so.
- **No legal advice or commitments** the notes don't support (no promised outcomes,
  amounts, or dates that aren't clearly established).
- **Never auto-send or send to a list.** One matter, one preview, user sends.

## Notes

- "Matter notes" are Clio `Note` records associated with the matter (`GET /notes`).
- The client's phone comes from the matter's client contact (default number, then
  a mobile/cell, then the first number on file).
- Clio texting is US/Canada only (+1). If the client's number isn't textable, the
  drafted message can still be sent by other means — that's the user's call.
