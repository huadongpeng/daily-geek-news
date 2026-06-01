import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://www.huadongpeng.com',
  integrations: [
    sitemap({
      changefreq: 'daily',
      priority: 0.7,
    }),
  ],
  build: {
    // Generates /blog/foo/index.html → clean URL /blog/foo/
    format: 'directory',
  },
});
