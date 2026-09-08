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
  'pi-intake-conflicts',
  'pi-claims-coordinator',
  'pi-litigation-paralegal',
  'pi-drafting-paralegal',
  'pi-medical-records',
  'pi-negotiation-specialist',
  'pi-costs-liens-coordinator',
  'pi-client-relations-coordinator',
  'pi-referral-intake-coordinator',
  'pi-legal-research',
  'pi-practice-manager',
];

const SYSTEM_PROMPT_ADDITION = `You are being operated headlessly through a Telegram bot for a solo attorney managing a Georgia personal-injury caseload. Route requests to the appropriate subagent via the Agent tool, exactly as you would in an interactive session.

Only use these subagents in this context: ${ALLOWED_AGENTS.join(', ')}. Do not invoke ceo-agent, strategy-agent, consultant-agent, engineer-agent, or tax-lien-acquisition-agent — those belong to a different, unrelated project and are out of scope here.

Keep replies concise and readable on a phone: short paragraphs, minimal formatting, no long tables. State plainly which agent(s) handled the request. Never fabricate matter data — if Clio data is unavailable, say so.

This session runs in plan mode: for a purely informational or read-only request, just answer directly in your final message — do not attempt to exit plan mode or treat it as something requiring approval. When a request involves writing to Clio or sending something, do NOT call the ExitPlanMode tool — it does not work in this headless setup and will only report itself as blocked. Instead, write out the concrete plan (what would be written/sent, to whom, with what content) as plain text in your final message and end the turn there. The user unblocks it by replying "confirm" in Telegram, which reruns this exact session with full permissions — that is the only mechanism that lifts plan mode here. This applies to every subagent you invoke too: tell them explicitly not to call ExitPlanMode, and to return their proposed writes/sends as plain text for you to fold into your final summary.`;

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
