# Byrd Law Group — Clio Toolkit

A Claude Code plugin marketplace that bundles the firm's Clio Manage skills into one
installable package. Add the marketplace once, install `clio-toolkit`, and every teammate
(intake, case managers, paralegals, attorneys) gets the same tools.

## What's inside

The `clio-toolkit` plugin bundles three skills:

| Skill | What it does | Reads/Writes |
|-------|--------------|--------------|
| **clio** | Base Clio Manage API access with managed OAuth (matters, contacts, tasks, activities, calendar, documents, billing). The other two build on it. | Read/Write |
| **clio-matter-analysis** | Deep-dive analysis of a single matter, deadline- and task-risk first: what's overdue, due soon, upcoming court dates, staleness, and recommended next actions. | Read-only |
| **clio-mva-intake** | Stands up the standard MVA pre-litigation workflow on a new matter — the Phase 1–7 task checklist plus calendar entries for the critical Georgia deadlines (SOL, ante litem) with stacked reminders. Previews the full plan for approval before writing anything. | Write (preview-first) |

## Install

In an interactive Claude Code session:

```bash
/plugin marketplace add /Users/deandreabyrd/Documents/GitHub/Claude_Prophet/byrd-law-clio-marketplace
```

(Or point it at the git URL once this folder is pushed to a repo — e.g.
`/plugin marketplace add your-org/byrd-law-clio-marketplace`.)

Then install the plugin:

```bash
/plugin install clio-toolkit@byrd-law-clio
```

Restart the session if prompted. The three skills then trigger automatically based on what
you ask (e.g. "analyze the Smith matter", "set up the new Jones car accident case").

## Setup required before use

1. **Maton API key** — set `MATON_API_KEY` (see the `clio` skill for where to get it).
2. **Clio OAuth connection** — authorize Clio at https://ctrl.maton.ai (or via `claude mcp`).
   Until this is done, calls return `401 Unauthorized`.
3. **User mapping (for clio-mva-intake)** — Clio tasks need real assignees. List firm users
   (`GET /users?fields=id,name`) and build a role→user JSON mapping. See the skill's
   `references/mva-sop.md`.

## Customizing the MVA workflow

The MVA task list and deadline rules are the firm's to own. Edit
`plugins/clio-toolkit/skills/clio-mva-intake/references/mva_template.json` to change task
names, owners, due-date offsets, reminder cadence, or deadlines, then bump the version in the
manifests and have the team update.

## Disclaimer

The computed litigation deadlines are calendaring aids, not legal advice. Georgia law and
case-specific tolling change real deadlines — the supervising attorney must verify every date
against current law before relying on it.

---
Owner: Byrd Law Group · Version 1.0.0
