/**
 * Cloudflare Pages Function — POST /api/contact
 *
 * Validates a contact-form submission, rejects bots via a honeypot field and
 * Cloudflare Turnstile, then forwards the message by email through Resend.
 *
 * Required environment variables (set in the Cloudflare Pages project):
 *   RESEND_API_KEY   — Resend API key
 *   CONTACT_TO       — recipient, e.g. team@6170properties.com
 *   TURNSTILE_SECRET — Cloudflare Turnstile secret key
 * Optional:
 *   CONTACT_FROM     — verified Resend sender
 *                      (default: "6170 Properties <website@6170properties.com>")
 *
 * Responds with JSON ({ ok: true } / { ok: false, error }) when the request
 * Accepts application/json (the site's fetch path), otherwise a minimal HTML
 * page so the form still works with JavaScript disabled.
 */

interface Env {
  RESEND_API_KEY: string;
  CONTACT_TO: string;
  TURNSTILE_SECRET: string;
  CONTACT_FROM?: string;
}

type PagesFn = (ctx: {
  request: Request;
  env: Env;
}) => Promise<Response> | Response;

const FALLBACK_EMAIL = 'team@6170properties.com';

function wantsJson(request: Request): boolean {
  const accept = request.headers.get('accept') || '';
  return accept.includes('application/json');
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function respond(
  request: Request,
  status: number,
  ok: boolean,
  message: string
): Response {
  if (wantsJson(request)) {
    return new Response(JSON.stringify({ ok, error: ok ? undefined : message }), {
      status,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }

  const title = ok ? 'Message sent' : 'Message not sent';
  const body = ok
    ? `<p>Thank you — your message has been sent. We'll be in touch soon.</p>`
    : `<p>${escapeHtml(message)}</p>
       <p>Please email <a href="mailto:${FALLBACK_EMAIL}">${FALLBACK_EMAIL}</a> and we'll help you directly.</p>`;

  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} — 6170 Properties</title>
<style>body{font-family:system-ui,sans-serif;background:#F7F5F0;color:#2B2B2B;
max-width:42rem;margin:0 auto;padding:3rem 1.25rem;line-height:1.6}
h1{color:#1B2A41}a{color:#8f6f3e}</style></head>
<body><h1>${title}</h1>${body}<p><a href="/">Return to the home page</a></p></body></html>`;

  return new Response(html, {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

async function verifyTurnstile(
  secret: string,
  token: string,
  ip: string | null
): Promise<boolean> {
  try {
    const body = new URLSearchParams();
    body.append('secret', secret);
    body.append('response', token);
    if (ip) body.append('remoteip', ip);

    const res = await fetch(
      'https://challenges.cloudflare.com/turnstile/v0/siteverify',
      { method: 'POST', body }
    );
    const data = (await res.json()) as { success?: boolean };
    return data.success === true;
  } catch {
    return false;
  }
}

export const onRequestPost: PagesFn = async ({ request, env }) => {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return respond(request, 400, false, 'We could not read your submission.');
  }

  const get = (k: string) => (form.get(k) ?? '').toString().trim();

  // 1) Honeypot — real people leave this blank.
  if (get('company') !== '') {
    // Pretend success so bots don't learn anything.
    return respond(request, 200, true, '');
  }

  // 2) Required fields (name is always required; one of email/phone must exist).
  const name = get('name');
  const email = get('email');
  const phone = get('phone');
  const message = get('message');

  if (!name) {
    return respond(request, 400, false, 'Please include your name.');
  }
  if (!email && !phone) {
    return respond(
      request,
      400,
      false,
      'Please include a phone number or email so we can reach you.'
    );
  }
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return respond(request, 400, false, 'That email address looks invalid.');
  }

  // 3) Turnstile.
  const token = get('cf-turnstile-response');
  if (!env.TURNSTILE_SECRET) {
    return respond(request, 500, false, 'The form is not fully configured yet.');
  }
  if (!token) {
    return respond(
      request,
      400,
      false,
      'Please complete the "I\'m not a robot" check and try again.'
    );
  }
  const ip = request.headers.get('CF-Connecting-IP');
  const ok = await verifyTurnstile(env.TURNSTILE_SECRET, token, ip);
  if (!ok) {
    return respond(
      request,
      400,
      false,
      'We could not verify that you are human. Please try again.'
    );
  }

  // 4) Build and send the email via Resend.
  if (!env.RESEND_API_KEY || !env.CONTACT_TO) {
    return respond(request, 500, false, 'The form is not fully configured yet.');
  }

  const formName = get('form_name') || 'Website contact';
  const from =
    env.CONTACT_FROM || '6170 Properties <website@6170properties.com>';

  const fields: Array<[string, string]> = [
    ['Name', name],
    ['Email', email],
    ['Phone', phone],
    ['Property address', get('property_address')],
    ['Best time to call', get('best_time')],
    ['Message', message],
  ];
  const lines = fields
    .filter(([, v]) => v)
    .map(([label, v]) => `${label}: ${v}`);
  const text = `New submission from the 6170 Properties website (${formName}).\n\n${lines.join(
    '\n'
  )}`;
  const htmlRows = fields
    .filter(([, v]) => v)
    .map(
      ([label, v]) =>
        `<tr><td style="padding:4px 12px 4px 0;font-weight:600">${escapeHtml(
          label
        )}</td><td style="padding:4px 0">${escapeHtml(v)}</td></tr>`
    )
    .join('');
  const html = `<p>New submission from the 6170 Properties website (${escapeHtml(
    formName
  )}).</p><table>${htmlRows}</table>`;

  const payload: Record<string, unknown> = {
    from,
    to: [env.CONTACT_TO],
    subject: `Website: ${formName} — ${name}`,
    text,
    html,
  };
  if (email) payload.reply_to = email;

  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        authorization: `Bearer ${env.RESEND_API_KEY}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      return respond(
        request,
        502,
        false,
        'We could not send your message right now.'
      );
    }
  } catch {
    return respond(
      request,
      502,
      false,
      'We could not send your message right now.'
    );
  }

  return respond(request, 200, true, '');
};
