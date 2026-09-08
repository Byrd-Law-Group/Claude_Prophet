// Spawns the Claude Code CLI headlessly from the project root so it picks up
// .claude/agents (the pi-* subagents) and the clio-toolkit plugin/skills,
// exactly as an interactive Claude Code session in this repo would.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, '..');

// bot.js also calls loadEnvFile, but ES module imports are hoisted and fully
// evaluated before the importing module's own body runs — so by the time
// bot.js's loadEnvFile call executes, this module's top-level env reads
// below would already have happened. Load .env here too so CLAUDE_BIN,
// CLAUDE_PROJECT_DIR, CLAUDE_MODEL, and CLAUDE_TIMEOUT_MS actually see it.
try {
  process.loadEnvFile(new URL('.env', import.meta.url));
} catch {
  // no telegram_bot/.env — env vars must already be set some other way
}

const CLAUDE_BIN = process.env.CLAUDE_BIN || 'claude';
// Resolve relative to telegram_bot/, not the process's cwd, so this works
// the same whether the bot is launched from the repo root or elsewhere.
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR
  ? path.resolve(__dirname, process.env.CLAUDE_PROJECT_DIR)
  : REPO_ROOT;
const MODEL = process.env.CLAUDE_MODEL || undefined;
const TIMEOUT_MS = Number(process.env.CLAUDE_TIMEOUT_MS || 10 * 60 * 1000);

const ALLOWED_AGENTS = [
  'pi-case-manager',
  'pi-prelitigation-paralegal',
  'pi-intake-conflicts',
  'pi-claims-coordinator',
  'pi-litigation-paralegal',
  'pi-drafting-paralegal',
  'pi-medical-records',
  'pi-medical-chronology',
  'pi-damages-analyst',
  'pi-negotiation-specialist',
  'pi-costs-liens-coordinator',
  'pi-subrogation-erisa',
  'pi-client-relations-coordinator',
  'pi-referral-intake-coordinator',
  'pi-legal-research',
  'pi-legal-assistant',
  'pi-practice-manager',
];

const SYSTEM_PROMPT_ADDITION = `You are being operated headlessly through a Telegram bot for a solo attorney managing a Georgia personal-injury caseload. Route requests to the appropriate subagent via the Agent tool, exactly as you would in an interactive session.

Only use these subagents in this context: ${ALLOWED_AGENTS.join(', ')}. Do not invoke ceo-agent, strategy-agent, consultant-agent, engineer-agent, or tax-lien-acquisition-agent — those belong to a different, unrelated project and are out of scope here.

These agents exist to function as the attorney's actual daily staff, not just reporting tools — the goal is that talking to the bot substitutes for having a human in each of these roles. When the attorney refers to staff roles by name, route as follows: "case manager" → pi-case-manager (ongoing caseload health/deadline monitoring); "legal assistant" or "front desk" → pi-legal-assistant (calendar, phone/voicemail, inbox triage — no matter-data writes); "pre-lit paralegal" / "pre-litigation paralegal" → pi-prelitigation-paralegal (actively drives one or more pre-suit files forward day to day, delegating writes to the specialist that owns each ledger); "litigation paralegal" → pi-litigation-paralegal (owns everything from filing forward). When records or bills have just come in for a matter, route to pi-medical-chronology to read them and update the chronology — that's distinct from pi-medical-records, which only requests records and tracks whether they've arrived. Once a chronology is complete, pi-damages-analyst turns it into the demand-ready medical narrative and causation/damages assessment; pi-drafting-paralegal then assembles that into the actual demand letter. Don't skip pi-damages-analyst straight to drafting when someone asks for a "medical summary" or wants to know how strong the medical case is — that analysis is its job, not pi-drafting-paralegal's. For a health-insurance, Medicare, Medicaid, or ERISA plan reimbursement claim against a settlement, route to pi-subrogation-erisa — that is legally distinct from the hospital/provider-lien and hard-cost tracking pi-drafting-paralegal and pi-costs-liens-coordinator handle, and it must be resolved before any disbursement. A vague request like "what do I need to handle today" or "run my morning" should fan out across pi-legal-assistant (calendar/phone/inbox) and pi-prelitigation-paralegal or pi-case-manager (case-side triage) rather than picking just one.

Keep replies concise and readable on a phone: short paragraphs, minimal formatting, no long tables. State plainly which agent(s) handled the request. Never fabricate matter data — if Clio data is unavailable, say so.

This session runs in plan mode: for a purely informational or read-only request, just answer directly in your final message — do not attempt to exit plan mode or treat it as something requiring approval. When a request involves writing to Clio or sending something, do NOT call the ExitPlanMode tool — it does not work in this headless setup and will only report itself as blocked. Instead, write out the concrete plan as plain text in your final message and end the turn there. This applies to every subagent you invoke too: tell them explicitly not to call ExitPlanMode, and to return their proposed writes/sends as plain text for you to fold into your final summary.

There are two Gmail-capable tool sets available: the Google Workspace connector's gws-gmail-send (sends from the attorney's own dbyrd@haveawordwithbyrd.com) and a separate Gmail connector, tool names prefixed mcp__947d5246-03d6-4cad-948c-50e7a6284151__ (send_message, create_draft, reply, forward). Each of these is a single-account connection with no "from" or sender-override parameter of any kind — every send through a given connector's tools goes out as whichever one Google account authorized that connector, always, with nothing to configure. That absence of a from parameter is not a limitation to work around; it means the sender is already fixed by which tool-name prefix you call.

For any outbound client, provider, or carrier email drafted by a pi-* agent, use the 947d5246-... tools, not gws-gmail-send — that connector is authorized as admin@haveawordwithbyrd.com. Before the first send in a session, confirm this is still true by calling that connector's search_threads with query "in:sent" and pageSize 1, and checking the sender field on the returned message equals admin@haveawordwithbyrd.com (connector re-authorization could in principle repoint it at a different account). Once that check passes, calling send_message on those same 947d5246-... tools IS sending as admin@haveawordwithbyrd.com — proceed with the send; do not withhold it while searching for a from/sender field that isn't there.

There is no dedicated fax-sending tool. To send a fax, use RingCentral's email-to-fax gateway through that same 947d5246-... send_message tool: set "to" to the recipient's 10-digit fax number immediately followed by "@rcfax.com" (e.g. 3175554444@rcfax.com — digits only, no dashes, spaces, or leading "1"), attach the document via "attachments" (base64, combined size under 20MB, filenames with no ampersands or other special characters), and put any fax cover-page text in "subject". This only works because admin@haveawordwithbyrd.com is the account's authorized RingCentral email-to-fax sender — never substitute gws-gmail-send for a fax. A fax sent this way is an outbound send like any other and follows the exact same numbering/confirmation rule below: state the destination fax number, the document, and any cover text as one numbered item, and send only after that specific item is confirmed. Note in the plan item that it will go out as a fax, not an email, so the user isn't surprised by the recipient.

Number every distinct write or send action in the plan (1., 2., 3., ...) — one number per Clio write, per outbound email or fax, per calendar/ledger entry, per e-signature request sent via scripts/dropbox_sign.py, each with exactly what would be written or sent and to whom. Never bundle more than one action under a single number. The user confirms items individually by replying "confirm <number>" in Telegram; each confirmation reruns this session authorized for exactly that one numbered item, never the whole plan. When you receive an instruction to proceed with only one specific numbered item, execute only that item — leave every other item exactly as staged, even though nothing stops you at the tool-permission level from touching them. Do not ask the user to just say "confirm" for everything; a plan is only ever approved one numbered item at a time.`;

/**
 * Runs one turn of the Claude CLI.
 * @param {object} opts
 * @param {string} opts.prompt - user message / instruction
 * @param {string} [opts.sessionId] - resume an existing session for conversation continuity
 * @param {'plan'|'bypassPermissions'} opts.permissionMode
 * @returns {Promise<{result: string, session_id: string, raw: object|null}>}
 */
export function runClaude({ prompt, sessionId, permissionMode }) {
  return new Promise((resolve, reject) => {
    const args = ['-p', prompt, '--output-format', 'json', '--permission-mode', permissionMode];
    // ExitPlanMode needs an interactive approval that headless -p mode can
    // never provide — it would just report itself as blocked. Disallow it
    // outright so Claude (and any subagent it routes to) writes the plan out
    // as text instead of getting stuck trying to call it.
    if (permissionMode === 'plan') args.push('--disallowedTools', 'ExitPlanMode');
    if (sessionId) args.push('--resume', sessionId);
    if (MODEL) args.push('--model', MODEL);
    args.push('--append-system-prompt', SYSTEM_PROMPT_ADDITION);

    const child = spawn(CLAUDE_BIN, args, { cwd: PROJECT_DIR, env: process.env });

    let stdout = '';
    let stderr = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill('SIGKILL');
      reject(new Error(`claude timed out after ${TIMEOUT_MS}ms`));
    }, TIMEOUT_MS);

    child.stdout.on('data', (d) => (stdout += d));
    child.stderr.on('data', (d) => (stderr += d));

    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err.code === 'ENOENT') {
        reject(new Error(`Claude CLI not found at "${CLAUDE_BIN}". Install it with: npm install -g @anthropic-ai/claude-code`));
      } else {
        reject(err);
      }
    });

    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      if (!stdout.trim()) {
        return reject(new Error(stderr.trim() || `claude exited with code ${code} and no output`));
      }

      try {
        const lastLine = stdout.trim().split('\n').pop();
        const parsed = JSON.parse(lastLine);
        resolve({
          result: parsed.result ?? '(no result text)',
          session_id: parsed.session_id ?? sessionId,
          raw: parsed,
        });
      } catch {
        // Fell back to non-JSON output — still return something useful.
        resolve({ result: stdout.trim(), session_id: sessionId, raw: null });
      }
    });
  });
}

export { ALLOWED_AGENTS };
