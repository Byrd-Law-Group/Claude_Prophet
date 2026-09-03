---
name: clio-referral-tracker
description: Tag, read, and report on the referral source of Clio personal-injury matters — set an explicit source tag on a matter (a Clio custom field), look up a matter's current source (explicit tag, or a best-effort parse of its description), or run a firm-wide ranked report with an unknown_source bucket for untracked matters. Use whenever intake needs a source logged, a matter's source needs checking, or BD/marketing wants a referral breakdown.
---

Backs the `pi-referral-intake-coordinator` agent. Three subcommands, run via the Bash tool against the script in this skill's `scripts/` directory. All output is JSON on stdout (except `set`'s human-readable preview) so it's easy to parse and report on.

## Prerequisites

Set these environment variables before invoking (e.g. in the shell, or the project's `.env`):

- `CLIO_ACCESS_TOKEN` — a valid Clio Manage API v4 OAuth2 bearer token. Required.
- `CLIO_API_BASE` — API base URL. Defaults to `https://app.clio.com/api/v4` (use the EU/CA/AU regional base if the firm's Clio account is on one).
- `CLIO_REFERRAL_FIELD_NAME` — the name of the Matter custom field used to store the referral source. Defaults to `Referral Source`. The field must already exist in Clio (Settings → Custom Fields → Matter) — this skill does not create custom fields.

If `CLIO_ACCESS_TOKEN` is missing, or no custom field matching the configured name exists, the script fails fast with a clear error — surface that to the user rather than retrying.

`known-sources.json` in this skill's directory is a firm-maintained list of known referral source names used only for the best-effort description-parsing fallback (see `report` and `show` below). Keep it updated as new sources come up; it is not the source of truth — the custom field tag is.

## Subcommands

### `show` — read a matter's current source

```bash
node .claude/skills/clio-referral-tracker/scripts/referral-tracker.js show <matter>
```

`<matter>` is a Clio display number (tried first, exact match) or a free-text search term (client name, matter description) if that doesn't resolve to exactly one matter. Ambiguous or no-match results fail with the candidate list — ask the user to disambiguate rather than guessing.

Returns `{ matter_id, display_number, source, source_type }` where `source_type` is `explicit` (custom field set), `parsed` (matched a `known-sources.json` entry in the description), or `unknown_source` (neither).

### `set` — tag a matter's source (writes a custom field — always preview first)

```bash
node .claude/skills/clio-referral-tracker/scripts/referral-tracker.js set <matter> <source>
```

`<matter>` here must be the Clio display number (a single token) — everything after it on the command line is treated as the source, so a multi-word source (e.g. `Attorney Referral`) doesn't need quoting. If you only have a client name or description to go on, resolve it to a display number with `show` first.

Without `--commit`, this only prints a preview (matter, field, current value, new value) and writes nothing. Show that preview to the user and get explicit confirmation before re-running with `--commit`:

```bash
node .claude/skills/clio-referral-tracker/scripts/referral-tracker.js set <matter> <source> --commit
```

Never chain the preview and `--commit` runs together in one turn without the user having seen the preview in between.

### `report` — firm-wide ranked breakdown

```bash
node .claude/skills/clio-referral-tracker/scripts/referral-tracker.js report --status=open
```

`--status` is `open` (default) or `all`. Returns:

- `matters_scanned` — total matters considered.
- `sources` — `[{ source, count }]`, ranked descending. Source names are normalized to Title Case for grouping, which can merge distinct sources or split one source into variants — that's why `possible_duplicates` exists.
- `unknown_source` — count of matters with neither an explicit tag nor a parseable description match. This is the real gap in tracking, not a "no referral" count — always call it out by name and size.
- `possible_duplicates` — pairs of source names whose normalized forms are prefixes of each other (e.g. `Joyous` / `Joyous Referrals`). Eyeball these before presenting the report as clean data; ask the user whether to consolidate.

## Behavior this skill must preserve

- Never invent or assume a source. Explicit custom-field tag beats a parsed guess; anything with neither goes to `unknown_source`, full stop.
- `set` always previews before writing, every time — no standing approval across turns.
- This skill only touches the referral-source custom field. It does not open matters, calendar deadlines, or touch treatment/lien/coverage/negotiation data — that's other agents' territory.
