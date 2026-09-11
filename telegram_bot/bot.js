import { Bot } from 'node-telegram-bot-api';
import { runClaude, ALLOWED_AGENTS } from './claude.js';
import { getState, setState, clearState } from './state.js';
import { logEvent } from './log.js';
import { queryRecentFaxes, checkForNewFaxes, markFaxesSeen, formatFax, getLastCheckedAt } from './faxes.js';

try {
  process.loadEnvFile(new URL('.env', import.meta.url));
} catch {
  // no telegram_bot/.env yet — env vars must already be set some other way
}

const TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const ALLOWED_USER_ID = process.env.TELEGRAM_ALLOWED_USER_ID
  ? String(process.env.TELEGRAM_ALLOWED_USER_ID)
  : null;
// Default lookback for a manual /faxes check, and the floor used for the
// automatic check below (which pads its own lookback to cover however long
// it's actually been since the last check, so a missed run or a weekend gap
// can't let a fax fall through the cracks).
const FAX_LOOKBACK_HOURS = Number(process.env.FAX_LOOKBACK_HOURS || 48);
// The automatic fax check runs once a day, Mon-Fri, at this local hour
// (24h clock) — e.g. 18 for 6pm.
const FAX_CHECK_HOUR = Number(process.env.FAX_CHECK_HOUR ?? 18);
const FAX_CHECK_WEEKDAYS = new Set([1, 2, 3, 4, 5]); // Mon-Fri (0=Sun..6=Sat)

if (!TOKEN) {
  console.error('Missing TELEGRAM_BOT_TOKEN in telegram_bot/.env. Get one from @BotFather on Telegram.');
  process.exit(1);
}

const bot = new Bot(TOKEN);
// Bare "confirm" is deliberately NOT accepted as a blanket approval — a plan
// with several write/send actions must be confirmed one at a time, by number,
// so one word in Telegram can never authorize a batch of unrelated writes.
const BARE_CONFIRM_RE = /^\s*(confirm|yes|approve|go ahead|do it)\s*[.!]?\s*$/i;
const ITEM_CONFIRM_RE = /^\s*confirm\s+(\d+)\s*[.!]?\s*$/i;
const TELEGRAM_MAX = 4000;

function chunk(text) {
  const parts = [];
  let s = text;
  while (s.length > TELEGRAM_MAX) {
    let cut = s.lastIndexOf('\n', TELEGRAM_MAX);
    if (cut < TELEGRAM_MAX * 0.5) cut = TELEGRAM_MAX;
    parts.push(s.slice(0, cut));
    s = s.slice(cut);
  }
  parts.push(s);
  return parts;
}

async function reply(ctx, text) {
  for (const part of chunk(text)) {
    await ctx.reply(part);
  }
}

// Parses an optional /faxes argument like "30d", "30 days", "720h", or a bare
// number (treated as hours) into an hours count. Returns null for empty
// input (caller should fall back to FAX_LOOKBACK_HOURS) or invalid input.
function parseLookbackArg(arg) {
  const trimmed = (arg || '').trim();
  if (!trimmed) return null;
  const dayMatch = trimmed.match(/^(\d+(?:\.\d+)?)\s*d(?:ays?)?$/i);
  if (dayMatch) return Number(dayMatch[1]) * 24;
  const hourMatch = trimmed.match(/^(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?$/i);
  if (hourMatch) return Number(hourMatch[1]);
  const bareNumber = trimmed.match(/^(\d+(?:\.\d+)?)$/);
  if (bareNumber) return Number(bareNumber[1]);
  return undefined; // signals "couldn't parse this"
}

function formatHour(hour24) {
  const period = hour24 >= 12 ? 'pm' : 'am';
  const hour12 = ((hour24 + 11) % 12) + 1;
  return `${hour12}${period}`;
}

const HELP_TEXT = `Firm assistant bot — talk to it like you would in Claude Code; it routes to the right specialist:
${ALLOWED_AGENTS.map((a) => `• ${a}`).join('\n')}

Safety: every request runs in plan mode first — it can research and draft (Clio notes, letters, status updates) but cannot save or send anything. Every write or send it proposes is numbered. Reply "confirm <number>" (e.g. "confirm 2") to execute just that one item — each item needs its own confirmation, so a batch of drafts is never approved all at once.

Commands:
/new — start a fresh conversation (forgets prior context)
/agents — list available agents
/faxes — check for recently received faxes right now (default lookback ${FAX_LOOKBACK_HOURS}h). Add a lookback to search further back, e.g. "/faxes 30d" or "/faxes 720h"
/pause — put the bot to rest (ignores messages until /resume)
/resume — wake the bot back up
/help — this message

The bot also checks for new incoming faxes on its own every weekday at ${formatHour(FAX_CHECK_HOUR)} and will message you here as soon as one arrives.`;

bot.catch((err, ctx) => {
  console.error('handler error', ctx.update.update_id, err);
});

// Global auth gate: runs before every command/message handler below.
bot.use(async (ctx, next) => {
  const fromId = String(ctx.from?.id ?? '');
  const chatId = ctx.chatId;
  if (!chatId || !fromId) return;

  if (!ALLOWED_USER_ID) {
    await ctx.reply(
      `Bot isn't locked down yet. Set TELEGRAM_ALLOWED_USER_ID=${fromId} in telegram_bot/.env and restart the bot.`
    );
    logEvent({ event: 'setup_needed', fromId, chatId });
    return;
  }

  if (fromId !== ALLOWED_USER_ID) {
    logEvent({ event: 'rejected_unauthorized', fromId, chatId });
    return; // silently ignore anyone who isn't you
  }

  await next();
});

bot.command(['start', 'help'], (ctx) => reply(ctx, HELP_TEXT));
bot.command('agents', (ctx) => reply(ctx, ALLOWED_AGENTS.join('\n')));
bot.command('new', (ctx) => {
  clearState(ctx.chatId);
  return ctx.reply('Started a new conversation.');
});

bot.command('faxes', async (ctx) => {
  const parsed = parseLookbackArg(typeof ctx.match === 'string' ? ctx.match : '');
  if (parsed === undefined) {
    await ctx.reply('Didn\'t understand that lookback. Try "/faxes", "/faxes 30d", or "/faxes 720h".');
    return;
  }
  const hours = parsed ?? FAX_LOOKBACK_HOURS;

  await ctx.api.sendChatAction({ chat_id: ctx.chatId, action: 'typing' });
  try {
    const faxes = await queryRecentFaxes(hours);
    // Whatever this shows the user is now "seen" so the background poll
    // doesn't message them again about the same fax a few minutes later.
    markFaxesSeen(faxes.map((f) => f.id));
    logEvent({ event: 'fax_check_manual', chatId: ctx.chatId, hours, found: faxes.length });
    if (!faxes.length) {
      await ctx.reply(`No faxes received in the last ${hours}h.`);
    } else {
      await reply(ctx, faxes.map(formatFax).join('\n'));
    }
  } catch (err) {
    logEvent({ event: 'fax_check_manual', chatId: ctx.chatId, hours, ok: false, error: err.message });
    await ctx.reply(`Error checking faxes: ${err.message}`);
  }
});

bot.command('pause', (ctx) => {
  const chatId = ctx.chatId;
  setState(chatId, { ...getState(chatId), paused: true });
  logEvent({ event: 'pause', chatId });
  return ctx.reply('Resting — send /resume to wake me back up.');
});

bot.command('resume', (ctx) => {
  const chatId = ctx.chatId;
  setState(chatId, { ...getState(chatId), paused: false });
  logEvent({ event: 'resume', chatId });
  return ctx.reply("I'm back.");
});

bot.on('message', async (ctx) => {
  const text = ctx.message?.text?.trim();
  if (!text || text.startsWith('/')) return;

  const chatId = ctx.chatId;
  const state = getState(chatId);

  if (state.paused) {
    return ctx.reply('Resting — send /resume to wake me back up.');
  }

  const itemMatch = text.match(ITEM_CONFIRM_RE);

  if (BARE_CONFIRM_RE.test(text) && !itemMatch) {
    if (!state.sessionId) {
      await ctx.reply('Nothing pending to confirm.');
      return;
    }
    await ctx.reply(
      'Which item? Each proposed write or send is numbered — reply "confirm <number>" (e.g. "confirm 2") for that one specifically.'
    );
    return;
  }

  const isConfirm = Boolean(itemMatch);

  if (isConfirm && !state.sessionId) {
    await ctx.reply('Nothing pending to confirm.');
    return;
  }

  const permissionMode = isConfirm ? 'bypassPermissions' : 'plan';
  const prompt = isConfirm
    ? `Proceed with ONLY item ${itemMatch[1]} from the plan you most recently proposed — execute exactly that one Clio write or send, nothing else. Every other item you proposed stays staged exactly as before; do not touch them even though you technically have the permissions to. Once item ${itemMatch[1]} is done, report what was done and remind me which items are still pending confirmation.`
    : text;

  await ctx.api.sendChatAction({ chat_id: chatId, action: 'typing' });
  logEvent({ event: 'request', chatId, mode: permissionMode, len: text.length });

  // Telegram's "typing..." indicator expires after ~5s, and these turns can
  // legitimately run many minutes (agent routing + Clio calls). Without a
  // heartbeat the chat just goes silent and looks stuck.
  const heartbeat = setInterval(() => {
    ctx.api.sendChatAction({ chat_id: chatId, action: 'typing' }).catch(() => {});
  }, 4000);

  try {
    const { result, session_id } = await runClaude({
      prompt,
      sessionId: state.sessionId || undefined,
      permissionMode,
    });
    setState(chatId, { sessionId: session_id || state.sessionId });
    logEvent({ event: 'response', chatId, mode: permissionMode, ok: true });
    await reply(ctx, result);
  } catch (err) {
    logEvent({ event: 'response', chatId, mode: permissionMode, ok: false, error: err.message });
    await reply(ctx, `Error: ${err.message}`);
  } finally {
    clearInterval(heartbeat);
  }
});

// Background fax check: fires regardless of /pause, since an incoming fax
// (records, a filing) is a time-sensitive external event, not a chat turn.
// Runs once a day, Mon-Fri, at FAX_CHECK_HOUR local time (not a fixed
// interval) — computed via setTimeout since setInterval can't express "next
// weekday at this hour".
function msUntilNextFaxCheck(now = new Date()) {
  const next = new Date(now);
  next.setHours(FAX_CHECK_HOUR, 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  while (!FAX_CHECK_WEEKDAYS.has(next.getDay())) {
    next.setDate(next.getDate() + 1);
  }
  return next.getTime() - now.getTime();
}

// Pads the lookback to cover however long it's actually been since the last
// check (e.g. the Fri 6pm -> Mon 6pm weekend gap), never below the
// configured floor, with a small margin for clock drift or a delayed run.
function faxCheckLookbackHours() {
  const lastCheckedAt = getLastCheckedAt();
  if (!lastCheckedAt) return FAX_LOOKBACK_HOURS;
  const hoursSince = (Date.now() - new Date(lastCheckedAt).getTime()) / 3600000;
  return Math.max(FAX_LOOKBACK_HOURS, Math.ceil(hoursSince) + 2);
}

function scheduleNextFaxCheck() {
  setTimeout(async () => {
    try {
      const fresh = await checkForNewFaxes(faxCheckLookbackHours());
      for (const fax of fresh) {
        await bot.api.sendMessage({ chat_id: Number(ALLOWED_USER_ID), text: formatFax(fax) });
      }
    } catch (err) {
      logEvent({ event: 'fax_check_auto', ok: false, error: err.message });
    } finally {
      scheduleNextFaxCheck();
    }
  }, msUntilNextFaxCheck());
}

if (ALLOWED_USER_ID) {
  scheduleNextFaxCheck();
} else {
  console.log('Skipping automatic fax checks: TELEGRAM_ALLOWED_USER_ID is not set yet.');
}

console.log('PI practice Telegram bot running (polling)...');
try {
  await bot.startPolling();
} catch (err) {
  console.error(`Bot stopped: ${err.message}`);
  if (err.errorCode === 401) {
    console.error('That looks like an invalid TELEGRAM_BOT_TOKEN — check telegram_bot/.env.');
  }
  process.exit(1);
}
