import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const posts = await getCollection('blog', ({ data }) => !data.draft);
  posts.sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());

  return rss({
    title: 'hdop家 · 老花',
    description: '一个中年小公司技术经理的个人情报雷达：AI工具、副业、出海信号、生活观察。早晚更新。',
    site: context.site,
    items: posts.slice(0, 40).map(post => ({
      title:       post.data.title,
      pubDate:     post.data.date,
      description: post.data.description || '',
      link:        `/blog/${post.id}/`,
    })),
    customData: `<language>zh-cn</language>`,
  });
}
