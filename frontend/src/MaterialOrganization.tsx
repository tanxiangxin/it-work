import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, List, Modal, Space, Typography } from 'antd';
import { api, post } from './api';

export function MaterialOrganization({ course, disabled, onDocument }: { course: string; disabled: boolean; onDocument: (id: string) => void }) {
  const client = useQueryClient(); const { message } = App.useApp();
  const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false);
  const query = useQuery({ queryKey: ['material-organization', course], queryFn: () => api(`/courses/${course}/material-organization`),
    refetchInterval: q => q.state.data?.organization?.status === 'draft' && q.state.data.organization.ready + q.state.data.organization.failed < q.state.data.organization.total ? 2000 : false });
  const organization = query.data?.organization;
  const act = async (action: 'apply' | 'rollback') => {
    setBusy(true);
    try {
      const updated = await api(`/courses/${course}/material-organization/${organization.id}/${action}`, post({}));
      client.setQueryData(['material-organization', course], { organization: updated });
      await client.invalidateQueries({ queryKey: ['course-documents', course] });
      message.success(action === 'apply' ? '已切换为主题资料，原资料及历史引用已保留' : '已恢复原资料');
      setOpen(false);
    } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  return <>
    <Space wrap style={{ marginBottom: 16, marginLeft: 12 }}>
      <Button disabled={disabled || busy || query.isPending || !!query.error} loading={busy} onClick={async () => {
        if (organization?.status === 'draft' || organization?.status === 'applied') { setOpen(true); return; }
        setBusy(true);
        try {
          const result = await api(`/courses/${course}/material-organization`, post({}));
          client.setQueryData(['material-organization', course], { organization: result }); setOpen(true);
        } catch (e) { message.error((e as Error).message); }
        finally { setBusy(false); }
      }}>{organization?.status === 'draft' ? '查看整理方案' : organization?.status === 'applied' ? '查看已整理资料' : '整理已有 AI 资料'}</Button>
    </Space>
    <Modal title="按主题整理资料" open={open} onCancel={() => setOpen(false)} width={720} footer={<Space>
      <Button onClick={() => setOpen(false)}>关闭</Button>
      {organization?.status === 'draft' && <Button type="primary" loading={busy} disabled={organization.ready !== organization.total || organization.failed > 0} onClick={() => void act('apply')}>应用整理方案</Button>}
      {organization?.status === 'applied' && <Button loading={busy} onClick={() => void act('rollback')}>恢复原资料</Button>}
    </Space>}>
      <Alert showIcon type={organization?.failed ? 'error' : 'info'} message={organization?.status === 'applied' ? '当前展示合并后的主题资料，可恢复原资料' : `新资料导入进度 ${organization?.ready || 0}/${organization?.total || 0}`}
        description="仅按原文组织相关章节，不新增知识。原资料、网页来源和历史引用保留；全部新资料导入成功后才能切换。" />
      <List dataSource={organization?.groups || []} renderItem={(group: any) => <List.Item><div>
        <Button type="link" style={{ padding: 0 }} onClick={() => { setOpen(false); onDocument(group.new_document_id); }}>{group.title}</Button>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>{group.original_names.join('、')}</Typography.Paragraph>
      </div></List.Item>} />
    </Modal>
  </>;
}
