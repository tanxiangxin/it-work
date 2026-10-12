import { test, expect, Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const docker = process.env.E2E_DOCKER_PATH || (process.platform === 'win32' ? 'C:/Users/WIAN11/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' : 'docker');
const dockerContext = process.env.E2E_DOCKER_CONTEXT || (process.platform === 'win32' ? 'desktop-linux' : '');
function database(code: string) {
  return execFileSync(docker, [...(dockerContext ? ['--context', dockerContext] : []), 'compose', 'exec', '-T', 'api', 'python', '-c', code],
    { cwd: '..', encoding: 'utf8' }).trim();
}
async function login(page: Page, role: 'student' | 'admin') {
  await page.goto('/');
  await page.getByRole('radio', { name: role === 'admin' ? '管理端登录' : '学生登录', exact: true }).click();
  await page.getByLabel('账号邮箱').fill(role + '@example.test');
  await page.getByLabel('密码', { exact: true }).fill(process.env[role === 'admin' ? 'DEMO_ADMIN_PASSWORD' : 'DEMO_STUDENT_PASSWORD'] || 'test-password');
  const baseline = page.waitForResponse(r => r.url().endsWith('/notifications/updates') && r.status() === 200);
  await page.getByRole('button', { name: role === 'admin' ? '登录管理端' : '登录学生服务台', exact: true }).click();
  await baseline;
}
test('在线新增工单与回复提醒、离线历史和已读操作', async ({ browser }) => {
  const fixture = JSON.parse(database(`
import json
from sqlalchemy import select
from app.db import session
from app import models as m
with session() as db:
    user = db.scalar(select(m.User).where(m.User.email == 'student@example.test'))
    conv = m.Conversation(user_id=user.id)
    db.add(conv); db.flush()
    draft = m.TicketDraft(user_id=user.id, conversation_id=conv.id, title='消息功能浏览器测试', category='校园网络', description='自动化测试工单')
    db.add(draft); db.commit()
    print(json.dumps({'draft_id':str(draft.id),'conversation_id':str(conv.id)}))
`));
  const a = await browser.newContext(), s = await browser.newContext();
  try {
    const admin = await a.newPage(), student = await s.newPage();
    await login(admin, 'admin'); await login(student, 'student');
    const created = await s.request.post('/api/v1/tickets', { data: { draft_id: fixture.draft_id,
      title: '消息功能浏览器测试', category: '校园网络', description: '自动化测试工单' }, headers: { 'Idempotency-Key': fixture.draft_id } });
    expect(created.status()).toBe(201);
    const ticket = await created.json();
    await expect(admin.locator('.ant-notification-notice').filter({ hasText: '收到新工单' })).toBeVisible({ timeout: 15000 });
    await admin.getByRole('button', { name: '消息中心', exact: true }).click();
    const notice = admin.locator('.system-message').filter({ hasText: '消息功能浏览器测试' });
    await expect(notice).toContainText('未读');
    await notice.getByRole('button', { name: '查看工单' }).click();
    await expect(admin.getByText('工单详情', { exact: true })).toBeVisible();
    expect((await a.request.post(`/api/v1/tickets/${ticket.id}/replies`, { data: { content: '测试回复：请检查网络连接' } })).status()).toBe(201);
    const popup = student.locator('.ant-notification-notice').filter({ hasText: '工单收到新回复' });
    await expect(popup).toBeVisible({ timeout: 15000 });
    await popup.getByRole('button', { name: '查看工单' }).click();
    await expect(student.getByText('测试回复：请检查网络连接', { exact: true })).toBeVisible();
    await student.reload();
    await student.getByRole('button', { name: '消息中心', exact: true }).click();
    await expect(student.locator('.system-message').filter({ hasText: '测试回复：请检查网络连接' })).toBeVisible();
    await expect(student.locator('.ant-notification-notice')).toHaveCount(0);
    expect((await a.request.patch(`/api/v1/tickets/${ticket.id}/status`, { data: { status: 'resolved' } })).status()).toBe(200);
    await expect(student.locator('.system-message').filter({ hasText: '工单状态更新' }).first()).toBeVisible({ timeout: 15000 });
    await student.getByRole('button', { name: '全部标为已读' }).click();
    await expect(student.getByText('0 条未读消息', { exact: true })).toBeVisible();
    if (process.env.E2E_SCREENSHOT_DIR) await student.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/message-center.png', fullPage: true });
  } finally {
    await a.close(); await s.close();
    database(`
import uuid
from sqlalchemy import select, delete
from app.db import session
from app import models as m
draft_id=uuid.UUID('${fixture.draft_id}')
with session() as db:
    ids=select(m.Ticket.id).where(m.Ticket.draft_id == draft_id)
    for table in [m.Notification, m.TicketReply, m.TicketEvent]:
        db.execute(delete(table).where(table.ticket_id.in_(ids)))
    db.execute(delete(m.Ticket).where(m.Ticket.draft_id == draft_id))
    db.execute(delete(m.TicketDraft).where(m.TicketDraft.id == draft_id))
    db.execute(delete(m.Conversation).where(m.Conversation.id == uuid.UUID('${fixture.conversation_id}')))
    db.commit()
`);
  }
});
