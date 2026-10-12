import { test, expect } from '@playwright/test';

test('课程资料搜索限制10份，后台进度及再次生成', async ({ page }) => {
  page.setDefaultTimeout(15000);
  let batch: any;
  let poll = 0;
  let submitted = 0;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'search-student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'search-course', name: '数据库原理' }], total: 1 } });
    if (path === '/courses/search-course/material-search') {
      if (route.request().method() === 'POST') {
        expect(route.request().postDataJSON()).toEqual({ topic: '事务与并发控制', limit: 10 });
        submitted += 1; poll = 0;
        batch = { id: 'batch-' + submitted, status: 'queued', limit: 10, generated: 0, ready: 0, failed: 0 };
        return route.fulfill({ status: 202, json: batch });
      }
      if (batch) {
        poll += 1;
        batch = { ...batch, status: poll === 1 ? 'generating' : poll === 2 ? 'importing' : 'complete', generated: poll >= 2 ? 10 : 0, ready: poll >= 3 ? 10 : 0 };
      }
      return route.fulfill({ json: { job: batch || null } });
    }
    if (path === '/courses/search-course/documents') {
      const items = batch?.generated ? Array.from({ length: 10 }, (_, i) => ({ id: 'doc-' + i, name: `AI联网资料-事务知识点${i + 1}.md`, active_version_id: 'version-' + i, versions: [{ status: 'ready' }] })) : [];
      return route.fulfill({ json: { items, total: items.length } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  const search = page.getByRole('button', { name: '搜索课程资料', exact: true });
  await expect(search).toBeEnabled();
  await search.click();
  await expect(page.getByRole('spinbutton', { name: '生成资料份数' })).toHaveValue('3');
  await expect(page.getByRole('spinbutton', { name: '生成资料份数' })).toHaveAttribute('aria-valuemax', '10');
  await page.getByRole('spinbutton', { name: '生成资料份数' }).fill('10');
  await page.getByRole('textbox', { name: '搜索资料主题' }).fill('事务与并发控制');
  await page.getByRole('button', { name: '开始搜索并存入', exact: true }).click();
  await expect(search).toBeDisabled();
  await expect(page.getByText('AI 正在联网搜索并整理资料，本次最多 10 份', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await expect(page.getByText('本次已生成并导入 10 份资料，可再次搜索生成更多', { exact: true })).toBeVisible();
  await page.locator('[aria-label="资料来源"]').getByText('AI 搜索资料', { exact: true }).click();
  await expect(page.getByText('AI联网资料-事务知识点1.md', { exact: true })).toBeVisible();
  await expect(search).toBeEnabled();
  await search.click();
  await expect(page.getByRole('button', { name: '开始搜索并存入', exact: true })).toBeVisible();
  expect(submitted).toBe(1);
});
