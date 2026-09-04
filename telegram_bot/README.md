# PI Practice Telegram Bot

A single Telegram bot that puts the 12 personal-injury practice agents
(`pi-case-manager`, `pi-intake-conflicts`, `pi-claims-coordinator`,
`pi-litigation-paralegal`, `pi-drafting-paralegal`, `pi-medical-records`,
`pi-negotiation-specialist`, `pi-costs-liens-coordinator`,
`pi-client-relations-coordinator`, `pi-referral-intake-coordinator`,
`pi-legal-research`, `pi-practice-manager`) behind one chat. Message it like
you'd talk to Claude Code in this repo — it routes to the right specialist
agent on its own. Send `/pause` to put it to rest (it ignores messages until
you send `/resume`) — handy for nights/weekends without needing terminal
access to the Mac.

**How it works:** every message runs the Claude Code CLI headlessly
(`claude -p`) from the repo root in `plan` permission mode, so it can freely
research and draft (a Clio note, a demand letter, a status update) but is
structurally unable to save or send anything. Reply **`confirm`** to execute
exactly what it just proposed. `/new` clears the conversation.

## One-time setup

1. **Create the bot.** In Telegram, message [@BotFather](https://t.me/BotFather),
   send `/newbot`, follow the prompts, and copy the token it gives you.

2. **Configure.**
   ```bash
   cp telegram_bot/.env.example telegram_bot/.env
   ```
   Paste the token into `TELEGRAM_BOT_TOKEN`. Leave `TELEGRAM_ALLOWED_USER_ID`
   blank for now.

3. **Log in the Claude CLI.** The bot shells out to a standalone `claude`
   binary, which has its own login separate from any desktop app session.
   It shares your `~/.claude` config directory though, so it already sees
   the `clio-toolkit` plugin and this project's `.claude/agents`.
   ```bash
   claude login
   ```
   Then sanity-check it can see the agents from this repo:
   ```bash
   cd /Users/deandreabyrd/Documents/GitHub/Claude_Prophet
   claude -p "List the pi-* subagents available in this project."
   ```

4. **Start the bot once in the foreground** to grab your Telegram user id:
   ```bash
   npm run telegram-bot
   ```
   Message your bot anything on Telegram. It'll reply telling you your user
   id — paste it into `TELEGRAM_ALLOWED_USER_ID` in `telegram_bot/.env`, then
   restart the bot (Ctrl-C, `npm run telegram-bot` again). From then on it
   ignores every Telegram account except yours.

5. **Try it.** Ask it something read-only first, e.g. *"What's the status of
   the Brown case?"* Then try something that would write, e.g. *"Log a
   $1,200 ER bill on the Smith matter"* — it should come back with a drafted
   note and ask you to confirm before anything is saved.

## Running it in the background (launchd)

To keep it running without a Terminal window open:

```bash
cp telegram_bot/com.haveawordwithbyrd.pi-telegram-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.haveawordwithbyrd.pi-telegram-bot.plist
```

Logs land in `telegram_bot/logs/`. To stop it:

```bash
launchctl unload ~/Library/LaunchAgents/com.haveawordwithbyrd.pi-telegram-bot.plist
```

The plist already points at the `node` and working-directory paths on this
machine — if you ever move the repo or reinstall Node, update the paths
inside it (`which node` / `which claude` to check).

## Example

```
You:  What's the status of the Hines matter?
Bot:  Handled by: pi-case-manager

      Nathan Hines — "Hit by semi in Sandy Springs," status Open.
      Deadlines: SOL 4/12/2027, ante litem notice sent 2/1/2026.
      Treatment: ongoing at Piedmont Ortho, last visit 8/20/2026.
      Bills/liens: $6,400 ER bill (Grady), MedPay lien logged.

You:  Log a $1,200 follow-up bill from Piedmont Ortho on that matter
Bot:  Handled by: pi-case-manager

      Proposed: add a $1,200 Piedmont Ortho bill to the Hines medical
      ledger (dated today, unpaid). Reply "confirm" to save it to Clio.
You:  confirm
Bot:  Saved. Piedmont Ortho — $1,200 added to the Hines cost/medical ledger.
```

Every turn until you reply `confirm` is read-only planning — nothing is
written to Clio until you approve it.

## Notes & limits

- Only responds to the single Telegram account whose id is in
  `TELEGRAM_ALLOWED_USER_ID`. Everyone else is silently ignored (logged as
  `rejected_unauthorized` in `telegram_bot/logs/bot.log`).
- This runs only while your Mac is on, awake, and logged in (launchd
  `LaunchAgent`s don't run at the login screen or while asleep).
- The confirm step uses `--permission-mode bypassPermissions` for that one
  turn — it trusts that whatever the plan-mode turn just described is what
  gets executed. Read the draft before confirming.
- `telegram_bot/logs/bot.log` records timestamps, chat id, and message
  length only — not message or response text — to avoid piling up client
  details in a plain-text file. Full conversation history lives in Claude's
  own session store (resumed via `--resume`), same as any Claude Code
  session.
- Each Telegram chat keeps its own Claude session (`telegram_bot/state/`).
  Use `/new` to start over if a conversation drifts.
