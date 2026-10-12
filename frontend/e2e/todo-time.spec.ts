import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

test('待办日期、滚轮时分、确认取消及北京时间回填', async ({ page }) => {
  page.setDefaultTimeout(15000);
  // Allows UI regression without changing credentials in an existing demo database.
  if (process.env.E2E_MOCK_API) {
    let loggedIn = false;
    let todo: any;
    const user = { id: 'time-picker-student', name: '测试学生', role: 'student' };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
      const method = route.request().method();
      if (path === '/auth/me') return route.fulfill({ status: loggedIn ? 200 : 401, json: loggedIn ? user : { message: '请登录' } });
      if (path === '/auth/login') { loggedIn = true; return route.fulfill({ json: user }); }
      if (path === '/todos' && method === 'POST') {
        todo = { ...route.request().postDataJSON(), id: 'time-picker-todo' };
        return route.fulfill({ status: 201, json: todo });
      }
      if (path === '/todos/' + todo?.id && method === 'PUT') {
        todo = { ...todo, ...route.request().postDataJSON() };
        return route.fulfill({ json: todo });
      }
      if (path === '/todos') return route.fulfill({ json: { items: todo ? [todo] : [], total: todo ? 1 : 0 } });
      return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
    });
  }
  await page.goto('/');
  await page.getByRole('radio', { name: '学生登录', exact: true }).click();
  await page.getByLabel('账号邮箱').fill('student@example.test');
  await page.getByLabel('密码', { exact: true }).fill(process.env.DEMO_STUDENT_PASSWORD || 'test-password');
  await page.getByRole('button', { name: '登录学生服务台', exact: true }).click();
  await page.getByRole('menuitem', { name: '个人待办', exact: true }).click();
  await page.getByRole('button', { name: '新建待办', exact: true }).click();
  const title = `E2E 分段时间 ${Date.now()}`;
  await page.getByLabel('待办标题', { exact: true }).fill(title);
  const fill = async (label: string, parts: string[]) => {
    for (const [i, unit] of ['年', '月', '日', '时', '分'].entries()) await page.getByRole('textbox', { name: label + unit, exact: true }).fill(parts[i]);
  };
  let id: string | undefined;
  try {
    await fill('截止时间', ['2030', '2', '30', '10', '30']);
    await page.getByRole('button', { name: '保存待办', exact: true }).click();
    await expect(page.getByText('请输入有效日期和时间（时：0–23，分：0–59）。', { exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: '截止时间日', exact: true }).fill('');
    await page.getByRole('button', { name: '保存待办', exact: true }).click();
    await expect(page.getByText('请完整填写年、月、日、时、分，或清空时间。', { exact: true })).toBeVisible();
    await fill('截止时间', ['2030', '12', '1', '10', '30']);
    await page.getByRole('button', { name: '选择截止时间', exact: true }).click();
    const picker = page.getByRole('dialog', { name: '选择截止时间（北京时间）', exact: true });
    await expect(picker.getByRole('combobox')).toHaveCount(0);
    await expect(picker.getByRole('textbox')).toHaveCount(0);
    await page.getByRole('button', { name: '下个月', exact: true }).click();
    await expect(picker.getByText('2031年1月', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '上个月', exact: true }).click();
    await page.locator('td[title="2030-12-02"]').click();
    await page.getByRole('listbox', { name: '选择截止时间时', exact: true }).getByRole('option', { name: '11', exact: true }).click();
    await page.getByRole('button', { name: '取消选择', exact: true }).click();
    await expect(page.getByRole('textbox', { name: '截止时间日', exact: true })).toHaveValue('1');
    await page.getByRole('button', { name: '选择截止时间', exact: true }).click();
    await page.locator('td[title="2030-12-03"]').click();
    const hours = page.getByRole('listbox', { name: '选择截止时间时', exact: true });
    const minutes = page.getByRole('listbox', { name: '选择截止时间分', exact: true });
    await expect.poll(() => hours.evaluate(el => el.scrollTop)).toBe(400);
    await expect(hours.getByRole('option', { name: '10', exact: true })).toHaveAttribute('aria-selected', 'true');
    await hours.hover();
    await page.mouse.wheel(0, 80);
    await expect(hours.getByRole('option', { selected: true })).not.toHaveText('10');
    await hours.focus();
    await hours.press('Home');
    await expect(hours.getByRole('option', { name: '00', exact: true })).toHaveAttribute('aria-selected', 'true');
    await hours.press('End');
    await expect(hours.getByRole('option', { name: '23', exact: true })).toHaveAttribute('aria-selected', 'true');
    await hours.getByRole('option', { name: '11', exact: true }).click();
    await minutes.getByRole('option', { name: '45', exact: true }).click();
    if (process.env.E2E_SCREENSHOT_DIR) {
      await mkdir(process.env.E2E_SCREENSHOT_DIR, { recursive: true });
      await expect(picker).toHaveCSS('transform', 'none');
      await expect(picker.getByRole('button', { name: '确认时间', exact: true })).toBeInViewport();
      await page.screenshot({ path: join(process.env.E2E_SCREENSHOT_DIR, 'todo-calendar-confirm.png'), animations: 'disabled' });
    }
    await page.getByRole('button', { name: '确认时间', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '选择截止时间（北京时间）', exact: true })).not.toBeVisible();
    await expect(page.getByRole('textbox', { name: '截止时间日', exact: true })).toHaveValue('03');
    await fill('提醒时间', ['2030', '12', '3', '10', '0']);
    const saved = page.waitForResponse(r => r.url().endsWith('/todos') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '保存待办', exact: true }).click();
    const response = await saved; expect(response.status()).toBe(201);
    const todo = await response.json(); id = todo.id;
    expect(new Date(todo.due_at).toISOString()).toBe('2030-12-03T03:45:00.000Z');
    expect(new Date(todo.remind_at).toISOString()).toBe('2030-12-03T02:00:00.000Z');
    await page.locator('.ant-list-item').filter({ hasText: title }).getByRole('button', { name: /^编\s*辑$/ }).click();
    await expect(page.getByRole('textbox', { name: '截止时间时', exact: true })).toHaveValue('11');
    await page.getByRole('button', { name: '清空提醒时间', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    const dialog = page.getByRole('dialog', { name: '编辑个人待办', exact: true });
    await expect(dialog).toBeVisible();
    for (const unit of ['年', '月', '日', '时', '分']) await expect(page.getByRole('textbox', { name: '截止时间' + unit, exact: true })).toBeInViewport();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.getByRole('button', { name: '选择截止时间', exact: true }).click();
    await expect(hours).toBeInViewport();
    await expect(minutes).toBeInViewport();
    expect(await picker.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await expect(picker).toHaveCSS('transform', 'none');
    await expect.poll(() => hours.evaluate(el => el.scrollTop)).toBe(440);
    await expect.poll(() => minutes.evaluate(el => el.scrollTop)).toBe(1800);
    await expect(hours.getByRole('option', { name: '11', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(minutes.getByRole('option', { name: '45', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(picker.getByRole('button', { name: '确认时间', exact: true })).toBeInViewport();
    if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.E2E_SCREENSHOT_DIR, 'todo-time-mobile.png'), animations: 'disabled' });
    await page.getByRole('button', { name: '取消选择', exact: true }).click();
    const updated = page.waitForResponse(r => r.url().endsWith('/todos/' + id) && r.request().method() === 'PUT');
    await page.getByRole('button', { name: '保存待办', exact: true }).click();
    const result = await updated; expect(result.status()).toBe(200); expect((await result.json()).remind_at).toBeNull();
  } finally {
    if (id && !process.env.E2E_MOCK_API) expect((await page.request.delete('/api/v1/todos/' + id)).status()).toBe(200);
  }
});
