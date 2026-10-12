import { test, expect } from '@playwright/test';

for (const narrow of [false, true]) test(`最近会话和历史记录可分别清空${narrow ? '（窄屏）' : ''}`, async ({ page }) => {
  if (narrow) await page.setViewportSize({ width: 414, height: 896 });
  const conversation = { id: 'history-chat', title: '校园网如何连接？', mode: 'bot', created_at: '2026-10-12T04:00:00Z' };
  let recent = [conversation], history = [conversation], deletes = 0;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/conversations') {
      if (route.request().method() === 'DELETE') {
        deletes++;
        recent = [];
        if (url.searchParams.get('history') === 'true') history = [];
        return route.fulfill({ json: { cleared: 1 } });
      }
      const items = url.searchParams.get('history') === 'true' ? history : recent;
      return route.fulfill({ json: { items, total: items.length } });
    }
    if (path === '/conversations/history-chat') return route.fulfill({ json: { ...conversation, messages: [
      { id: 'q', role: 'user', content: conversation.title, created_at: conversation.created_at, status: 'complete', citations: [] },
      { id: 'a', role: 'assistant', content: '连接校园网后使用统一认证账号登录。', created_at: conversation.created_at,
        status: 'complete', model_mode: 'mock', answer_kind: 'general', citations: [] },
    ] } });
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.locator('.conversation-item').filter({ hasText: conversation.title }).click();
  await expect(page.getByText('连接校园网后使用统一认证账号登录。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '清空最近会话', exact: true }).click();
  await page.locator('.ant-popconfirm').getByRole('button', { name: /取\s*消/ }).click();
  expect(deletes).toBe(0);
  await page.getByRole('button', { name: '清空最近会话', exact: true }).click();
  await page.locator('.ant-popconfirm').getByRole('button', { name: /^清\s*空$/ }).click();
  await expect(page.getByText('暂无最近会话', { exact: true })).toBeVisible();
  await expect(page.getByText('连接校园网后使用统一认证账号登录。', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button', { name: '清空最近会话', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: /history 历史记录/ }).click();
  const drawer = page.locator('.ant-drawer-open');
  await drawer.getByRole('button', { name: /校园网如何连接/ }).click();
  await expect(page.getByText('连接校园网后使用统一认证账号登录。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /history 历史记录/ }).click();
  await drawer.getByRole('button', { name: /清空历史记录/ }).click();
  await page.locator('.ant-popconfirm').getByRole('button', { name: /^清\s*空$/ }).click();
  await expect(drawer.getByText('暂无历史记录', { exact: true })).toBeVisible();
  await expect(drawer.getByRole('button', { name: /清空历史记录/ })).toBeDisabled();
  expect(deletes).toBe(2);
  await page.reload();
  await page.getByRole('button', { name: /history 历史记录/ }).click();
  await expect(page.locator('.ant-drawer-open').getByText('暂无历史记录', { exact: true })).toBeVisible();
});
