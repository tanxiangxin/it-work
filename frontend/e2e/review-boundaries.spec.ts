import { test, expect } from '@playwright/test';

test('切换课程后不会展示上一门课程延迟返回的后台结果', async ({ page }) => {
  page.setDefaultTimeout(15000);
  let job: any;
  let received!: () => void;
  let release!: () => void;
  const requested = new Promise<void>(resolve => { received = resolve; });
  const responseReady = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'a', name: '课程A' }, { id: 'b', name: '课程B' }], total: 2 } });
    if (path === '/courses/a/study-jobs') {
      if (route.request().method() === 'POST') job = { id: 'job-a', course_id: 'a', kind: 'outline', status: 'complete', title: 'A提纲' };
      return route.fulfill({ status: route.request().method() === 'POST' ? 202 : 200, json: route.request().method() === 'POST' ? job : { items: job ? [job] : [] } });
    }
    if (path === '/study-jobs/job-a') {
      received(); await responseReady;
      return route.fulfill({ json: { ...job, result: { id: 'run-a', course_id: 'a', kind: 'outline', question: 'A提纲',
        content: '课程A的延迟结果', citations: [], exercises: [], created_at: '2026-10-12T04:00:00Z', model_mode: 'mock' } } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0, job: null } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="学习任务"]').getByText('复习提纲', { exact: true }).click();
  await page.getByRole('button', { name: '生成复习提纲', exact: true }).click();
  await requested;
  await page.locator('.ant-select[aria-label="选择课程"]').click();
  await page.getByTitle('课程B', { exact: true }).click();
  const delivered = page.waitForResponse(response => response.url().endsWith('/study-jobs/job-a'));
  release();
  await (await delivered).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('.ant-select-selection-item').filter({ hasText: '课程B' })).toBeVisible();
  await expect(page.getByText('课程A的延迟结果', { exact: true })).toHaveCount(0);
  await expect(page.locator('.study-reply')).toHaveCount(0);
});

test('损坏的答案草稿不会恢复或使练习页面崩溃', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('campus-draft:v1:student:practice:course:practice',
    JSON.stringify({ savedAt: new Date().toISOString(), values: [42] })));
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: '测试课程' }], total: 1 } });
    if (path === '/courses/course/study') return route.fulfill({ json: { items: [{ id: 'practice', course_id: 'course', kind: 'practice', question: '草稿边界练习', content: '请作答', citations: [], created_at: '2026-10-12T04:00:00Z',
      exercises: [{ kind: 'short_answer', question: '什么是事务？', answer: '参考答案', explanation: '讲解', sources: [] }] }], total: 1 } });
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0, job: null } });
  });
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="学习记录分类"]').getByText('练习题', { exact: true }).click();
  await page.getByRole('button', { name: '草稿边界练习', exact: true }).click();
  await expect(page.getByLabel('第1题答案', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '恢复答案草稿', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
