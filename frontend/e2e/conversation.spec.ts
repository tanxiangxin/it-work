import {test, expect} from '@playwright/test';

test('普通对话可回复且刷新后保留回复类型', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('账号邮箱').fill('student@example.test');
  await page.getByLabel('密码', {exact: true}).fill(process.env.DEMO_STUDENT_PASSWORD || 'test-password');
  await page.getByRole('button', {name: '登录学生服务台'}).click();
  await expect(page.getByText('校园服务 / 知识问答')).toBeVisible();
  await page.getByRole('button', { name: '新的问题' }).click();
  await page.getByLabel('问题', {exact: true}).fill('你好，你能做什么');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByText('普通回复 · 未查询知识库', {exact: true})).toBeVisible({timeout: 45000});
  await expect(page.getByText('现有资料不足以支持可靠回答。请补充具体情况，或创建工单联系管理员。', {exact: true})).toHaveCount(0);
  await page.reload();
  await page.locator('.conversation-item').filter({hasText: '你好，你能做什么'}).first().click();
  await expect(page.getByText('普通回复 · 未查询知识库', {exact: true})).toBeVisible();
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({path: process.env.E2E_SCREENSHOT_DIR + '/general-conversation.png', fullPage: true});
  }
});
