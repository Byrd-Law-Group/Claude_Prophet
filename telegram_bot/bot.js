import { Bot } from 'node-telegram-bot-api';
import { runClaude, ALLOWED_AGENTS } from './claude.js';
import { getState, setState, clearState } from './state.js';
import { logEvent } from './log.js';

try {
  process.loadEnvFile(new URL('.env', import.meta.url));
} catch {
  // no telegram_bot/.env yet — env vars must already be set some other way
}

const TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const ALLOWED_USER_ID = process.env.TELEGRAM_ALLOWED_USER_ID
  ? String(process.env.TELEGRAM_ALLOWED_USER_ID)
  : null;

if (!TOKEN) {
  console.error('Missing TELEGRAM_BOT_TOKEN in telegram_bot/.env. Get one from @BotFather on Telegram.');
  process.exit(1);
}

const bot = new Bot(TOKEN);
const CONFIRM_RE = /^\s*(confirm|yes|approve|go ahead|do it)\s*[.!]?\s*$/i;
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

const HELP_TEXT = `Firm assistant bot — talk to it like you would in Claude Code; it routes to the right specialist:
${ALLOWED_AGENTS.map((a) => `• ${a}`).join('\n')}

Safety: every request runs in plan mode first — it can research and draft (Clio notes, letters, status updates) but cannot save or send anything. Reply "confirm" to actually execute the last thing it proposed.

Commands:
/new — start a fresh conversation (forgets prior context)
/agents — list available agents
/pause — put the bot to rest (ignores messages until /resume)
/resume — wake the bot back up
/help — this message`;

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

  const isConfirm = CONFIRM_RE.test(text);

  if (isConfirm && !state.sessionId) {
    await ctx.reply('Nothing pending to confirm.');
    return;
  }

  const permissionMode = isConfirm ? 'bypassPermissions' : 'plan';
  const prompt = isConfirm
    ? 'Proceed. You are approved to execute exactly what you just proposed, including any Clio writes or sends it called for.'
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
