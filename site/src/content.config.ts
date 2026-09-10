import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// A single "pages" collection. Each Markdown file supplies the copy for one
// route. Structured bits (hero, blocks) live in frontmatter; flowing prose
// lives in the Markdown body. Edit copy here without touching components.
const pages = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/pages' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    // Optional home-page hero. `ctas` renders as buttons in order; each is
    // styled primary (filled) or secondary (outline).
    hero: z
      .object({
        heading: z.string(),
        statement: z.string(),
        ctas: z.array(
          z.object({
            label: z.string(),
            href: z.string(),
            variant: z.enum(['primary', 'secondary']).default('secondary'),
          })
        ),
      })
      .optional(),
    // Optional set of short content blocks (home page "how we acquire" etc.).
    blocks: z
      .array(z.object({ heading: z.string(), body: z.string() }))
      .optional(),
    // Optional "who we are" teaser with a link.
    whoWeAre: z
      .object({
        heading: z.string(),
        body: z.string(),
        linkLabel: z.string(),
        linkHref: z.string(),
      })
      .optional(),
    // Optional note rendered after a form (e.g. the Treasurer note).
    afterFormNote: z.string().optional(),
  }),
});

// The optional /about team section is loaded directly from Markdown files in
// src/content/team via import.meta.glob (see src/components/Team.astro), so it
// isn't a content collection here — that keeps the build quiet when no team
// files exist.
export const collections = { pages };
