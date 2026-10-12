import { test, expect } from '@playwright/test';

test('AI 配置直接显示自定义模型表单并保留密钥', async ({ page }) => {
  let saved: Record<string, unknown> = { mode: 'default', api_base: '', model: '', api_style: 'openai', has_api_key: false };
  const submitted: Record<string, unknown>[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = { items: [], total: 0, page: 1, page_size: 20, cursor: 0, unread_count: 0 };
    if (path.endsWith('/auth/me')) data = { id: 'test-user', name: '测试用户', role: 'student', email: 'test@example.test' };
    else if (path.endsWith('/system')) data = { model_mode: 'real' };
    else if (path.endsWith('/ai-config/test')) data = { message: '连接成功，模型可正常回复' };
    else if (path.endsWith('/ai-config')) {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON(); submitted.push(body);
        saved = body.mode === 'default' ? { mode: 'default', api_base: '', model: '', api_style: 'openai', has_api_key: false }
          : { ...body, api_key: undefined, has_api_key: !!body.api_key || saved.has_api_key };
      }
      data = saved;
    }
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.locator('.topbar').getByText('真实模型', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'AI 配置' }).click();
  await expect(page.getByText('服务器默认', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('模型来源')).toHaveCount(0);
  await expect(page.getByText('本地模型', { exact: true })).toHaveCount(0);
  await expect(page.getByText('自定义模型', { exact: true })).toBeVisible();
  await page.getByRole('dialog').locator('.ant-select').click();
  await expect(page.locator('.ant-select-item-option')).toHaveCount(2);
  await expect(page.locator('.ant-select-item-option').getByText('OpenAI', { exact: true })).toBeVisible();
  await page.locator('.ant-select-item-option').getByText('Anthropic', { exact: true }).click();
  await expect(page.getByText(/填写基础地址，例如 https:\/\/api.anthropic.com/)).toBeVisible();
  await page.getByLabel('API 地址').fill('https://models.example/v1');
  await page.getByLabel('模型名称').fill('custom-chat');
  await page.getByLabel('API Key').fill('test-secret');
  await page.getByRole('button', { name: '测试连接' }).click();
  await expect(page.getByText('连接成功，模型可正常回复')).toBeVisible();
  expect(submitted).toHaveLength(0);
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/ai-configuration.png', fullPage: true });
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(submitted[0]).toMatchObject({ mode: 'cloud', model: 'custom-chat', api_style: 'anthropic' });
  await page.getByRole('button', { name: 'AI 配置' }).click();
  await expect(page.getByLabel('模型名称')).toHaveValue('custom-chat');
  await page.getByLabel('API 地址').fill('https://models.example/v1');
  await page.getByLabel('API Key').fill('test-secret');
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'AI 配置' }).click();
  await expect(page.getByLabel('API Key')).toHaveValue('');
  await expect(page.getByText('已保存密钥，留空保留；修改接口地址后需重新填写。')).toBeVisible();
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(submitted[2].api_key).toBeUndefined();
});
