import { z, defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    // z.coerce.date() accepts ISO-8601 strings like "2026-06-01T10:30:00+08:00"
    date: z.coerce.date(),
    description: z.string().optional().default(''),
    cover: z.string().optional().default(''),
    categories: z.array(z.string()).optional().default([]),
    tags: z.array(z.string()).optional().default([]),
    draft: z.boolean().optional().default(false),
    sources: z
      .array(
        z.object({
          name: z.string(),
          url: z.string(),
        })
      )
      .optional()
      .default([]),
  }),
});

export const collections = { blog };
