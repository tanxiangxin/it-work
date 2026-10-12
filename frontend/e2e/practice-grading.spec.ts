import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const docker = process.env.E2E_DOCKER_PATH || (process.platform === 'win32' ? 'C:/Users/WIAN11/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' : 'docker');
function database(code: string) {
  return execFileSync(docker, [...(process.platform === 'win32' ? ['--context', 'desktop-linux'] : []), 'compose', 'exec', '-T', 'api', 'python', '-c', code], { cwd: '..', encoding: 'utf8' }).trim();
}

test('练习统一提交、逐题评分、答案开关及刷新后恢复', async ({ page }) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  let courseId: string | undefined;
  let testUser: { id: string; email: string } | undefined;
  let gradeRequests = 0;
  page.on('request', request => { if (request.url().endsWith('/grade-jobs')) gradeRequests++; });
  try {
    testUser = JSON.parse(database(`
import json,uuid
from app.db import session
from app import models as m
from app.security import passwords
with session() as db:
    id=uuid.uuid4()
    user=m.User(id=id,email='e2e-practice-'+id.hex+'@example.test',name='E2E练习验证',role='student',password_hash=passwords.hash('test-password'))
    db.add(user)
    db.commit()
    print(json.dumps(dict(id=str(id),email=user.email)))
`));
    await page.goto('/');
    await page.getByRole('radio', { name: '学生登录', exact: true }).click();
    await page.getByLabel('账号邮箱').fill(testUser!.email);
    await page.getByLabel('密码', { exact: true }).fill('test-password');
    await page.getByRole('button', { name: '登录学生服务台', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: '学习资料助手', exact: true })).toBeVisible();
    const created = await page.request.post('/api/v1/courses', { data: { name: 'E2E 练习评分验证' } });
    expect(created.status()).toBe(201); courseId = (await created.json()).id;
    database(`
import uuid
from app.db import session
from app import models as m
with session() as db:
    course=db.get(m.Course,uuid.UUID('${courseId}'))
    db.add(m.StudyRun(user_id=course.user_id,course_id=course.id,kind='practice',question='E2E事务练习',content='请完成以下练习',citations=[],answerable=True,model_mode='real',exercises=[
        dict(kind='true_false',question='未显式定义构造方法时编译器生成默认构造方法，定义有参构造方法后不再生成默认构造方法。',answer='正确',explanation='编译器仅在未显式定义构造方法时生成默认构造方法。',sources=[]),
        dict(kind='true_false',question='Java类可以extends多个父类。',answer='错误',explanation='Java类只支持单继承。',sources=[]),
        dict(kind='true_false',question='String内容不可变。',answer='正确',explanation='修改操作不改变原实例。',sources=[]),
        dict(kind='short_answer',question='请简述Java中方法重载与方法重写的区别。',answer='重载是同名方法参数列表不同，编译时决定调用；重写是子类重新实现父类同签名实例方法，涉及继承，运行时动态分派。',explanation='区分参数列表、继承关系和调用时机，两者并非没有区别。',sources=[]),
        dict(kind='short_answer',question='简述Java异常分类及finally作用。',answer='Throwable包括Error和Exception，Exception包括受检异常和RuntimeException；finally通常用于清理资源，即使异常也会执行，但进程终止时不保证执行。',explanation='需掌握异常层次、受检与非受检、声明和处理、finally资源清理及不执行的边界。',sources=[])]))
    db.commit()
`);
    await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
    await expect(page.locator('.ant-select-selection-item').filter({ hasText: 'E2E 练习评分验证' })).toBeVisible();
    await page.locator('[aria-label="学习记录分类"]').getByText('练习题', { exact: true }).click();
    await page.getByRole('button', { name: 'E2E事务练习', exact: true }).click();
    const drawer = page.locator('.ant-drawer-open');
    await expect(drawer.getByRole('button', { name: '提交答案', exact: true })).toBeDisabled();
    await expect(drawer.getByText(/参考答案：/)).toHaveCount(0);
    await drawer.getByRole('button', { name: '显示答案', exact: true }).click();
    await expect(drawer.getByText(/参考答案：/)).toHaveCount(5);
    expect(gradeRequests).toBe(0);
    await drawer.getByRole('button', { name: '收起答案', exact: true }).click();
    await drawer.locator('[aria-label="第1题答案"]').getByText('错误', { exact: true }).click();
    await drawer.locator('[aria-label="第2题答案"]').getByText('正确', { exact: true }).click();
    await drawer.locator('[aria-label="第3题答案"]').getByText('错误', { exact: true }).click();
    await drawer.getByLabel('第4题答案').fill('没有区别');
    await drawer.getByLabel('第5题答案').fill('运行时异常');
    const submitted = page.waitForResponse(r => r.url().endsWith('/grade-jobs') && r.request().method() === 'POST', { timeout: 90000 });
    await drawer.getByRole('button', { name: '提交答案', exact: true }).click();
    const response = await submitted; expect(response.status()).toBe(202);
    const job = await response.json();
    await expect.poll(async () => (await (await page.request.get(`/api/v1/study-jobs/${job.id}`)).json()).status,
      { timeout: 90000 }).toBe('complete');
    const grading = (await (await page.request.get(`/api/v1/study-jobs/${job.id}`)).json()).result.grading;
    expect(gradeRequests).toBe(1);
    expect(grading.results[0].correct).toBe(false);
    expect(grading.results[0].score).toBe(0);
    expect(grading.results).toHaveLength(5);
    expect(grading.results[3].score).toBe(0);
    expect(grading.scoring_version).toBe(2);
    if (grading.model_mode === 'real') expect(grading.results[3].criteria.length).toBeGreaterThan(0);
    expect(grading.results[4].score).toBeLessThan(10);
    await expect(drawer.getByText(/本次得分：/)).toBeVisible();
    await expect(drawer.getByText(/作答错误/)).toHaveCount(3);
    await expect(drawer.getByText(/参考答案：/)).toHaveCount(5);
    await expect(drawer.getByText('复习建议', { exact: true })).toBeVisible();
    if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: process.env.E2E_SCREENSHOT_DIR + '/practice-grading.png', fullPage: true });
    await page.reload();
    await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
    await expect(page.locator('.ant-select-selection-item').filter({ hasText: 'E2E 练习评分验证' })).toBeVisible();
    await page.locator('[aria-label="学习记录分类"]').getByText('练习题', { exact: true }).click();
    await page.getByRole('button', { name: 'E2E事务练习', exact: true }).click();
    await expect(page.locator('.ant-drawer-open').getByText(/本次得分：/)).toBeVisible();
    await expect(page.locator('.ant-drawer-open').getByLabel('第4题答案')).toHaveValue('没有区别');
  } finally {
    if (courseId) database(`
import uuid
from sqlalchemy import delete,select
from app.db import session
from app import models as m
with session() as db:
    id=uuid.UUID('${courseId}')
    jobs=select(m.StudyJob.id).where(m.StudyJob.course_id==id)
    db.execute(delete(m.Notification).where(m.Notification.study_job_id.in_(jobs)))
    db.execute(delete(m.StudyJob).where(m.StudyJob.course_id==id))
    db.execute(delete(m.StudyRun).where(m.StudyRun.course_id==id))
    db.execute(delete(m.Course).where(m.Course.id==id))
    db.commit()
`);
    if (testUser) database(`
import uuid
from sqlalchemy import delete,select
from app.db import session
from app import models as m
with session() as db:
    id=uuid.UUID('${testUser.id}')
    for table in reversed(m.Base.metadata.sorted_tables):
        if 'user_id' in table.c:
            db.execute(delete(table).where(table.c.user_id==id))
    db.execute(delete(m.User).where(m.User.id==id))
    db.commit()
`);
  }
});
