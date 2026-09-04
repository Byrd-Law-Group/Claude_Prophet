// Tiny per-chat state persistence (just the Claude session id to resume),
// so restarting the bot process doesn't lose conversation continuity.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_DIR = path.join(__dirname, 'state');

if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true });

function filePath(chatId) {
  return path.join(STATE_DIR, `${chatId}.json`);
}

export function getState(chatId) {
  const p = filePath(chatId);
  if (!existsSync(p)) return { sessionId: null };
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return { sessionId: null };
  }
}

export function setState(chatId, state) {
  writeFileSync(filePath(chatId), JSON.stringify(state, null, 2));
}

export function clearState(chatId) {
  setState(chatId, { sessionId: null });
}
