import { useState } from 'react';
import { App, Alert, Button, Form, Input, Modal, Select, Space, Spin, Table, Tag, Typography } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { api, post } from './api';

type Configuration = {
  api_base: string; model: string;
  api_style: 'openai' | 'anthropic'; api_key?: string; has_api_key?: boolean;
};
type ModelStatus = { can_test_server?: boolean; features?: { feature: string; source: string; mode: string; model: string; configured: boolean }[] };
type Usage = { enabled: boolean; date: string; daily_used: number | null; daily_limit: number; remaining: number | null; models: { model: string; input_tokens: number; output_tokens: number; unreported_usage: number; estimated_cny: number | null }[]; cost_note: string };

export function AIConfiguration({ onSaved }: { onSaved: () => void }) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<'save' | 'test'>();
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<Configuration>();
  const [status, setStatus] = useState<ModelStatus>();
  const [serverBusy, setServerBusy] = useState(false);
  const [usage, setUsage] = useState<Usage>();
  const [form] = Form.useForm<Configuration>();
  const base = Form.useWatch('api_base', form);
  const apiStyle = Form.useWatch('api_style', form);
  const retainedKey = saved?.has_api_key && saved.api_base.replace(/\/$/, '') === base?.replace(/\/$/, '');
  async function show() {
    setOpen(true); setLoading(true); setError(''); setSaved(undefined); form.resetFields();
    try {
      const [data, models, today] = await Promise.all([api<Configuration>('/ai-config'), api<ModelStatus>('/ai-config/status'), api<Usage>('/usage')]);
      setStatus(models);
      setUsage(today);
      setSaved(data); form.setFieldsValue({ ...data, api_key: undefined });
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  async function testServer(kind: 'chat' | 'embedding') {
    setServerBusy(true); setError('');
    try { const result = await api('/ai-config/server-test', post({ kind })); message.info(result.message); }
    catch (e) { setError((e as Error).message); }
    finally { setServerBusy(false); }
  }
  async function run(action: 'save' | 'test') {
    let values: Configuration;
    try { values = await form.validateFields(); } catch { return; }
    if (retainedKey && !values.api_key?.trim()) values.api_key = undefined;
    const payload = { ...values, mode: 'cloud' };
    setBusy(action); setError('');
    try {
      if (action === 'test') {
        const result = await api('/ai-config/test', post(payload)); message.success(result.message);
      } else {
        await api('/ai-config', { method: 'PUT', body: JSON.stringify(payload) });
        onSaved();
        message.success('AI 配置已保存，将用于后续知识问答和工单摘要'); setOpen(false);
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(undefined); }
  }
  return <><Button icon={<SettingOutlined />} onClick={() => void show()}>AI 配置</Button>
    <Modal title="AI 配置" width={720} style={{ top: 24 }} styles={{ body: { maxHeight: 'calc(100dvh - 150px)', overflowY: 'auto' } }} open={open} onCancel={() => { if (!busy && !serverBusy) setOpen(false); }} footer={null} destroyOnHidden>
      <Spin spinning={loading}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text strong>各功能当前使用的模型</Typography.Text>
          <Table size="small" pagination={false} rowKey="feature" dataSource={status?.features || []} columns={[
            { title: '功能', dataIndex: 'feature' }, { title: '来源', dataIndex: 'source' },
            { title: '模型', dataIndex: 'model', render: (value: string) => value || '未配置' },
            { title: '状态', render: (_, row) => <Tag color={!row.configured ? 'orange' : row.mode === 'mock' ? 'gold' : 'cyan'}>{!row.configured ? '未就绪' : row.mode === 'mock' ? '模拟模式' : '已配置，需检测连接'}</Tag> },
          ]} scroll={{ x: 520 }} />
          {status?.can_test_server && <Space wrap>
            <Button loading={serverBusy} disabled={!!busy || serverBusy} onClick={() => void testServer('chat')}>检测服务器聊天模型</Button>
            <Button disabled={!!busy || serverBusy} onClick={() => void testServer('embedding')}>检测服务器嵌入模型</Button>
          </Space>}
          {typeof usage?.daily_limit === 'number' && <>
            <Typography.Text strong>我的今日用量（北京时间）</Typography.Text>
            <Typography.Text>{usage.enabled ? `已提交 ${usage.daily_used ?? '未知'} / ${usage.daily_limit} 次 AI 请求，剩余 ${usage.remaining ?? '未知'} 次` : '测试环境未开启额度限制'}</Typography.Text>
            <Table size="small" pagination={false} rowKey="model" dataSource={usage.models || []} columns={[
              { title: '模型', dataIndex: 'model' }, { title: '输入 Token', dataIndex: 'input_tokens' },
              { title: '输出 Token', dataIndex: 'output_tokens' },
              { title: '估算费用', render: (_, row) => row.estimated_cny == null ? '未估算' : `¥${row.estimated_cny.toFixed(6)}` },
            ]} scroll={{ x: 520 }} />
            <Typography.Text type="secondary">{usage.cost_note} 调用额度按提交次数计算，失败请求也计入；上传另设限流。</Typography.Text>
          </>}
          <Alert type="info" showIcon message="自定义模型" description="下方个人配置用于知识问答和工单摘要；学习、通知、联网搜索及资料索引使用上表中的服务器配置。模型需支持 JSON 格式回复。连接检测会发送少量测试内容，真实服务可能产生费用。" />
          {error && <Alert type="error" showIcon message={error} />}
          <Form form={form} layout="vertical" disabled={loading || !!busy}>
              <Form.Item name="api_base" label="API 地址" extra={apiStyle === 'anthropic' ? '填写基础地址，例如 https://api.anthropic.com 或以 /v1 结尾的地址，无需添加 /messages。' : '填写基础地址（通常以 /v1 结尾），无需添加 /chat/completions。'} rules={[{ required: true, message: '请输入 API 地址' }, { validator: (_, value) => {
                try { const url = new URL(value); if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error(); return Promise.resolve(); }
                catch { return Promise.reject(new Error('请输入不含账号、密码或查询参数的 HTTP(S) 地址')); }
              } }]}><Input placeholder="https://your-provider.example/v1" maxLength={2048} /></Form.Item>
              <Form.Item name="model" label="模型名称" rules={[{ required: true, whitespace: true, message: '请输入模型名称' }]}><Input placeholder="填写服务提供的模型标识" maxLength={200} /></Form.Item>
              <Form.Item name="api_style" label="接口类型" rules={[{ required: true }]}><Select options={[{ value: 'openai', label: 'OpenAI' }, { value: 'anthropic', label: 'Anthropic' }]} /></Form.Item>
              <Form.Item name="api_key" label="API Key" extra={retainedKey ? '已保存密钥，留空保留；修改接口地址后需重新填写。' : '密钥由后端保存，不在页面回显。'} rules={[{ validator: (_, value) => !value?.trim() && !retainedKey ? Promise.reject(new Error('请输入 API Key')) : Promise.resolve() }]}><Input.Password autoComplete="new-password" placeholder={retainedKey ? '已保存，留空保留' : '请输入 API Key'} maxLength={4096} /></Form.Item>
          </Form>
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button disabled={loading || !!busy || !saved} onClick={() => void run('test')} loading={busy === 'test'}>测试连接</Button>
            <Button type="primary" disabled={loading || !!busy || !saved} onClick={() => void run('save')} loading={busy === 'save'}>保存配置</Button>
          </Space>
        </Space>
      </Spin>
    </Modal></>;
}
