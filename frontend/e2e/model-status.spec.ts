import { test, expect } from '@playwright/test';

test('管理员可查看功能模型、用量并检测服务器模拟状态', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('radio', { name: '管理端登录', exact: true }).click();
  await page.getByLabel('账号邮箱').fill('admin@example.test');
  await page.getByLabel('密码', { exact: true }).fill(process.env.DEMO_ADMIN_PASSWORD || 'test-password');
  await page.getByRole('button', { name: '登录管理端', exact: true }).click();
  await page.getByRole('button', { name: 'AI 配置' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('学习问答、提纲、练习与评分', { exact: true })).toBeVisible();
  await expect(dialog.getByText('资料索引与检索', { exact: true })).toBeVisible();
  await expect(dialog.getByText('我的今日用量（北京时间）', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '检测服务器聊天模型', exact: true }).click();
  await expect(page.getByText('服务器当前为模拟模式，未调用真实模型', { exact: true })).toBeVisible();
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/model-status.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await dialog.boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(390);
  await dialog.getByRole('button', { name: '保存配置', exact: true }).scrollIntoViewIfNeeded();
  await expect(dialog.getByRole('button', { name: '保存配置', exact: true })).toBeInViewport();
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/model-status-mobile.png', fullPage: true });
});
