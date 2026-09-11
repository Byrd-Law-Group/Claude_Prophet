// Central place for company-wide facts used across components.
// Fill in the two placeholders before launch (see CHECKLIST.md).
export const site = {
  legalName: '6170 Properties LLC',
  entityLine: 'An Ohio limited liability company',
  // Placeholders — replace with the real values before launch.
  // Until then, `hasMailingAddress` / `hasPhone` below stay false and the
  // components omit these lines entirely, so a raw `{{...}}` never ships.
  mailingAddress: '{{MAILING_ADDRESS}}',
  phone: '{{PHONE}}',
  // Single public contact address for the company.
  email: 'team@6170properties.com',
  areaServed: 'Montgomery County, Ohio',
  url: 'https://6170properties.com',
  // Cloudflare Turnstile site key (public). Replace before launch.
  // The matching secret lives only in the Pages env var TURNSTILE_SECRET.
  turnstileSiteKey: '0x4AAAAAAEvRhwy8elNQJZt2',
} as const;

// Whether the real business details have been filled in. When a value is still
// the `{{...}}` placeholder (or blank) these are false, and every component
// hides the corresponding line instead of rendering the raw token. This keeps
// the live site from ever showing a fake or half-filled phone/address — the
// email remains the always-available contact channel.
const isPlaceholder = (v: string) => v.trim() === '' || /^\{\{.*\}\}$/.test(v);
export const hasMailingAddress = !isPlaceholder(site.mailingAddress);
export const hasPhone = !isPlaceholder(site.phone);

export type NavItem = { label: string; href: string };

export const nav: NavItem[] = [
  { label: 'Home', href: '/' },
  { label: 'About', href: '/about' },
  { label: 'For Property Owners', href: '/property-owners' },
  { label: 'Facing Foreclosure', href: '/foreclosures' },
  { label: 'Contact', href: '/contact' },
];
