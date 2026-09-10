# 6170 Properties — website

A small, fast, static marketing site for **6170 Properties LLC**, built with
[Astro](https://astro.build/) and plain CSS. No CMS, no UI framework, no
client-side framework. The only third-party script on the site is Cloudflare
Turnstile (spam protection on the contact forms).

- **Purpose:** credibility and contact — for banks, title companies, county
  offices, delinquent property owners, and the occasional buyer or tenant.
- **Deploy target:** Cloudflare Pages (free tier).
- **Contact form:** a Cloudflare Pages Function that validates input, checks a
  honeypot + Turnstile, and emails submissions via Resend.

---

## Local development

```bash
npm install
npm run dev      # http://localhost:4321
```

Other scripts:

```bash
npm run build    # produce the static site in ./dist
npm run preview  # serve ./dist locally
```

> The contact form's serverless function (`functions/api/contact.ts`) does not
> run under `astro dev`. To exercise the form locally, build first and run it
> through Wrangler (see **Testing the form locally** below).

---

## Editing copy

All page copy lives in Markdown under [`src/content/pages/`](src/content/pages):

| File | Page |
| --- | --- |
| `home.md` | `/` |
| `about.md` | `/about` |
| `property-owners.md` | `/property-owners` |
| `contact.md` | `/contact` |
| `privacy.md` | `/privacy` |
| `terms.md` | `/terms` |

- **Structured bits** (the home hero, the three home blocks, the Treasurer note)
  live in each file's **frontmatter** (the block between `---` fences).
- **Flowing prose** lives in the **Markdown body** below the frontmatter.
- Company-wide facts (legal name, address, phone, emails, Turnstile site key)
  live in one place: [`src/siteData.ts`](src/siteData.ts).

You can edit any of this without touching components. After editing, run
`npm run build` (or keep `npm run dev` running) to see the result.

### Placeholders to fill in

Two literal placeholders are intentional and must be replaced before launch:

- `{{MAILING_ADDRESS}}` and `{{PHONE}}` — set both in
  [`src/siteData.ts`](src/siteData.ts). They then appear everywhere
  automatically (footer, contact page, JSON-LD schema).
- `{{TURNSTILE_SITE_KEY}}` — also in `src/siteData.ts` (see **Contact form**).

---

## Adding a team section later

The About page shows a "Our team" section **only if** team files exist —
otherwise it renders nothing.

To add it, drop one Markdown file per person into `src/content/team/`:

```markdown
---
name: Jane Doe
role: Managing Member      # optional
order: 1                   # optional, controls sort order
---

A short bio goes here. It can be a paragraph or two.
```

No code changes needed. Remove the files to hide the section again.

## Adding or replacing photos

Placeholder graphics live in [`public/images/`](public/images) — see
[`public/images/README.md`](public/images/README.md). Replace them with real
photos (JPG/WebP) and update the `<img>`/`<picture>` `src` and `alt` in the
relevant page. **Never** include property addresses or parcel numbers in images
or filenames. The social share image is `public/og-image.png` (1200×630).

---

## Contact form

The form posts to `/api/contact`, handled by
[`functions/api/contact.ts`](functions/api/contact.ts) (a Cloudflare Pages
Function). It:

1. Rejects bots via a hidden **honeypot** field and **Cloudflare Turnstile**.
2. Validates the input.
3. Emails the submission to `CONTACT_TO` via **Resend**.
4. On failure, the page shows the `team@` email and phone as a fallback.

### Required environment variables

Set these in **Cloudflare Pages → your project → Settings → Variables and
Secrets** (mark the keys as secrets). See [`.env.example`](.env.example).

| Variable | Purpose |
| --- | --- |
| `RESEND_API_KEY` | Resend API key used to send the email. |
| `CONTACT_TO` | Recipient, e.g. `team@6170properties.com`. |
| `TURNSTILE_SECRET` | Cloudflare Turnstile **secret** key (server side). |
| `CONTACT_FROM` *(optional)* | Verified Resend sender. Defaults to `6170 Properties <website@6170properties.com>`. |

The Turnstile **site** key (public) is separate and goes in
`src/siteData.ts` (`turnstileSiteKey`).

### Testing the form locally

The function runs under Wrangler, not `astro dev`:

```bash
npm run build
# put real (or test) values in .dev.vars — same keys as .env.example
npx wrangler pages dev dist
```

Turnstile offers test keys that always pass — see
<https://developers.cloudflare.com/turnstile/troubleshooting/testing/>.

---

## Deploy to Cloudflare Pages

Cloudflare has a built-in Astro preset — **no `wrangler.toml` is needed**.

1. Push this repo to GitHub/GitLab.
2. In the Cloudflare dashboard: **Workers & Pages → Create → Pages → Connect to
   Git**, and pick this repository.
3. Set the build configuration:
   - **Framework preset:** Astro
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Root directory:** `site` *(this project lives in the repo's `site/`
     subfolder; set this if the repo root is not the site)*
4. Add the environment variables above.
5. Deploy. Every push to the production branch redeploys.

The functions in `functions/` are picked up automatically by Cloudflare Pages —
`functions/api/contact.ts` becomes `POST /api/contact`.

### DNS — pointing the domain

Point the domain at your Pages project (Cloudflare **Pages → Custom domains**):

- Add **`6170properties.com`** (the apex) as a custom domain. Cloudflare creates
  the necessary `CNAME`/flattened record to `your-project.pages.dev`.
- Add **`www.6170properties.com`** as a custom domain too (`CNAME www →
  your-project.pages.dev`).
- Make **`www` redirect to the apex**: add a Bulk Redirect or a Redirect Rule
  (`www.6170properties.com/*` → `https://6170properties.com/$1`, 301) so there's
  one canonical host. The site's canonical tags already use the apex
  `https://6170properties.com`.

If the domain's nameservers are already on Cloudflare, custom domains resolve
automatically. Otherwise create the `CNAME` records at your DNS provider as
above.

---

## Analytics (optional)

The site ships with **no** tracking. If you want privacy-friendly, cookieless
numbers, enable **Cloudflare Web Analytics** for the domain in the Cloudflare
dashboard (it can be injected automatically at the edge, so no code change is
required).

---

## SEO & performance notes

- Unique `<title>` and meta description per page; Open Graph + Twitter tags.
- `robots.txt` allows all; `sitemap-index.xml` is generated at build.
- JSON-LD `RealEstateAgent` schema on the home page.
- Canonical URLs on `https://6170properties.com`.
- System font stacks (no webfont requests). To self-host **Source Serif 4**
  later, add the font files under `public/fonts/`, add an `@font-face` block in
  `src/styles/global.css`, and put the family first in the `--font-serif` stack.

See [`CHECKLIST.md`](CHECKLIST.md) for the pre-launch to-do list.
