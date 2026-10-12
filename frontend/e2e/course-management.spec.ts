import { test, expect } from '@playwright/test';

test('资料来源切换与删除课程确认、清空页面', async ({ page }) => {
  page.setDefaultTimeout(15000);
  let deleted = false;
  let deleteRequests = 0;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: deleted ? [] : [{ id: 'course', name: '数据库原理' }], total: deleted ? 0 : 1 } });
    if (path === '/courses/course' && route.request().method() === 'DELETE') {
      deleted = true; deleteRequests++;
      return route.fulfill({ json: { ok: true } });
    }
    if (path === '/courses/course/material-search') return route.fulfill({ json: { job: null } });
    if (path === '/courses/course/documents') {
      const ai = url.searchParams.get('source') === 'ai';
      return route.fulfill({ json: { items: [{ id: ai ? 'ai-doc' : 'uploaded-doc', source: ai ? 'ai' : 'uploaded', name: ai ? 'AI联网资料-事务.md' : '我的课堂笔记.md', versions: [{ status: 'ready' }] }], total: 1 } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await expect(page.getByRole('button', { name: '我的课堂笔记.md', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'AI联网资料-事务.md', exact: true })).toHaveCount(0);
  const toggle = page.locator('[aria-label="资料来源"]');
  await toggle.getByText('AI 搜索资料', { exact: true }).click();
  await expect(page.getByRole('button', { name: 'AI联网资料-事务.md', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '我的课堂笔记.md', exact: true })).toHaveCount(0);
  await toggle.getByText('上传资料', { exact: true }).click();
  await expect(page.getByRole('button', { name: '我的课堂笔记.md', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: '学习问题或主题' }).fill('待删除课程的问题');
  const remove = page.locator('.table-toolbar').getByRole('button', { name: '删除课程', exact: true });
  await remove.click();
  await expect(page.getByText('课程中的上传资料、AI 搜索资料和学习记录将一并删除，进行中的资料任务会终止。')).toBeVisible();
  await page.locator('.ant-popconfirm').getByRole('button', { name: /取\s*消/ }).click();
  await expect(page.getByText('确认删除这门课程？', { exact: true })).not.toBeVisible();
  expect(deleteRequests).toBe(0);
  await expect(page.getByRole('button', { name: '我的课堂笔记.md', exact: true })).toBeVisible();
  await remove.click();
  await page.locator('.ant-popconfirm').getByRole('button', { name: '删除课程', exact: true }).click();
  await expect(page.getByText('先创建一门课程，再上传学习资料。')).toBeVisible();
  await expect(remove).toBeDisabled();
  await expect(page.getByRole('textbox', { name: '学习问题或主题' })).toHaveValue('');
  expect(deleteRequests).toBe(1);
});
