import { test, expect } from '@playwright/test';

for (const failed of [false, true]) test(`十题练习建议一键切换并生成提纲${failed ? '失败时保留输入' : ''}`, async ({ page }) => {
  page.setDefaultTimeout(15000);
  const suggestions = ['加强方法重载与重写的区别，比较参数列表和继承关系。', '复习Java异常分类与finally资源清理。'];
  const run = { id: 'practice', kind: 'practice', question: '十题练习', content: '请作答', created_at: '2026-10-12T04:00:00Z', model_mode: 'real', answer_kind: 'knowledge', citations: [],
    exercises: Array.from({ length: 10 }, (_, i) => ({ kind: 'short_answer', question: `第${i + 1}个Java知识点`, answer: '参考答案', explanation: '讲解', sources: [] })),
    grading: { answers: Array(10).fill('没有区别'), results: Array.from({ length: 10 }, (_, i) => ({ number: i + 1, score: 0, correct: null, feedback: '未覆盖知识点', knowledge_points: ['Java'], criteria: [] })), suggestions, total_score: 0, max_score: 100, model_mode: 'real', scoring_version: 2 } };
  let requests = 0;
  let submission: any;
  let job: any;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: 'Java课程' }], total: 1 } });
    if (path === '/courses/course/study-jobs') {
      if (route.request().method() === 'POST') {
        requests++; submission = route.request().postDataJSON();
        if (failed) return route.fulfill({ status: 503, json: { message: '测试：模型暂时不可用' } });
        job = { id: 'outline-job', course_id: 'course', kind: 'outline', status: 'complete', title: submission.content, result: { ...run, id: 'outline', kind: 'outline', question: submission.content, content: '针对薄弱知识点的复习提纲已生成', exercises: [], grading: {} } };
        return route.fulfill({ status: 202, json: job });
      }
      return route.fulfill({ json: { items: job ? [job] : [] } });
    }
    if (path === '/study-jobs/outline-job') return route.fulfill({ json: job });
    if (path === '/courses/course/study') return route.fulfill({ json: { items: [run], total: 1 } });
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0, job: null } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="学习记录分类"]').getByText('练习题', { exact: true }).click();
  await page.getByRole('button', { name: '十题练习', exact: true }).click();
  const drawer = page.locator('.ant-drawer-open');
  await expect(drawer.locator('.practice-card')).toHaveCount(10);
  await drawer.getByRole('button', { name: '一键生成复习提纲', exact: true }).click();
  await expect(page.getByRole('radio', { name: '复习提纲', exact: true }).first()).toBeChecked();
  await expect(page.getByText('学习记录详情', { exact: true })).not.toBeVisible();
  await expect(page.getByLabel('学习问题或主题', { exact: true })).toHaveValue(/加强方法重载与重写/);
  expect(submission.kind).toBe('outline');
  for (const suggestion of suggestions) expect(submission.content).toContain(suggestion);
  expect(requests).toBe(1);
  if (failed) await expect(page.getByText('测试：模型暂时不可用', { exact: true })).toBeVisible();
  else await expect(page.getByText('针对薄弱知识点的复习提纲已生成', { exact: true })).toBeVisible();
});
