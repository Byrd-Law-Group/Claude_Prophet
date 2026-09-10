# Images

These are **placeholder** graphics so the site builds and renders with nothing
broken. Replace them with real photos before (or after) launch.

- Do **not** include any property addresses, parcel numbers, or identifying
  house numbers in images or their filenames.
- Do **not** fetch stock photos without a license.

## Files here

| File | Used on | Suggested real photo | Recommended size |
| --- | --- | --- | --- |
| `dayton-neighborhood-1.svg` | Home | A calm, wide shot of a Dayton-area street or skyline | 1200×800 JPG |
| `renovated-home-1.svg` | (optional) | A tidy, renovated exterior (no house number visible) | 1200×800 JPG |
| `../og-image.png` | Social share card | Branded 1200×630 image | 1200×630 PNG/JPG |

## How to replace a placeholder

1. Drop your real photo into this folder, e.g. `dayton-neighborhood-1.jpg`.
2. In the page/component that uses it (e.g. `src/pages/index.astro`), update the
   `<picture>` / `<img src>` to point at your new file and adjust the `alt` text
   to describe the actual photo.
3. Keep images reasonably sized (compress JPGs to ~150–300 KB) so Lighthouse
   performance stays high.
