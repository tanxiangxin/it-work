import { test, expect } from '@playwright/test';

test('旧资料整理预览、等待导入、应用并恢复原资料', async ({ page }) => {
  page.setDefaultTimeout(15000);
  let organization: any = null; let polls = 0;
  const old = ['包.md', '访问修饰符.md'];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); const path = url.pathname.replace('/api/v1', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 'student', name: '测试学生', role: 'student' } });
    if (path === '/courses') return route.fulfill({ json: { items: [{ id: 'course', name: 'Java程序设计' }], total: 1 } });
    if (path === '/courses/course/material-search') return route.fulfill({ json: { job: null } });
    if (path === '/courses/course/material-organization') {
      if (route.request().method() === 'POST') {
        organization = { id: 'organization', status: 'draft', total: 1, ready: 0, failed: 0, groups: [{ title: '类的组织与访问控制', original_names: old, new_document_id: 'new' }] };
        return route.fulfill({ status: 201, json: organization });
      }
      if (organization?.status === 'draft' && ++polls >= 2) organization.ready = 1;
      return route.fulfill({ json: { organization } });
    }
    if (path.endsWith('/organization/apply') || path.endsWith('/organization/rollback')) {
      organization = { ...organization, status: path.endsWith('/apply') ? 'applied' : 'rolled_back' };
      return route.fulfill({ json: organization });
    }
    if (path === '/courses/course/documents') {
      const names = url.searchParams.get('source') !== 'ai' ? [] : organization?.status === 'applied' ? ['AI联网资料-类的组织与访问控制.md'] : old;
      return route.fulfill({ json: { items: names.map((name, i) => ({ id: 'doc' + i, name, source: 'ai', versions: [{ status: 'ready' }] })), total: names.length } });
    }
    return route.fulfill({ json: { items: [], total: 0, unread_count: 0 } });
  });
  await page.goto('/');
  await page.getByRole('menuitem', { name: '学习资料助手', exact: true }).click();
  await page.locator('[aria-label="资料来源"]').getByText('AI 搜索资料', { exact: true }).click();
  const organize = page.getByRole('button', { name: '整理已有 AI 资料', exact: true });
  await expect(organize).toBeEnabled(); await organize.click();
  const modal = page.getByRole('dialog');
  await expect(modal.getByText('包.md、访问修饰符.md')).toBeVisible();
  await expect(modal.getByRole('button', { name: '应用整理方案', exact: true })).toBeDisabled();
  await expect(modal.getByRole('button', { name: '应用整理方案', exact: true })).toBeEnabled();
  await modal.getByRole('button', { name: '应用整理方案', exact: true }).click();
  await expect(page.getByRole('button', { name: 'AI联网资料-类的组织与访问控制.md', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '包.md', exact: true })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/material-organized.png' });
  await page.getByRole('button', { name: '查看已整理资料', exact: true }).click();
  await modal.getByRole('button', { name: '恢复原资料', exact: true }).click();
  await expect(page.getByRole('button', { name: '包.md', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '访问修饰符.md', exact: true })).toBeVisible();
});
