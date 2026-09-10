// Central place for company-wide facts used across components.
// Fill in the two placeholders before launch (see CHECKLIST.md).
export const site = {
  legalName: '6170 Properties LLC',
  entityLine: 'An Ohio limited liability company',
  // Placeholders — replace with the real values before launch.
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

export type NavItem = { label: string; href: string };

export const nav: NavItem[] = [
  { label: 'Home', href: '/' },
  { label: 'About', href: '/about' },
  { label: 'For Property Owners', href: '/property-owners' },
  { label: 'Facing Foreclosure', href: '/foreclosures' },
  { label: 'Contact', href: '/contact' },
];
