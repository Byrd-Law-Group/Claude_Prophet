// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Canonical production URL. Used for sitemap, canonical tags, and OG URLs.
const SITE = 'https://6170properties.com';

// https://astro.build/config
export default defineConfig({
  site: SITE,
  output: 'static',
  trailingSlash: 'never',
  build: {
    // Emit clean URLs (/about instead of /about/index.html) so paths are stable.
    format: 'file',
  },
  integrations: [sitemap()],
  // No external JS; keep the output lean.
  compressHTML: true,
});
