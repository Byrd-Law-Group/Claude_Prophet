# Claude_Prophet — PI Practice Agents

A Claude Code agent system for a Georgia personal-injury law practice, plus a
Telegram front end so the firm can work matters from a phone.

## What's here

**17 specialist subagents** (`.claude/agents/`), each scoped to one part of a
PI matter's lifecycle:

| Agent | Role |
|---|---|
| `pi-intake-conflicts` | New-client intake, conflict checks, accident/injury facts |
| `pi-case-manager` | Ongoing matter management — deadlines, treatment, records, bills |
| `pi-prelitigation-paralegal` | Day-to-day driver for pre-suit matters |
| `pi-litigation-paralegal` | Owns matters once suit is filed |
| `pi-medical-records` | HIPAA authorizations and records/bills requests |
| `pi-medical-chronology` | Builds the chronology once records/bills are received |
| `pi-damages-analyst` | Turns the chronology into a demand-ready damages summary |
| `pi-drafting-paralegal` | Drafts demand letters, specials summaries, LORs, etc. |
| `pi-claims-coordinator` | Opens/manages BI, UM/UIM, MedPay/PIP claims |
| `pi-negotiation-specialist` | Tracks demands, offers, counters, settlement negotiations |
| `pi-costs-liens-coordinator` | Tracks LOP providers and hard case costs |
| `pi-subrogation-erisa` | Health-insurer/government-payer subrogation and reimbursement |
| `pi-client-relations-coordinator` | Client communications, engagement letters, welcome packs |
| `pi-referral-intake-coordinator` | Tags and tracks referral sources at intake |
| `pi-public-records` | Requests police/incident reports, CAD records, and other public records |
| `pi-legal-research` | Georgia/federal case law and statute research via CourtListener |
| `pi-legal-assistant` | Front-desk/admin work — calendar, scheduling |
| `pi-practice-manager` | Firm-wide rollup across every specialist agent's portfolio |

**`.claude/skills/clio-referral-tracker/`** — a skill for tagging referral
sources on Clio matters at intake, used by `pi-referral-intake-coordinator`.

**`telegram_bot/`** — a single Telegram bot that puts all 17 agents behind
one chat. Message it like you'd talk to Claude Code in this repo; it routes
to the right specialist on its own, runs every turn through the Claude Code
CLI in `plan` permission mode (so it can research and draft but never save
or send anything on its own), and requires you to reply `confirm` before it
executes what it proposed. See [`telegram_bot/README.md`](telegram_bot/README.md)
for setup.

**`scripts/dropbox_sign.py`** — Dropbox Sign (HelloSign) integration for
sending PI documents (e.g. HIPAA authorizations) for e-signature.

## Setup

1. Clone this repo and run `npm install`.
2. Copy `.env.example` to `.env` and fill in the Clio Manage API values
   (used by the `clio-referral-tracker` skill).
3. Follow [`telegram_bot/README.md`](telegram_bot/README.md) to stand up the
   Telegram front end, if you want one.
4. Open the repo in Claude Code — the agents in `.claude/agents/` are
   available immediately; no separate install step.

## Requirements

- [Claude Code CLI](https://claude.com/claude-code), logged in
- Node.js (for the Telegram bot)
- A Clio Manage account with API access (for Clio-backed agents/skills)
