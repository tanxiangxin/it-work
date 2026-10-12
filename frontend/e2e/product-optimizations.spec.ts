import { test, expect, type Page } from '@playwright/test';

const practice = {
  id: 'practice', kind: 'practice', question: '练习草稿测试', content: '请作答', created_at: '2026-10-12T04:00:00Z',
  model_mode: 'mock', answer_kind: 'knowledge', citations: [], answerable: true, grading: {},
  exercises: [{ kind: 'short_answer', question: '什么是事务？', answer: '原子操作', explanation: '解释', sources: [] }],
};
const outline = { ...practice, id: 'outline', kind: 'outline', question: '后台提纲', content: '后台生成的复习提纲结果', exercises: [] };
type State = { user: string; jobs: any[]; urls: string[]; todo?: any; grade?: any; notifications?: any[] };

async function mock(page: Page, state: State) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); const path = url.pathname.replace('/api/v1', '');
    const method = route.request().method(); state.urls.push(path + url.search);
    if (path === '/auth/me') return route.fulfill({ json: { id: state.user, role: 'admin', name: '测试用户' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: '测试课程' }], total: 1 } });
    if (path === '/courses/course/study') return route.fulfill({ json: { items: [practice], total: 1 } });
    if (path === '/courses/course/study-jobs' && method === 'POST') {
      const body = route.request().postDataJSON();
      const job = { id: 'job', course_id: 'course', kind: body.kind, status: 'queued', title: body.content || '提纲', created_at: '2026-10-12T04:00:00Z' };
      state.jobs = [job]; return route.fulfill({ status: 202, json: job });
    }
    if (path.endsWith('/grade-jobs')) {
      const body = route.request().postDataJSON(); state.grade = body;
      const job = { id: 'grade-job', course_id: 'course', run_id: 'practice', kind: 'grade', status: 'queued', title: '练习评分', created_at: '2026-10-12T04:00:00Z' };
      state.jobs = [job]; return route.fulfill({ status: 202, json: job });
    }
    if (path === '/courses/course/study-jobs') return route.fulfill({ json: { items: state.jobs } });
    if (path.startsWith('/study-jobs/') && path.endsWith('/retry')) {
      const job = { ...state.jobs[0], id: 'retry-job', status: 'queued', error: null };
      state.jobs = [job]; return route.fulfill({ status: 202, json: job });
    }
    if (path.startsWith('/study-jobs/')) return route.fulfill({ json: state.jobs.find(job => path.endsWith(job.id)) });
    if (path === '/todos' && method === 'POST') { state.todo = route.request().postDataJSON(); return route.fulfill({ status: 201, json: { ...state.todo, id: 'todo' } }); }
    if (path === '/notifications/updates') return route.fulfill({ json: { items: [], unread_count: state.notifications?.length || 0, cursor: 0 } });
    if (path === '/notifications') return route.fulfill({ json: { items: state.notifications || [], total: state.notifications?.length || 0 } });
    return route.fulfill({ json: { items: [], total: 0, categories: [], unread_count: 0, job: null } });
  });
}

test('通知搜索日期与待办筛选接入查询，支持重置', async ({ page }) => {
  const state: State = { user: 'search-user', jobs: [], urls: [] }; await mock(page, state);
  await page.goto('/'); await page.getByRole('menuitem', { name: '校园通知', exact: true }).click();
  await page.getByLabel('搜索通知标题').fill('报名'); await page.getByLabel('搜索通知标题').press('Enter');
  await page.getByLabel('发布起始日期', { exact: true }).fill('2030-01-01');
  await page.getByLabel('发布结束日期', { exact: true }).fill('2030-01-03');
  await expect.poll(() => state.urls.some(url => url.includes('published_from=2030-01-01') && url.includes('published_to=2030-01-03') && url.includes('q='))).toBe(true);
  await page.getByRole('button', { name: '重置筛选', exact: true }).click();
  await expect(page.getByLabel('搜索通知标题')).toHaveValue('');
  await expect(page.getByLabel('发布起始日期', { exact: true })).toHaveValue('');
  await page.getByRole('menuitem', { name: '个人待办', exact: true }).click();
  await page.getByLabel('搜索待办标题').fill('交作业'); await page.getByLabel('搜索待办标题').press('Enter');
  await page.getByRole('combobox', { name: '待办到期筛选' }).click();
  await page.getByText('今天到期', { exact: true }).click();
  await expect.poll(() => state.urls.some(url => url.includes('/todos?') && url.includes('due=today') && url.includes('completed=false'))).toBe(true);
});

test('通知与待办草稿刷新可恢复，按账号隔离并在保存后清理', async ({ page }) => {
  const state: State = { user: 'draft-user', jobs: [], urls: [] }; await mock(page, state);
  const openNotice = async () => { await page.getByRole('menuitem', { name: '校园通知', exact: true }).click(); await page.getByRole('button', { name: '新建通知', exact: true }).click(); };
  await page.goto('/'); await openNotice();
  await page.getByLabel('通知标题', { exact: true }).fill('未提交通知');
  await page.getByLabel('官方通知正文', { exact: true }).fill('草稿正文');
  await page.reload(); await openNotice();
  await expect(page.getByText('发现未提交的本地草稿', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '恢复草稿', exact: true }).click();
  await expect(page.getByLabel('通知标题', { exact: true })).toHaveValue('未提交通知');
  state.user = 'other-user'; await page.reload(); await openNotice();
  await expect(page.getByRole('button', { name: '恢复草稿', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('通知标题', { exact: true })).toHaveValue('');
  state.user = 'draft-user'; await page.reload();
  await page.getByRole('menuitem', { name: '个人待办', exact: true }).click(); await page.getByRole('button', { name: '新建待办', exact: true }).click();
  await page.getByLabel('待办标题', { exact: true }).fill('草稿待办');
  await page.getByRole('textbox', { name: '截止时间年', exact: true }).fill('2030');
  await page.reload(); await page.getByRole('menuitem', { name: '个人待办', exact: true }).click(); await page.getByRole('button', { name: '新建待办', exact: true }).click();
  await page.getByRole('button', { name: '恢复草稿', exact: true }).click();
  await expect(page.getByLabel('待办标题', { exact: true })).toHaveValue('草稿待办');
  await expect(page.getByRole('textbox', { name: '截止时间年', exact: true })).toHaveValue('2030');
  await page.getByRole('button', { name: '清空截止时间', exact: true }).click();
  await page.getByRole('button', { name: '保存待办', exact: true }).click();
  await expect.poll(() => state.todo?.title).toBe('草稿待办');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('campus-draft:v1:draft-user:todo:new'))).toBeNull();
});

test('后台提纲刷新保留进度，完成可查看，消息跳转并支持失败重试', async ({ page }) => {
  const state: State = { user: 'job-user', jobs: [], urls: [] }; await mock(page, state);
  await page.goto('/'); await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="学习任务"]').getByText('复习提纲', { exact: true }).click();
  await page.getByRole('button', { name: '生成复习提纲', exact: true }).click();
  await expect(page.getByText('排队中', { exact: true })).toBeVisible();
  await page.getByRole('menuitem', { name: '个人待办', exact: true }).click();
  await page.reload(); await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await expect(page.getByText('排队中', { exact: true })).toBeVisible();
  state.jobs[0] = { ...state.jobs[0], status: 'complete', result: outline };
  await expect(page.getByRole('button', { name: '查看结果', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '查看结果', exact: true }).click();
  await expect(page.getByText('后台生成的复习提纲结果', { exact: true })).toBeVisible();
  state.notifications = [{ id: 'message', sequence: 1, study_job_id: 'job', title: '提纲已完成', content: '查看结果', created_at: '2026-10-12T04:00:00Z', read_at: null }];
  await page.reload(); await page.getByRole('button', { name: '消息中心', exact: true }).click();
  await page.getByRole('button', { name: '查看学习任务', exact: true }).click();
  await expect(page.getByText('后台生成的复习提纲结果', { exact: true })).toBeVisible();
  state.jobs[0] = { ...state.jobs[0], status: 'failed', error: '任务中断，请重试', result: null };
  await page.reload(); await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.getByRole('button', { name: '重试任务', exact: true }).click();
  await expect(page.getByText('排队中', { exact: true })).toBeVisible();
});

test('练习答案草稿恢复，后台评分完成后显示并清理草稿', async ({ page }) => {
  const state: State = { user: 'answer-user', jobs: [], urls: [] }; await mock(page, state);
  const open = async () => { await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click(); await page.locator('[aria-label="学习记录分类"]').getByText('练习题', { exact: true }).click(); await page.getByRole('button', { name: '练习草稿测试', exact: true }).click(); };
  await page.goto('/'); await open(); await page.getByLabel('第1题答案', { exact: true }).fill('我的作答');
  await page.reload(); await open(); await page.getByRole('button', { name: '恢复答案草稿', exact: true }).click();
  await expect(page.getByLabel('第1题答案', { exact: true })).toHaveValue('我的作答');
  await page.getByRole('button', { name: '提交答案', exact: true }).click();
  await expect(page.getByText('评分任务排队中，可以离开页面', { exact: true })).toBeVisible();
  await expect(page.getByLabel('第1题答案', { exact: true })).toBeDisabled();
  expect(state.grade.answers).toEqual(['我的作答']);
  state.jobs[0] = { ...state.jobs[0], status: 'complete', result: { ...practice, grading: { answers: ['我的作答'], results: [{ number: 1, score: 7, feedback: '部分正确', knowledge_points: ['事务'], criteria: [] }], total_score: 7, max_score: 10, suggestions: ['复习事务'], model_mode: 'mock', scoring_version: 2 } } };
  await expect(page.getByText('本次得分：7 / 10', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '恢复答案草稿', exact: true })).toHaveCount(0);
});
