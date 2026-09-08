# Pre-launch checklist

Do these before pointing the domain at the live site.

## 1. Fill in the placeholders

- [ ] Set the **mailing address** — replace `{{MAILING_ADDRESS}}` in
      `src/siteData.ts` (`mailingAddress`).
- [ ] Set the **phone number** — replace `{{PHONE}}` in `src/siteData.ts`
      (`phone`).
- [ ] Confirm the two email addresses in `src/siteData.ts` are correct
      (`acquisitions@` and `notices@`).
- [ ] Update the "Last updated" dates in `src/content/pages/privacy.md` and
      `terms.md` if needed.

## 2. Cloudflare Turnstile

- [ ] Create a Turnstile widget at
      <https://dash.cloudflare.com/?to=/:account/turnstile> for
      `6170properties.com` (and `www`).
- [ ] Put the **site key** (public) in `src/siteData.ts` (`turnstileSiteKey`,
      replacing `{{TURNSTILE_SITE_KEY}}`).
- [ ] Keep the **secret key** for the `TURNSTILE_SECRET` env var (step 4).

## 3. Resend (email delivery)

- [ ] Create a Resend account and **verify the sending domain**
      (`6170properties.com`) at <https://resend.com> — add the DNS records
      Resend provides.
- [ ] Create a **Resend API key** for `RESEND_API_KEY` (step 4).
- [ ] Decide the "from" address (default
      `website@6170properties.com`); it must be on the verified domain.

## 4. Cloudflare Pages environment variables

In **Pages → project → Settings → Variables and Secrets**, add (as secrets
where noted):

- [ ] `RESEND_API_KEY` (secret)
- [ ] `CONTACT_TO` = `acquisitions@6170properties.com`
- [ ] `TURNSTILE_SECRET` (secret)
- [ ] `CONTACT_FROM` (optional) if you don't want the default sender

## 5. Test the form end-to-end

- [ ] Deploy a preview, submit each form (property-owners + contact), and
      confirm the email arrives at `acquisitions@`.
- [ ] Confirm the honeypot works (a filled `company` field is silently
      dropped) and that Turnstile is required.
- [ ] Confirm the on-page success message shows, and that a forced failure
      shows the phone + `acquisitions@` fallback.

## 6. Content review

- [ ] Read every page for accuracy (especially `/property-owners` and the
      Montgomery County Treasurer number **937-225-4010, option 2**).
- [ ] Replace the placeholder images in `public/images/` and `og-image.png`
      with real graphics (no addresses or parcel numbers).

## 7. Point DNS

- [ ] Add `6170properties.com` (apex) and `www.6170properties.com` as custom
      domains on the Pages project.
- [ ] Add a redirect so `www` → apex (301).
- [ ] Confirm HTTPS works on both and that `www` redirects to the apex.

## 8. Final checks

- [ ] Re-run Lighthouse against the live URL (targets: 95+ Performance,
      Accessibility, Best Practices, SEO).
- [ ] Confirm `robots.txt` and `/sitemap-index.xml` load.
- [ ] (Optional) Enable Cloudflare Web Analytics (cookieless).
