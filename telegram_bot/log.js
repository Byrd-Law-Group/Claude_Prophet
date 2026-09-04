// Lightweight audit trail: metadata only (timestamps, chat id, mode, message
// length) — not full message/response text, to avoid piling up client PII in
// a plain log file on disk.
import { appendFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_DIR = path.join(__dirname, 'logs');
const LOG_FILE = path.join(LOG_DIR, 'bot.log');

if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });

export function logEvent(event) {
  const line = JSON.stringify({ ts: new Date().toISOString(), ...event });
  appendFileSync(LOG_FILE, line + '\n');
  console.log(line);
}
