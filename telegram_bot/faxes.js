// Polls RingCentral (via a headless, read-only Claude CLI call that has the
// RingCentral message-store tools connected) for newly received faxes, logs
// each one, and remembers which fax ids have already been reported so the
// same fax is never announced twice across restarts.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runClaude } from './claude.js';
import { logEvent } from './log.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_DIR = path.join(__dirname, 'state');
const SEEN_FILE = path.join(STATE_DIR, 'fax-check.json');
// Bounds the seen-id ledger so it can't grow forever; comfortably larger than
// any plausible number of faxes between two checks.
const MAX_SEEN = 500;

if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true });

function loadSeen() {
  if (!existsSync(SEEN_FILE)) return [];
  try {
    return JSON.parse(readFileSync(SEEN_FILE, 'utf8')).seenIds ?? [];
  } catch {
    return [];
  }
}

function persistSeen(seenIds) {
  const trimmed = seenIds.slice(-MAX_SEEN);
  writeFileSync(
    SEEN_FILE,
    JSON.stringify({ seenIds: trimmed, lastCheckedAt: new Date().toISOString() }, null, 2)
  );
}

/** Marks fax ids as already reported without logging them (used when a
 * manual /faxes listing already showed them to the user). */
export function markFaxesSeen(ids) {
  if (!ids.length) return;
  persistSeen([...loadSeen(), ...ids]);
}

/** Returns the ISO timestamp of the last recorded check (manual or
 * automatic), or null if none has happened yet. */
export function getLastCheckedAt() {
  if (!existsSync(SEEN_FILE)) return null;
  try {
    return JSON.parse(readFileSync(SEEN_FILE, 'utf8')).lastCheckedAt ?? null;
  } catch {
    return null;
  }
}

const faxQueryPrompt = (hours) =>
  `Read-only task, nothing to confirm or send: call the RingCentral message-store tool to list inbound fax records (messageType "Fax", direction "Inbound") received in the last ${hours} hours. For each record report exactly these fields, one fax per line, pipe-separated, no headers and no extra commentary: id|fromNumber|receivedISO8601|pageCount|readStatus. Do not open, read, or summarize the fax page content itself — metadata only. If there are none, respond with exactly the single word NONE and nothing else. Do not call any write, send, or confirmation tool for this task.`;

function parseFaxLines(text) {
  const trimmed = (text || '').trim();
  if (!trimmed || trimmed === 'NONE') return [];
  return trimmed
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [id, from, receivedAt, pages, readStatus] = line.split('|').map((s) => s?.trim());
      return { id, from, receivedAt, pages, readStatus };
    })
    .filter((f) => f.id);
}

/** Queries RingCentral for inbound faxes in the given lookback window. Does
 * not touch the seen-id ledger. */
export async function queryRecentFaxes(hours) {
  const { result } = await runClaude({ prompt: faxQueryPrompt(hours), permissionMode: 'plan' });
  return parseFaxLines(result);
}

/** Queries recent faxes, logs and returns only the ones not already
 * reported, and records them as seen. */
export async function checkForNewFaxes(hours) {
  const faxes = await queryRecentFaxes(hours);
  const seenIds = loadSeen();
  const seenSet = new Set(seenIds);
  const fresh = faxes.filter((f) => !seenSet.has(f.id));

  for (const fax of fresh) {
    logEvent({ event: 'fax_received', ...fax });
  }
  if (fresh.length) persistSeen([...seenIds, ...fresh.map((f) => f.id)]);

  return fresh;
}

export function formatFax(fax) {
  return `📠 Fax from ${fax.from} — ${fax.receivedAt} — ${fax.pages} page(s) — ${fax.readStatus}`;
}
