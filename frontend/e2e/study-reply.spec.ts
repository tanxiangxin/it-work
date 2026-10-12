import { test, expect } from '@playwright/test';

const markdown = '# Java 方法复习\n\n**重点**：分清重载与重写。\n\n## 核心区别\n\n- 重载：参数列表不同。\n- 重写：子类实现父类方法。\n\n| 概念 | 调用时机 |\n| --- | --- |\n| 重载 | 编译时 |\n| 重写 | 运行时 |\n\n> 先理解概念，再结合代码练习。\n\n```java\nString label = "# **保留代码符号**";\n```\n\n---\n\n[公开参考](https://example.org/java)\n\n<script>alert("unsafe")</script>\n[危险链接](javascript:alert(1))';

for (const narrow of [false, true]) test(`资料回答与历史提纲按阅读排版展示${narrow ? '（窄屏）' : ''}`, async ({ page }) => {
  page.setDefaultTimeout(15000);
  const base = { id: 'answer', kind: 'question', question: '方法有哪些区别？', content: markdown, created_at: '2026-10-12T04:00:00Z', model_mode: 'real', answer_kind: 'knowledge', citations: [], exercises: [] };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: 'Java课程' }], total: 1 } });
    if (path === '/courses/course/study') {
      if (route.request().method() === 'POST') return route.fulfill({ status: 201, json: base });
      return route.fulfill({ json: { items: [{ ...base, id: 'outline', kind: 'outline', question: '历史复习提纲', content: '```markdown\n' + markdown + '\n```' }], total: 1 } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0, job: null } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  if (narrow) await page.setViewportSize({ width: 414, height: 896 });
  await page.getByLabel('学习问题或主题', { exact: true }).fill('方法有哪些区别？');
  await page.getByRole('button', { name: '根据资料回答', exact: true }).click();
  const reply = page.locator('.study-reply').first();
  await expect(reply.getByRole('heading', { name: 'Java 方法复习', exact: true })).toBeVisible();
  await expect(reply.locator('strong')).toHaveText('重点');
  await expect(reply.locator('li')).toHaveCount(2);
  await expect(reply.getByRole('cell', { name: '编译时', exact: true })).toBeVisible();
  await expect(reply.locator('pre code')).toHaveText('String label = "# **保留代码符号**";\n');
  await expect(reply.locator('script')).toHaveCount(0);
  await expect(reply.getByRole('link', { name: '公开参考' })).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(reply.getByText('危险链接')).not.toHaveAttribute('href', /javascript:/);
  const prose = await reply.locator('h1, h2, p, li, th, td').allTextContents();
  expect(prose.join('\n')).not.toContain('**重点**');
  expect(prose.join('\n')).not.toContain('## 核心区别');
  expect(await reply.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  if (!narrow) await reply.screenshot({ path: '../work/study-reply-desktop.png' });
  await page.locator('[aria-label="学习记录分类"]').getByText('摘要', { exact: true }).click();
  await page.getByRole('button', { name: '历史复习提纲', exact: true }).click();
  const drawerReply = page.locator('.ant-drawer-open .study-reply');
  await expect(drawerReply.getByRole('heading', { name: 'Java 方法复习', exact: true })).toBeVisible();
  await expect(drawerReply.locator('pre')).toHaveCount(1);
  await expect(drawerReply.getByRole('cell', { name: '运行时', exact: true })).toBeVisible();
  expect(await drawerReply.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  if (narrow) await drawerReply.screenshot({ path: '../work/study-reply-mobile.png' });
});
