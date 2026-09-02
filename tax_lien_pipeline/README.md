# Tax-Lien Acquisition Outreach Pipeline

Source tax-delinquent homeowner leads (starting in **Montgomery County, OH**),
compliance-scrub them, draft personalized **call scripts and texts** offering to
buy the property by paying off the back taxes, send them under a human-approval
gate, and log every touch.

> **You prepare and approve; the tool sends.** Nothing goes out without (1) a
> lawful basis to contact, (2) a passing compliance check, and (3) your explicit
> per-lead approval. This is manual, one-to-one outreach by design — **not** an
> autodialer or mass-texting blaster.

## Why it's built this careful way
Cold-contacting homeowners — especially distressed ones — is heavily regulated:
- **TCPA** — $500–$1,500 **per** call/text for violations; marketing robocalls/
  texts need prior express written consent.
- **National + Ohio Do-Not-Call** — numbers must be scrubbed before contact.
- **Ohio homeowner / equity-purchaser protections** — no misleading distressed
  owners about amounts, timelines, or their options.

The pipeline enforces DNC/suppression scrubbing, an 8am–9pm ET calling window,
per-lead attempt caps, mandatory caller identification, and permanent opt-out
honoring. **Have your attorney confirm your Ohio disclosures and consent approach
before going live — this is not legal advice.**

## Requirements
- Python 3.9+ (uses only the standard library for the core — no `pip install`).
- Twilio account **only when you're ready to actually send** (SMS + voice).

## Quick start (runs today, no credentials)
```bash
cd tax_lien_pipeline
python3 cli.py init
python3 cli.py import sample_data/montgomery_sample.csv
python3 cli.py scrub
python3 cli.py list
python3 cli.py draft 1          # preview the SMS + call script for lead #1
```

## The workflow
| Step | Command | What it does |
|------|---------|--------------|
| 1 | `init` | Create `leads.db` (SQLite). |
| 2 | `import <csv> [--source ...]` | Load + normalize + priority-score delinquent leads. |
| 3 | `scrub` | DNC/suppression scrub → set per-channel eligibility. |
| 4 | `list [status]` / `show <id>` | Review leads (ranked) and their touch history. |
| 5 | `consent <id> <basis>` | Record a lawful basis to contact (`express_written` / `prior_business`). |
| 6 | `draft <id>` | Preview the personalized SMS + call script. |
| 7 | `approve <id>` | **Human sign-off** — required before anything can send. |
| 8 | `send-sms <id>` / `call <id>` | Send/dial (preview unless Twilio is set). Add `--dry-run` to force preview. |
| 9 | `log <id> <outcome>` | Record a call/text result (`interested`, `no_answer`, `opt_out`, …). |
| 10 | `optout <id\|phone>` | Permanently suppress a contact. |
| — | `followups` / `stats` | Leads due for follow-up; pipeline summary. |

### Eligibility & the compliance gate
After `scrub`, each lead is `call_text`, `mail_only`, or `do_not_contact`.
DNC scrubbing is wired to **The Blacklist Alliance** (`tlp/dnc.py`): set
`BLACKLIST_API_KEY` and each number is checked against DNC + known-litigator
lists → `clear` (callable), `listed` (mail-only), or `unknown`. **Without a key
— or on any vendor error — the number stays `unknown` and defaults to
`mail_only`**; it will not call/text until the vendor clears it **or** you
record a lawful `consent` basis. This fail-safe means an outage can never open a
contact path. `can_contact()` is the single gate every send passes through;
there are no code overrides for opt-outs or calling hours.

## Getting the leads (Montgomery County, OH)
Export/download delinquent + owner data, then `import` the CSV:
- **Montgomery County Treasurer** — delinquent-tax list / tax-lien certificate sale.
- **Montgomery County Auditor** — owner of record, mailing address, value, homestead.
- **Recorder / Clerk of Courts** — recorded liens, mortgages, tax foreclosures.

The importer maps many common column names automatically (parcel, address,
owner, amount due, value, phone, …). A parcel number column is best for de-duping.
Skip-trace phone numbers via a legitimate provider before import. A live scraper
is intentionally omitted — respect each portal's terms of use.

## Going live (Twilio)
Set these in the repo `.env` (or the environment):
```
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_FROM_NUMBER=+1937XXXXXXX      # your Twilio number (E.164)
INVESTOR_PHONE_NUMBER=+1937XXXXXXX   # your phone; click-to-dial rings this first
CALLER_NAME=Your Name
COMPANY_NAME=Your Company
CALLBACK_NUMBER=+1937XXXXXXX
```
- **SMS:** `send-sms <id>` posts to Twilio; opt-out language is auto-appended.
- **Calls:** `call <id>` uses **click-to-dial** — Twilio rings *you* first, then
  bridges you to the homeowner. You're always live on the line.
- **Inbound STOP:** run `python3 webhook.py --port 8080` and point your Twilio
  number's inbound-SMS webhook at `https://<host>/sms`. STOP/UNSUBSCRIBE/etc.
  auto-suppress the number and flag the lead; other replies are logged.

## Still your responsibility before live outreach
1. A **Blacklist Alliance** account + `BLACKLIST_API_KEY` (the integration is
   already wired into `scrub_number` via `tlp/dnc.py`), or documented consent
   per lead. Confirm current pricing/coverage with the vendor, and have your
   attorney bless the vendor choice.
2. Attorney review of your Ohio equity-purchaser disclosures and consent language.
3. Legitimate lead + skip-trace data sources.

## Tests
Stdlib `unittest` — no dependencies. From `tax_lien_pipeline/`:
```bash
python3 -m unittest discover -s tests
```
The suite pins the compliance gate (`can_contact`): opt-out and suppression
blocking, the mail-only default for unknown-DNC numbers, calling-hour and
attempt-cap enforcement, and that queued previews never count as attempts. It
also covers phone normalization (suppression must match regardless of
formatting) and the importer's alias mapping, priority scoring, Montgomery
native format, and enrich-don't-clobber merge. A second suite
(`tests/test_dnc.py`) pins the Blacklist Alliance scrub's fail-safe: a missing
key, HTTP error, network exception, or unrecognized payload must all resolve to
`unknown` — never a false `clear`. No test touches the network.

## Files
```
tax_lien_pipeline/
├── cli.py             # command-line workflow
├── webhook.py         # inbound-SMS STOP/opt-out handler
├── tlp/
│   ├── config.py      # env + calling-window + Twilio config
│   ├── db.py          # SQLite schema + helpers
│   ├── importer.py    # CSV import, normalization, priority scoring
│   ├── compliance.py  # DNC scrub, calling hours, opt-out — the gate
│   ├── dnc.py         # Blacklist Alliance DNC lookup (fail-safe to 'unknown')
│   ├── outreach.py    # SMS + call-script drafting
│   └── messaging.py   # Twilio SMS + click-to-dial (stdlib urllib)
├── tests/test_pipeline.py   # compliance-gate + importer regression tests
├── tests/test_dnc.py        # DNC vendor scrub fail-safe tests
└── sample_data/montgomery_sample.csv
```
