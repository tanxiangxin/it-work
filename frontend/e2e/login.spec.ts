import {test, expect} from '@playwright/test';

test('学生与管理端入口切换并校验账号角色', async ({page}) => {
  await page.goto('/');
  await expect(page.getByRole('radio', {name: '学生登录', exact: true})).toHaveAttribute('aria-checked', 'true');
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({path: process.env.E2E_SCREENSHOT_DIR + '/student-login.png', fullPage: true});
  }
  await page.getByLabel('密码', {exact: true}).fill('temporary-input');
  await page.getByRole('radio', {name: '学生登录', exact: true}).focus();
  await page.getByRole('radio', {name: '学生登录', exact: true}).press('ArrowRight');
  await expect(page.getByRole('radio', {name: '管理端登录', exact: true})).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByLabel('密码', {exact: true})).toHaveValue('');
  await expect(page.getByLabel('账号邮箱')).toHaveAttribute('placeholder', 'admin@example.test');
  await page.getByLabel('账号邮箱').fill('student@example.test');
  await page.getByLabel('密码', {exact: true}).fill(process.env.DEMO_STUDENT_PASSWORD || 'test-password');
  await page.getByRole('button', {name: '登录管理端', exact: true}).click();
  await expect(page.getByText('当前账号不适用于此入口，请切换至学生登录', {exact: true})).toBeVisible();
  await page.getByRole('radio', {name: '学生登录', exact: true}).click();
  await page.getByLabel('密码', {exact: true}).fill(process.env.DEMO_STUDENT_PASSWORD || 'test-password');
  await page.getByRole('button', {name: '登录学生服务台', exact: true}).click();
  await expect(page.getByRole('menuitem', {name: '我的工单'})).toBeVisible();
  await expect(page.getByRole('menuitem', {name: '知识库管理'})).toHaveCount(0);
});

test('管理员从管理端入口登录', async ({page}) => {
  await page.goto('/');
  await page.getByRole('radio', {name: '管理端登录', exact: true}).click();
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({path: process.env.E2E_SCREENSHOT_DIR + '/admin-login.png', fullPage: true});
  }
  await page.getByLabel('账号邮箱').fill('admin@example.test');
  await page.getByLabel('密码', {exact: true}).fill(process.env.DEMO_ADMIN_PASSWORD || 'test-password');
  await page.getByRole('button', {name: '登录管理端', exact: true}).click();
  await expect(page.getByRole('menuitem', {name: '知识库管理'})).toBeVisible();
  await expect(page.getByRole('menuitem', {name: '工单工作台'})).toBeVisible();
});

test('窄屏登录入口可见且无横向溢出', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/');
  await expect(page.getByRole('radio', {name: '学生登录', exact: true})).toBeVisible();
  await page.getByRole('radio', {name: '管理端登录', exact: true}).click();
  await expect(page.getByRole('button', {name: '登录管理端', exact: true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({path: process.env.E2E_SCREENSHOT_DIR + '/mobile-login.png', fullPage: true});
  }
});
