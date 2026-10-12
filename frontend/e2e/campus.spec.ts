import { test, expect, Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
const docker = process.env.E2E_DOCKER_PATH || (process.platform === 'win32' ? 'C:/Users/WIAN11/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' : 'docker');
const dockerContext = process.env.E2E_DOCKER_CONTEXT || (process.platform === 'win32' ? 'desktop-linux' : '');
function database(code: string) {
  return execFileSync(docker, [...(dockerContext ? ['--context', dockerContext] : []), 'compose', 'exec', '-T', 'api', 'python', '-c', code], { cwd: '..', encoding: 'utf8' }).trim();
}
async function login(page: Page, role: 'student' | 'admin') {
  page.setDefaultTimeout(15000);
  await page.goto('/');
  await page.getByRole('radio', { name: role === 'admin' ? '管理端登录' : '学生登录', exact: true }).click();
  await page.getByLabel('账号邮箱').fill(role + '@example.test');
  await page.getByLabel('密码', { exact: true }).fill(process.env[role === 'admin' ? 'DEMO_ADMIN_PASSWORD' : 'DEMO_STUDENT_PASSWORD'] || 'test-password');
  const baseline = page.waitForResponse(r => r.url().endsWith('/notifications/updates') && r.status() === 200);
  await page.getByRole('button', { name: role === 'admin' ? '登录管理端' : '登录学生服务台', exact: true }).click();
  await baseline;
}
test('校园通知审核发布、订阅消息、确认待办与提醒', async ({ browser }) => {
  test.setTimeout(180000);
  const a = await browser.newContext(), s = await browser.newContext();
  let noticeId: string | undefined; let original: string[] = [];
  try {
    const admin = await a.newPage(), student = await s.newPage();
    await login(admin, 'admin'); await login(student, 'student');
    original = (await (await s.request.get('/api/v1/subscriptions')).json()).categories;
    await student.getByRole('menuitem', { name: '校园通知', exact: true }).click();
    const box = student.getByRole('checkbox', { name: '教学', exact: true });
    if (!await box.isChecked()) {
      const response = student.waitForResponse(r => r.url().endsWith('/subscriptions') && r.request().method() === 'PUT');
      await box.check(); await response;
    }
    await admin.getByRole('menuitem', { name: '校园通知', exact: true }).click();
    await admin.getByRole('button', { name: '新建通知', exact: true }).click();
    await admin.getByLabel('官方通知正文', { exact: true }).fill('E2E 校园通知测试\n此为自动化测试资料，不是学校真实通知。适用对象为测试账号，时间与地点未明确。');
    await admin.getByRole('button', { name: 'AI 提取摘要与办理信息', exact: true }).click();
    await expect(admin.getByText(/请核对提取结果后再发布/)).toBeVisible({ timeout: 90000 });
    await admin.getByLabel('通知标题', { exact: true }).fill('E2E 校园通知测试');
    await admin.getByLabel('湖南工业大学官方原文链接').fill('https://www.hut.edu.cn/');
    const saved = admin.waitForResponse(r => r.url().endsWith('/announcements') && r.request().method() === 'POST');
    await admin.getByRole('button', { name: '保存草稿', exact: true }).click();
    const response = await saved; expect(response.status()).toBe(201); noticeId = (await response.json()).id;
    const row = admin.locator('.ant-list-item').filter({ hasText: 'E2E 校园通知测试' });
    await row.getByRole('button', { name: '确认发布', exact: true }).click();
    await admin.getByRole('button', { name: '发布通知', exact: true }).click();
    const popup = student.locator('.ant-notification-notice').filter({ hasText: '订阅的校园通知已发布' });
    await expect(popup).toBeVisible({ timeout: 15000 });
    await popup.getByRole('button', { name: '查看通知', exact: true }).click();
    await expect(student.getByText('校园通知详情', { exact: true })).toBeVisible();
    await student.getByRole('button', { name: '加入个人待办', exact: true }).click();
    await student.getByLabel('待办标题', { exact: true }).fill('E2E 个人待办提醒');
    const todoResponse = student.waitForResponse(r => r.url().endsWith('/todos') && r.request().method() === 'POST');
    await student.getByRole('button', { name: '保存待办', exact: true }).click();
    const todo = await (await todoResponse).json();
    database(`
import uuid
from datetime import timedelta
from app.db import session
from app import models as m
with session() as db:
    row=db.get(m.Todo, uuid.UUID('${todo.id}'))
    row.remind_at=m.now()-timedelta(seconds=1)
    db.commit()
`);
    // Exercise the actual scheduler implementation without waiting for the next beat tick.
    database('from app.campus_jobs import deliver_reminders; deliver_reminders()');
    const reminder = student.locator('.ant-notification-notice').filter({ hasText: '待办提醒' });
    await expect(reminder).toBeVisible({ timeout: 15000 });
    await reminder.getByRole('button', { name: '查看待办', exact: true }).click();
    await expect(student.getByText('编辑个人待办', { exact: true })).toBeVisible();
    await student.getByRole('checkbox', { name: '已完成', exact: true }).check();
    const completedResponse = student.waitForResponse(r => r.url().endsWith('/todos/' + todo.id) && r.request().method() === 'PUT');
    await student.getByRole('button', { name: '保存待办', exact: true }).click();
    expect((await completedResponse).status()).toBe(200);
    await expect(student.getByText('编辑个人待办', { exact: true })).not.toBeVisible();
    await expect(student.getByText('E2E 个人待办提醒', { exact: true }).first()).toBeVisible();
    if (process.env.E2E_SCREENSHOT_DIR) await student.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/campus-todos.png', fullPage: true });
  } finally {
    await s.request.put('/api/v1/subscriptions', { data: { categories: original } });
    await a.close(); await s.close();
    if (noticeId) database(`
import uuid
from sqlalchemy import select, delete
from app.db import session
from app import models as m
id=uuid.UUID('${noticeId}')
with session() as db:
    todos=select(m.Todo.id).where(m.Todo.announcement_id == id)
    db.execute(delete(m.Notification).where((m.Notification.announcement_id == id) | m.Notification.todo_id.in_(todos)))
    db.execute(delete(m.Todo).where(m.Todo.announcement_id == id))
    db.execute(delete(m.SavedAnnouncement).where(m.SavedAnnouncement.announcement_id == id))
    db.execute(delete(m.Announcement).where(m.Announcement.id == id))
    db.commit()
`);
  }
});

test('个人课程上传、真实资料问答、提纲、练习与引用', async ({ browser }) => {
  test.setTimeout(240000);
  const context = await browser.newContext(); let courseId: string | undefined;
  try {
    const student = await context.newPage(); await login(student, 'student');
    await student.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
    await student.getByRole('button', { name: '新建课程', exact: true }).click();
    await student.getByLabel('课程名称', { exact: true }).fill('E2E 数据库原理');
    const created = student.waitForResponse(r => r.url().endsWith('/courses') && r.request().method() === 'POST');
    await student.getByRole('button', { name: '创建课程', exact: true }).click();
    courseId = (await (await created).json()).id;
    await student.locator('input[type=file]').first().setInputFiles('../samples/study/database-notes.md');
    await expect(student.getByRole('row').filter({ hasText: 'database-notes.md' }).getByText('已发布', { exact: true })).toBeVisible({ timeout: 60000 });
    await student.getByLabel('学习问题或主题', { exact: true }).fill('什么是数据库事务的原子性？');
    await student.getByRole('button', { name: '根据资料回答', exact: true }).click();
    const cited = student.locator('.ant-card').getByRole('button', { name: /database-notes.md/ }).filter({ has: student.locator('.anticon-link') }).first();
    await expect(cited).toBeVisible({ timeout: 90000 });
    await cited.click(); await expect(student.getByText('查看回答依据', { exact: true })).toBeVisible();
    await expect(student.locator('.source-text').last()).toContainText('原子性');
    await student.locator('.ant-drawer-open .ant-drawer-close').click();
    await student.locator('[aria-label="学习任务"]').getByText('复习提纲', { exact: true }).click();
    await expect(student.getByRole('radio', { name: '复习提纲', exact: true })).toBeChecked();
    await student.getByLabel('学习问题或主题', { exact: true }).fill('');
    const outline = student.waitForResponse(r => r.url().endsWith(`/courses/${courseId}/study-jobs`) && r.request().method() === 'POST');
    await student.getByRole('button', { name: '生成复习提纲', exact: true }).click();
    const outlineResponse = await outline; expect(outlineResponse.status()).toBe(202);
    const outlineJob = await outlineResponse.json();
    await expect.poll(async () => (await (await context.request.get(`/api/v1/study-jobs/${outlineJob.id}`)).json()).status,
      { timeout: 60000 }).toBe('complete');
    const outlineResult = await (await context.request.get(`/api/v1/study-jobs/${outlineJob.id}`)).json();
    expect(outlineResult.result.answerable).toBe(true);
    await student.locator('[aria-label="学习任务"]').getByText('练习题', { exact: true }).click();
    await expect(student.locator('[aria-label="学习任务"]').getByRole('radio', { name: '练习题', exact: true })).toBeChecked();
    await student.getByRole('button', { name: '生成练习题', exact: true }).click();
    const reveal = student.getByRole('button', { name: '显示答案', exact: true }).first();
    await expect(reveal).toBeVisible({ timeout: 90000 }); await reveal.click();
    await expect(student.getByText(/参考答案：/).first()).toBeVisible();
    await student.reload(); await student.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
    await expect(student.getByText('学习记录', { exact: true })).toBeVisible();
    await expect(student.getByRole('button', { name: /database-notes.md/ }).first()).toBeVisible();
    if (process.env.E2E_SCREENSHOT_DIR) await student.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/study-assistant.png', fullPage: true });
  } finally {
    await context.close();
    if (courseId) database(`
import uuid
from sqlalchemy import select, delete
from app.db import session
from app.storage import storage
from app import models as m
id=uuid.UUID('${courseId}')
with session() as db:
    jobs=select(m.StudyJob.id).where(m.StudyJob.course_id == id)
    db.execute(delete(m.Notification).where(m.Notification.study_job_id.in_(jobs)))
    db.execute(delete(m.StudyJob).where(m.StudyJob.course_id == id))
    docs=select(m.Document.id).where(m.Document.course_id == id)
    versions=select(m.DocumentVersion.id).where(m.DocumentVersion.document_id.in_(docs))
    keys=list(db.scalars(select(m.DocumentVersion.storage_key).where(m.DocumentVersion.document_id.in_(docs))))
    db.execute(delete(m.StudyRun).where(m.StudyRun.course_id == id))
    db.execute(delete(m.Chunk).where(m.Chunk.version_id.in_(versions)))
    db.execute(delete(m.ImportJob).where(m.ImportJob.version_id.in_(versions)))
    db.execute(delete(m.DocumentVersion).where(m.DocumentVersion.document_id.in_(docs)))
    db.execute(delete(m.Document).where(m.Document.course_id == id))
    db.execute(delete(m.Course).where(m.Course.id == id))
    db.commit()
    for key in keys: storage.remove(key)
`);
  }
});
