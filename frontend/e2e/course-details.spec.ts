import { test, expect } from '@playwright/test';

test('上传资料和AI联网资料都可查看正文详情', async ({ page }) => {
  page.setDefaultTimeout(15000);
  const docs = [
    { id: 'generated', source: 'ai', name: 'AI联网资料-Java基础.md', active_version_id: 'v1', versions: [{ status: 'ready' }] },
    { id: 'uploaded', source: 'uploaded', name: '课程笔记.md', active_version_id: 'v2', versions: [{ status: 'ready' }] },
  ];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'detail-student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: 'Java程序设计' }], total: 1 } });
    if (path === '/courses/course/material-search') return route.fulfill({ json: { job: null } });
    if (path === '/courses/course/documents') {
      const items = docs.filter(doc => doc.source === new URL(route.request().url()).searchParams.get('source'));
      return route.fulfill({ json: { items, total: items.length } });
    }
    const doc = docs.find(doc => path === '/courses/course/documents/' + doc.id);
    if (doc) return route.fulfill({ json: { ...doc, content_format: 'markdown', preview: doc.id === 'generated' ? '# Java基础\n\n> AI 联网整理资料，仅供学习参考。\n\nJava 是一种**编程语言**。\n\n- 访问修饰符：`public`\n- 类与对象\n\n| 类型 | 说明 |\n| --- | --- |\n| 类 | 对象模板 |\n\n```java\npublic class Demo {}\n```\n\n<script>alert("unsafe")</script>\n\n[危险链接](javascript:alert(1))\n\n## 网页来源\n\n- [Java官方资料](https://example.org/java)' : '', chunks: [{ id: doc.id + '-chunk', heading: 'Java基础', content: '我上传的课程笔记：Java类与对象。' }], chunk_total: 1 } });
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="资料来源"]').getByText('AI 搜索资料', { exact: true }).click();
  await page.getByRole('row').filter({ hasText: 'AI联网资料-Java基础.md' }).getByRole('button', { name: '查看详情', exact: true }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText('AI 联网整理', { exact: true })).toBeVisible();
  await expect(drawer.locator('blockquote')).toHaveText('AI 联网整理资料，仅供学习参考。');
  await expect(drawer.locator('strong')).toHaveText('编程语言');
  await expect(drawer.locator('pre code')).toContainText('public class Demo {}');
  await expect(drawer.getByRole('cell', { name: '对象模板' })).toBeVisible();
  await expect(drawer.locator('script')).toHaveCount(0);
  await expect(drawer.getByText('危险链接')).not.toHaveAttribute('href', /javascript:/);
  await expect(drawer.getByRole('link', { name: 'Java官方资料' })).toHaveCount(0);
  await drawer.getByRole('button', { name: '展开网页来源', exact: true }).click();
  await expect(drawer.getByRole('link', { name: 'Java官方资料' })).toHaveAttribute('href', 'https://example.org/java');
  await page.screenshot({ path: 'test-results/course-document-markdown.png' });
  await drawer.getByRole('button', { name: '收起网页来源', exact: true }).click();
  await expect(drawer.getByRole('link', { name: 'Java官方资料' })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.locator('[aria-label="资料来源"]').getByText('上传资料', { exact: true }).click();
  await page.getByRole('button', { name: '课程笔记.md', exact: true }).click();
  await expect(drawer.getByText('上传资料', { exact: true })).toBeVisible();
  await expect(drawer.getByText('我上传的课程笔记：Java类与对象。', { exact: true })).toBeVisible();
});
