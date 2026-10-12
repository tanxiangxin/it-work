import { test, expect } from '@playwright/test';

test('来源默认收起，学习记录按分类仅展示标题，点击查看详情', async ({ page }) => {
  page.setDefaultTimeout(15000);
  const user = { id: 'web-study-student', name: '测试学生', role: 'student' };
  const base = { created_at: new Date().toISOString(), model_mode: 'real', answerable: true, citations: [], exercises: [], web_sources: [] };
  const runs: any[] = [
    { ...base, id: 'outline-run', kind: 'outline', question: '事务复习摘要', content: '摘要完整内容', answer_kind: 'knowledge' },
    { ...base, id: 'practice-run', kind: 'practice', question: '事务练习标题', content: '练习完整内容', answer_kind: 'knowledge' },
  ];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: user });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'web-course', name: '数据库原理' }], total: 1 } });
    if (path === '/courses/web-course/study' && route.request().method() === 'POST') {
      const run = { ...base, id: 'web-run', kind: 'question', question: '量子纠缠是什么？', content: '这是联网检索后的参考答案。', answer_kind: 'web', web_sources: [{ title: '权威物理学网页', url: 'https://example.org/physics' }] };
      runs.unshift(run);
      return route.fulfill({ status: 201, json: run });
    }
    if (path === '/courses/web-course/study') {
      const items = runs.filter(run => run.kind === url.searchParams.get('kind'));
      return route.fulfill({ json: { items, total: items.length } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await expect(page.getByRole('button', { name: '搜索课程资料', exact: true })).toBeEnabled();
  await page.getByLabel('学习问题或主题').fill('量子纠缠是什么？');
  await page.getByRole('button', { name: '根据资料回答', exact: true }).click();
  await expect(page.getByText('本回答来自联网搜索，仅供参考', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('link', { name: '权威物理学网页' })).toHaveCount(0);
  await page.getByRole('button', { name: '展开网页来源（1）', exact: true }).click();
  await expect(page.getByRole('link', { name: '权威物理学网页' })).toHaveAttribute('href', 'https://example.org/physics');
  await page.getByRole('button', { name: '收起网页来源（1）', exact: true }).click();
  await page.getByRole('button', { name: '量子纠缠是什么？', exact: true }).click();
  const detail = page.getByRole('dialog');
  await expect(detail.getByText('这是联网检索后的参考答案。', { exact: true })).toBeVisible();
  await expect(detail.getByRole('link', { name: '权威物理学网页' })).toHaveCount(0);
  await detail.getByRole('button', { name: '展开网页来源（1）', exact: true }).click();
  await expect(detail.getByRole('link', { name: '权威物理学网页' })).toHaveAttribute('rel', 'noopener noreferrer');
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await expect(page.getByText('这是联网检索后的参考答案。', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '量子纠缠是什么？', exact: true })).toBeVisible();
  await page.getByText('摘要', { exact: true }).click();
  await expect(page.getByRole('button', { name: '量子纠缠是什么？', exact: true })).toHaveCount(0);
  await expect(page.getByText('摘要完整内容', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '事务复习摘要', exact: true }).click();
  await expect(detail.getByText('摘要完整内容', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByText('练习题', { exact: true }).last().click();
  await expect(page.getByRole('button', { name: '事务复习摘要', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '事务练习标题', exact: true }).click();
  await expect(detail.getByText('练习完整内容', { exact: true })).toBeVisible();
});
