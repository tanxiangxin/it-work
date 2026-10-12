import { useState } from 'react';
import { App, Alert, Button, Form, Input, Modal, Select, Space, Spin } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { api, post } from './api';

type Configuration = {
  api_base: string; model: string;
  api_style: 'openai' | 'anthropic'; api_key?: string; has_api_key?: boolean;
};

export function AIConfiguration({ onSaved }: { onSaved: () => void }) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<'save' | 'test'>();
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<Configuration>();
  const [form] = Form.useForm<Configuration>();
  const base = Form.useWatch('api_base', form);
  const apiStyle = Form.useWatch('api_style', form);
  const retainedKey = saved?.has_api_key && saved.api_base.replace(/\/$/, '') === base?.replace(/\/$/, '');
  async function show() {
    setOpen(true); setLoading(true); setError(''); setSaved(undefined); form.resetFields();
    try {
      const data = await api<Configuration>('/ai-config');
      setSaved(data); form.setFieldsValue({ ...data, api_key: undefined });
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
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
    <Modal title="AI 配置" open={open} onCancel={() => { if (!busy) setOpen(false); }} footer={null} destroyOnHidden>
      <Spin spinning={loading}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Alert type="info" showIcon message="自定义模型" description="配置用于知识问答和工单摘要。模型需支持 JSON 格式回复；学习资料助手沿用服务器配置。" />
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
