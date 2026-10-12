import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { App as AntApp, Alert, Avatar, Badge, Button, Card, ConfigProvider, Drawer, Empty, Form, Input, Layout,
  List, Menu, Modal, Pagination, Popconfirm, Select, Space, Spin, Table, Tag, Typography, Upload, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BookOutlined, CommentOutlined, FileTextOutlined, LogoutOutlined, PlusOutlined, SendOutlined,
  UploadOutlined, SafetyCertificateOutlined, ArrowRightOutlined, CustomerServiceOutlined, CheckCircleOutlined,
  ClockCircleOutlined, LinkOutlined, StopOutlined, UserOutlined, SettingOutlined, BellOutlined, CalendarOutlined, ReadOutlined,
  DeleteOutlined, HistoryOutlined } from '@ant-design/icons';
import { api, post, streamAnswer, date, statusText, ApiError } from './api';
import './style.css';
import { Notices, Study, Todos } from './campus';
import { AIConfiguration } from './AIConfiguration';
import { DraftAccount } from './drafts';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
type User = { id: string; role: 'student' | 'admin'; name: string; email: string };
type Citation = { chunk_id: string; document_name: string; heading: string; page?: number; paragraph?: number };
const categories = ['校园网络', '账号登录', '软件服务', '设备故障', '其他'];
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 1000 } } });

function ErrorNote({ error }: { error: unknown }) {
  return error ? <Alert type="error" showIcon message={error instanceof Error ? error.message : '请求失败'} /> : null;
}

function SourceButton({ source }: { source: Citation }) {
  const [open, setOpen] = useState(false);
  const { data, error, isFetching } = useQuery({ queryKey: ['source', source.chunk_id],
    queryFn: () => api('/sources/' + source.chunk_id), enabled: open, staleTime: 0 });
  return <><Button size="small" icon={<LinkOutlined />} onClick={() => setOpen(true)}>{source.document_name}
    {source.page ? ` · 第 ${source.page} 页` : ''}</Button>
    <Drawer open={open} width={600} title="查看回答依据" onClose={() => setOpen(false)}>
      {isFetching ? <Spin /> : <><ErrorNote error={error} />{data && !error && <>
        <Title level={4}>{data.document_name}</Title><Tag>版本 {data.version_id?.slice(0, 8)}</Tag>
        <Paragraph type="secondary">{data.heading}{data.page ? ` · 第 ${data.page} 页` : ''}
          {data.paragraph ? ` · 段落 / 行 ${data.paragraph}` : ''}</Paragraph>
          {data.source_spans?.length > 1 && <div style={{ marginBottom: 12 }}>{data.source_spans.map((span: any, index: number) => <Paragraph key={index} type="secondary" style={{ marginBottom: 4 }}>
            {span.heading}{span.page ? ` · 第 ${span.page} 页` : ''}{span.paragraph ? ` · 原文行 / 段落 ${span.paragraph}` : ''}
          </Paragraph>)}</div>}
        <pre className="source-text">{data.content}</pre></>}</>}
    </Drawer></>;
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [entryRole, setEntryRole] = useState<User['role']>('student');
  const [form] = Form.useForm();
  const chooseEntry = (role: User['role']) => {
    if (entryRole !== role) { setEntryRole(role); setError(undefined); form.resetFields(['password']); }
  };
  return <div className="login-page"><section className="login-story">
    <div className="brand"><span className="brand-mark">IT</span> 校园 IT 服务台</div>
    <div><div className="eyebrow">CAMPUS SERVICE DESK</div><h1>让每一个问题，<br />都有下一步。</h1>
      <p>从校园网络到软件服务，查找有据可依的答案，<br />或把问题交给能解决它的人。</p>
      <div className="login-features"><span><BookOutlined /> 查找知识</span><span><LinkOutlined /> 核对来源</span>
        <span><CustomerServiceOutlined /> 跟进工单</span></div></div>
    <small>知识有出处，服务有记录。</small>
  </section><section className="login-panel"><div className="login-card">
    <Tag color={entryRole === 'admin' ? 'blue' : 'cyan'}>校园服务 · 原型</Tag>
    <Title level={2}>选择你的服务入口</Title>
    <div className="login-entries" role="radiogroup" aria-label="登录入口">
      {(['student', 'admin'] as const).map(role => <button key={role} type="button" role="radio"
        aria-label={role === 'student' ? '学生登录' : '管理端登录'} aria-checked={entryRole === role} disabled={busy}
        tabIndex={entryRole === role ? 0 : -1} data-entry-role={role}
        className={'login-entry ' + role + (entryRole === role ? ' selected' : '')}
        onClick={() => chooseEntry(role)} onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const nextRole = event.key === 'Home' ? 'student' : event.key === 'End' ? 'admin' : role === 'student' ? 'admin' : 'student';
          chooseEntry(nextRole);
          event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-entry-role="${nextRole}"]`)?.focus();
        }}>
        {role === 'student' ? <UserOutlined /> : <SettingOutlined />}
        <b>{role === 'student' ? '学生登录' : '管理端登录'}</b>
        <span>{role === 'student' ? '查阅知识 · 跟进我的工单' : '管理资料 · 处理服务工单'}</span>
      </button>)}
    </div>
    <Paragraph type="secondary" className="login-entry-description">{entryRole === 'student'
      ? '使用学生账号，开始校园问答或查看自己的工单。'
      : '使用管理员账号，维护知识库并处理师生服务请求。'}</Paragraph>
    <ErrorNote error={error} /><Form form={form} layout="vertical" onFinish={async values => {
      setBusy(true); setError(undefined);
      try { onLogin(await api<User>('/auth/login', post({ ...values, entry_role: entryRole }))); } catch (e) { setError(e); } finally { setBusy(false); }
    }}><Form.Item name="email" label="账号邮箱" rules={[{ required: true, message: '请输入账号' }]}>
      <Input size="large" placeholder={entryRole === 'student' ? 'student@example.test' : 'admin@example.test'} autoComplete="username" /></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
        <Input.Password size="large" autoComplete="current-password" /></Form.Item>
      <Button block size="large" type="primary" htmlType="submit" loading={busy}>{entryRole === 'student' ? '登录学生服务台' : '登录管理端'} <ArrowRightOutlined aria-hidden="true" /></Button>
    </Form><div className="login-tip"><SafetyCertificateOutlined /> 演示账号由管理员初始化；不开放注册。</div>
  </div></section></div>;
}

function TicketDetail({ id, user, onClose }: { id?: string; user: User; onClose: () => void }) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);
  const { data, error, isFetching } = useQuery({ queryKey: ['ticket', id], queryFn: () => api('/tickets/' + id),
    enabled: !!id, refetchInterval: id ? 5000 : false });
  const mutate = async (path: string, options: RequestInit) => {
    setBusy(true);
    try { await api(path, options); setReply(''); await client.invalidateQueries({ queryKey: ['ticket'] });
      await client.invalidateQueries({ queryKey: ['tickets'] }); } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const transitions: Record<string, string[]> = user.role === 'admin'
    ? { open: ['in_progress', 'awaiting_student', 'resolved'], in_progress: ['awaiting_student', 'resolved'],
      awaiting_student: ['in_progress', 'resolved'], resolved: ['in_progress'] }
    : { resolved: ['closed', 'open'] };
  return <Drawer width={660} open={!!id} title="工单详情" onClose={onClose} destroyOnHidden>
    <ErrorNote error={error} />{!data && isFetching && <Spin />}{data && <>
      <Space><Tag color={data.status === 'resolved' ? 'green' : 'cyan'}>{statusText[data.status]}</Tag><Text type="secondary">{data.category}</Text></Space>
      <Title level={3}>{data.title}</Title><Text type="secondary">#{data.id.slice(0, 8)} · {date(data.created_at)} · {data.location || '未填写地点'}</Text>
      <Paragraph className="ticket-description">{data.description}</Paragraph>
      <Space wrap>{data.sources.map((s: Citation, i: number) => <SourceButton key={i} source={s} />)}</Space>
      <div className="section-label">处理进展</div>
      <List dataSource={data.events} renderItem={(item: any) => <List.Item><Space><ClockCircleOutlined />
        <Text>{item.before ? `${statusText[item.before]} → ` : '提交工单 → '}{statusText[item.after]}</Text>
        <Text type="secondary">{date(item.created_at)}</Text></Space></List.Item>} />
      <Space wrap>{(transitions[data.status] || []).map(status => <Button key={status} loading={busy}
        type={status === 'resolved' || status === 'closed' ? 'primary' : 'default'}
        onClick={() => mutate('/tickets/' + id + '/status', { method: 'PATCH', body: JSON.stringify({ status }) })}>
        {status === 'closed' ? '确认解决并关闭' : status === 'open' ? '仍未解决，重新打开' : `标记为${statusText[status]}`}</Button>)}</Space>
      <div className="section-label">沟通记录</div>
      {!data.replies.length && <Paragraph type="secondary">暂时没有回复。</Paragraph>}
      {data.replies.map((r: any) => <div key={r.id} className={'reply ' + r.role}><Space><Avatar size="small">{r.author[0]}</Avatar>
        <b>{r.author}</b><Tag>{r.role === 'admin' ? '管理员' : '学生'}</Tag><Text type="secondary">{date(r.created_at)}</Text></Space>
        <Paragraph style={{ whiteSpace: 'pre-wrap', margin: '12px 0 0' }}>{r.content}</Paragraph></div>)}
      {data.status !== 'closed' ? <><TextArea aria-label="工单回复" rows={4} maxLength={4000} value={reply}
        onChange={e => setReply(e.target.value)} placeholder={user.role === 'admin' ? '说明处理结果或需要补充的信息…' : '补充具体情况或反馈处理结果…'} />
        <Button style={{ marginTop: 12 }} type="primary" disabled={!reply.trim()} loading={busy}
          onClick={() => mutate('/tickets/' + id + '/replies', post({ content: reply }))}>发送回复</Button></>
        : <Alert type="success" message="工单已关闭，记录已保留。" />}
    </>}
  </Drawer>;
}

function Tickets({ user }: { user: User }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const { data, error, isFetching } = useQuery({ queryKey: ['tickets', page, status],
    queryFn: () => api(`/tickets?page=${page}${status ? '&status=' + status : ''}`), refetchInterval: 5000 });
  return <><div className="page-heading"><div className="eyebrow">REQUESTS</div><Title level={2}>{user.role === 'admin' ? '工单工作台' : '我的工单'}</Title>
    <Paragraph type="secondary">{user.role === 'admin' ? '让待处理的问题得到回应，保留每一步服务记录。' : '查看处理进度，补充信息，确认问题是否解决。'}</Paragraph></div>
    <ErrorNote error={error} /><Card><div className="table-toolbar"><b>服务请求</b><Select allowClear placeholder="所有状态"
      style={{ width: 160 }} value={status} onChange={v => { setStatus(v); setPage(1); }}
      options={['open', 'in_progress', 'awaiting_student', 'resolved', 'closed'].map(value => ({ value, label: statusText[value] }))} /></div>
      <Table<any> rowKey="id" loading={isFetching} dataSource={data?.items || []} pagination={false}
        locale={{ emptyText: <Empty description="暂无工单，遇到问题时可从知识问答创建。" /> }}
        columns={[{ title: '问题', dataIndex: 'title', render: (v, r) => <Button type="link" onClick={() => setSelected(r.id)}>{v}</Button> },
          { title: '分类', dataIndex: 'category' }, { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'resolved' || v === 'closed' ? 'green' : 'cyan'}>{statusText[v]}</Tag> },
          { title: '提交时间', dataIndex: 'created_at', render: date }]}
      /><Pagination style={{ marginTop: 20 }} current={page} total={data?.total || 0} pageSize={20} showSizeChanger={false} onChange={setPage} />
    </Card><TicketDetail id={selected} user={user} onClose={() => setSelected(undefined)} /></>;
}

function Knowledge() {
  const client = useQueryClient(); const { message } = AntApp.useApp();
  const [page, setPage] = useState(1); const [visibility, setVisibility] = useState('public');
  const [selected, setSelected] = useState<string>(); const [uploading, setUploading] = useState(false);
  const { data, error, isFetching } = useQuery({ queryKey: ['documents', page], queryFn: () => api('/documents?page=' + page), refetchInterval: 2500 });
  const detail = useQuery({ queryKey: ['document', selected], queryFn: () => api('/documents/' + selected), enabled: !!selected, refetchInterval: selected ? 2500 : false });
  const refresh = () => { client.invalidateQueries({ queryKey: ['documents'] }); client.invalidateQueries({ queryKey: ['document'] }); };
  const action = async (path: string, options: RequestInit) => { try { await api(path, options); refresh(); } catch (e) { message.error((e as Error).message); } };
  const upload = async (file: File, id?: string) => {
    setUploading(true); const body = new FormData(); body.append('file', file); if (!id) body.append('visibility', visibility);
    try { await api(id ? `/documents/${id}/versions` : '/documents', { method: 'POST', body }); refresh(); message.success('资料已接收，请等待后台处理'); }
    catch (e) { message.error((e as Error).message); } finally { setUploading(false); }
  };
  return <><div className="page-heading"><div className="eyebrow">KNOWLEDGE BASE</div><Title level={2}>知识库管理</Title>
    <Paragraph type="secondary">把校园 IT 操作指南变成可查询、可引用的知识。</Paragraph></div>
    <ErrorNote error={error} /><div className="knowledge-upload"><div><UploadOutlined /><Title level={4}>添加服务资料</Title>
      <Text type="secondary">支持 MD、TXT、DOCX、文本 PDF · 单文件 20 MB · PDF 最多 100 页</Text></div>
      <Space wrap><Select value={visibility} onChange={setVisibility} style={{ width: 170 }} options={[
        { value: 'public', label: '所有用户可见' }, { value: 'admin', label: '仅管理员可见' }]} />
        <Upload showUploadList={false} accept=".md,.txt,.docx,.pdf" beforeUpload={file => { void upload(file); return false; }}>
          <Button type="primary" icon={<PlusOutlined />} loading={uploading}>上传资料</Button></Upload></Space></div>
    <Card><div className="table-toolbar"><b>资料与导入任务</b><Text type="secondary">任务状态自动更新</Text></div>
      <Table<any> rowKey="id" loading={isFetching} dataSource={data?.items || []} pagination={false} columns={[
        { title: '资料名称', dataIndex: 'name', render: (v, r) => <Button type="link" onClick={() => setSelected(r.id)}>{v}</Button> },
        { title: '可见范围', dataIndex: 'visibility', render: (v, r) => <Select value={v} size="small" style={{ width: 120 }} options={[
          { value: 'public', label: '公开' }, { value: 'admin', label: '管理员' }]}
          onChange={visibility => action(`/documents/${r.id}/visibility`, { method: 'PATCH', body: JSON.stringify({ visibility }) })} /> },
        { title: '最新导入', render: (_, r) => <><Tag color={r.versions[0]?.status === 'failed' ? 'red' : r.versions[0]?.status === 'ready' ? 'green' : 'blue'}>
          {statusText[r.versions[0]?.status] || '待处理'}</Tag>{r.versions[0]?.error && <Text type="danger">{r.versions[0].error}</Text>}
          {r.active_version_id && r.versions[0]?.status !== 'ready' && <Tag>旧版本仍可用</Tag>}</> },
        { title: '操作', render: (_, r) => <Space><Upload showUploadList={false} beforeUpload={file => { void upload(file, r.id); return false; }} accept=".md,.txt,.docx,.pdf">
          <Button size="small" loading={uploading}>更新版本</Button></Upload>{r.versions[0]?.status === 'failed' && <Button size="small" onClick={() => action(`/documents/${r.id}/retry`, { method: 'POST' })}>重试</Button>}
          <Popconfirm title="删除后资料立即退出检索，确认删除？" onConfirm={() => action('/documents/' + r.id, { method: 'DELETE' })}><Button size="small" danger>删除</Button></Popconfirm></Space> }
      ]} scroll={{ x: 800 }} /><Pagination style={{ marginTop: 20 }} current={page} total={data?.total || 0} pageSize={20} showSizeChanger={false} onChange={setPage} />
    </Card><Drawer width={700} title="资料版本与分块" open={!!selected} onClose={() => setSelected(undefined)}>
      <ErrorNote error={detail.error} />{detail.data && <><Title level={4}>{detail.data.name}</Title>
        <List dataSource={detail.data.versions} renderItem={(v: any) => <List.Item><Space wrap><Text>{date(v.created_at)}</Text>
          <Tag>{statusText[v.status]}</Tag><Text>{v.chunks} 个分块</Text><Text type="secondary">{v.index_key}</Text>
          {v.error && <Text type="danger">{v.error}</Text>}</Space></List.Item>} />
        <div className="section-label">当前生效分块（最多展示 100 个）</div>
        {detail.data.chunks.map((c: any) => <Card key={c.id} size="small" style={{ marginBottom: 12 }} title={c.heading || '正文'}>
          <Text type="secondary">{c.page ? `第 ${c.page} 页` : c.paragraph ? `段落 / 行 ${c.paragraph}` : ''}</Text>
          <pre className="source-text">{c.content}</pre></Card>)}</>}
    </Drawer></>;
}

function Chat({ user, mode }: { user: User; mode: string }) {
  const client = useQueryClient(); const { message } = AntApp.useApp();
  const [selected, setSelected] = useState<string>(); const [page, setPage] = useState(1); const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false); const [progress, setProgress] = useState(''); const [draft, setDraft] = useState<any>();
  const [draftBusy, setDraftBusy] = useState(false); const [ticketId, setTicketId] = useState<string>();
  const [historyOpen, setHistoryOpen] = useState(false); const [historyPage, setHistoryPage] = useState(1);
  const [clearing, setClearing] = useState(false);
  const [draftForm] = Form.useForm(); const controller = useRef<AbortController | null>(null); const submitKey = useRef('');
  const list = useQuery({ queryKey: ['conversations', page], queryFn: () => api('/conversations?page=' + page) });
  const history = useQuery({ queryKey: ['conversations', 'history', historyPage],
    queryFn: () => api(`/conversations?history=true&page=${historyPage}`), enabled: historyOpen });
  const chat = useQuery({ queryKey: ['conversation', selected], queryFn: () => api('/conversations/' + selected), enabled: !!selected });
  useEffect(() => () => controller.current?.abort(), []);
  const clear = async (allHistory: boolean) => {
    setClearing(true);
    try {
      await api('/conversations' + (allHistory ? '?history=true' : ''), { method: 'DELETE' });
      setSelected(undefined); setInput(''); setDraft(undefined); setPage(1); setHistoryPage(1);
      client.removeQueries({ queryKey: ['conversation'] });
      await client.invalidateQueries({ queryKey: ['conversations'] });
      message.success(allHistory ? '历史记录已清空' : '最近会话已清空，可在历史记录中查看');
    } catch (e) { message.error((e as Error).message); } finally { setClearing(false); }
  };
  const create = async () => { const c = await api('/conversations', { method: 'POST' }); setSelected(c.id); client.invalidateQueries({ queryKey: ['conversations'] }); return c.id; };
  const send = async (question = input) => {
    if (!question.trim() || busy || clearing) return;
    setBusy(true); setProgress('正在准备回答…'); setInput(''); controller.current = new AbortController();
    try {
      const id = selected || await create();
      await streamAnswer(id, question, controller.current.signal, (event, data) => {
        if (event === 'status') setProgress(data.message);
        if (event === 'error') message.error(data.message);
      });
    } catch (e) { if ((e as Error).name !== 'AbortError') message.error((e as Error).message); }
    finally { setBusy(false); setProgress(''); client.invalidateQueries({ queryKey: ['conversation'] }); client.invalidateQueries({ queryKey: ['conversations'] }); }
  };
  const prepare = async () => {
    if (!selected) return; setDraftBusy(true);
    try { const value = await api(`/conversations/${selected}/ticket-draft`, { method: 'POST' }); setDraft(value);
      submitKey.current = crypto.randomUUID(); draftForm.setFieldsValue(value); }
    catch (e) { message.error((e as Error).message); } finally { setDraftBusy(false); }
  };
  return <><div className="page-heading"><div className="eyebrow">ASK & RESOLVE</div><Title level={2}>知识问答</Title>
    <Paragraph type="secondary">可以直接聊天或询问通用知识。校园 IT 问题会查阅资料并展示引用，未解决时可创建工单。</Paragraph></div>
    <div className="chat-layout"><aside className="conversation-panel"><Button block icon={<PlusOutlined />} disabled={busy || clearing}
      onClick={() => create().catch(e => message.error(e.message))}>新的问题</Button>
      <div className="conversation-toolbar"><span className="section-label">最近会话</span>
        <Popconfirm title="清空最近会话？" description="问答仍会保留在历史记录中。" okText="清空" cancelText="取消"
          onConfirm={() => clear(false)} disabled={busy || clearing || draftBusy || !list.data?.total}>
          <Button size="small" type="text" icon={<DeleteOutlined />} disabled={busy || clearing || draftBusy || !list.data?.total}
            loading={clearing} aria-label="清空最近会话">清空</Button>
        </Popconfirm></div>
      <Button block icon={<HistoryOutlined />} className="conversation-history-button" disabled={busy || clearing}
        onClick={() => { setHistoryPage(1); setHistoryOpen(true); }}>历史记录</Button>
      <ErrorNote error={list.error} /><List loading={list.isFetching} locale={{ emptyText: '暂无最近会话' }}
        dataSource={list.data?.items || []} renderItem={(c: any) => <button className={'conversation-item ' + (selected === c.id ? 'active' : '')}
        disabled={busy || clearing} onClick={() => setSelected(c.id)}><CommentOutlined /><span>{c.title}</span>{c.mode === 'ticketed' && <Tag>工单</Tag>}</button>} />
      {(list.data?.total || 0) > 20 && <Pagination simple current={page} total={list.data.total} pageSize={20} onChange={setPage} />}
    </aside><section className="chat-main"><ErrorNote error={chat.error} />
      <div className="chat-messages">{!chat.data?.messages.length && !busy ? <div className="chat-welcome"><div className="assistant-logo"><CustomerServiceOutlined /></div>
        <Title level={3}>你好，需要哪方面的帮助？</Title><Paragraph type="secondary">描述具体问题或错误代码，可以更快找到相关资料。</Paragraph>
        <div className="suggestions">{['校园网连接后无法上网怎么办？', 'VPN 错误 809 怎么处理？', '忘记统一认证密码怎么办？'].map(q =>
          <button key={q} onClick={() => send(q)}>{q}<ArrowRightOutlined /></button>)}</div>
      </div> : chat.data?.messages.map((m: any, index: number) => <article key={m.id} className={'chat-message ' + m.role}>
        <Avatar size={32} style={{ background: m.role === 'user' ? '#e9edf1' : '#d5f1ea', color: '#285548' }}>
          {m.role === 'user' ? user.name[0] : <CustomerServiceOutlined />}</Avatar>
        <div className="message-body"><div className="message-meta"><b>{m.role === 'user' ? '你' : '校园 IT 助手'}</b>
          {m.role === 'assistant' && <><Tag color={m.model_mode === 'mock' ? 'gold' : 'cyan'}>{m.model_mode === 'mock' ? '模拟模式' : '真实模型'}</Tag><Tag>{m.answer_kind === 'general' ? '普通回复 · 未查询知识库' : '知识库回答'}</Tag></>}
          <Text type="secondary">{date(m.created_at)}</Text></div><div className="message-content">{m.content || statusText[m.status]}</div>
          {m.status === 'failed' || m.status === 'interrupted' ? <Space><Tag color="red">{statusText[m.status]}</Tag>
            {chat.data.mode === 'bot' && <Button size="small" disabled={busy} onClick={() => {
              const previous = chat.data.messages.slice(0, index).reverse().find((item: any) => item.role === 'user');
              if (previous) void send(previous.content);
            }}>重试此问题</Button>}</Space> : null}
          <Space wrap className="citations">{(m.citations || []).map((s: Citation, i: number) => <SourceButton key={i} source={s} />)}</Space>
        </div></article>)}{busy && <div className="chat-progress"><Spin size="small" /><span>{progress}</span>
          <Button size="small" icon={<StopOutlined />} onClick={() => controller.current?.abort()}>停止</Button></div>}</div>
      {chat.data?.mode === 'ticketed' ? <Alert showIcon type="info" message="此会话已转工单，请在工单中继续沟通。"
        action={<Button onClick={() => setTicketId(chat.data.ticket_id)}>查看工单</Button>} /> : <div className="chat-compose">
        <TextArea aria-label="问题" value={input} onChange={e => setInput(e.target.value)} maxLength={4000} autoSize={{ minRows: 2, maxRows: 5 }}
          placeholder="例如：宿舍校园网连接成功，但浏览器无法打开网页…" onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
          }} /><div className="compose-toolbar"><Text type="secondary">{mode === 'mock' ? '模拟模式用于验证流程，不代表真实 AI 效果。' : '普通回复不代表学校政策；知识库回答请核对引用。'}</Text>
          <Space><Button disabled={!chat.data?.messages.length || busy} loading={draftBusy} onClick={prepare}>未解决？创建工单</Button>
            <Button aria-label="发送" type="primary" icon={<SendOutlined />} disabled={!input.trim() || clearing} loading={busy} onClick={() => send()}>发送</Button></Space></div>
      </div>}
    </section></div>
    <Drawer title="问答历史记录" width={560} open={historyOpen} onClose={() => setHistoryOpen(false)}
      extra={<Popconfirm title="清空全部历史记录？" description="全部问答将从历史记录和最近会话中移除，无法恢复。已创建的工单会保留。"
        okText="清空" cancelText="取消" onConfirm={() => clear(true)} disabled={busy || clearing || draftBusy || !history.data?.total}>
        <Button danger icon={<DeleteOutlined />} loading={clearing} disabled={busy || clearing || draftBusy || !history.data?.total}>清空历史记录</Button>
      </Popconfirm>}>
      <Paragraph type="secondary">包括已从最近会话清空的问答，点击会话即可查看完整内容。</Paragraph>
      <ErrorNote error={history.error} />
      <List loading={history.isFetching} dataSource={history.data?.items || []} locale={{ emptyText: '暂无历史记录' }}
        renderItem={(c: any) => <List.Item><button className="conversation-item conversation-history-item" disabled={busy || clearing}
          onClick={() => { setSelected(c.id); setHistoryOpen(false); }}>
          <CommentOutlined /><div><b>{c.title}</b><Text type="secondary">{date(c.created_at)}</Text></div>
          {c.mode === 'ticketed' && <Tag>工单</Tag>}
        </button></List.Item>} />
      {(history.data?.total || 0) > 20 && <Pagination current={historyPage} total={history.data.total} pageSize={20}
        showSizeChanger={false} onChange={setHistoryPage} />}
    </Drawer>
    <Modal title="确认工单内容" open={!!draft} onCancel={() => setDraft(undefined)} confirmLoading={draftBusy} okText="确认提交工单"
      onOk={() => draftForm.submit()}><Paragraph type="secondary">检查并补充信息后提交，管理员会在工单中回复。</Paragraph>
      <Form form={draftForm} layout="vertical" onFinish={async values => { setDraftBusy(true);
        try { const ticket = await api('/tickets', { ...post({ draft_id: draft.id, ...values }), headers: { 'Idempotency-Key': submitKey.current } });
          setDraft(undefined); setTicketId(ticket.id); client.invalidateQueries({ queryKey: ['conversation'] }); client.invalidateQueries({ queryKey: ['conversations'] }); }
        catch (e) { message.error((e as Error).message); } finally { setDraftBusy(false); }
      }}><Form.Item name="title" label="问题标题" rules={[{ required: true, whitespace: true }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="category" label="分类" rules={[{ required: true }]}><Select options={categories.map(value => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="description" label="具体情况" rules={[{ required: true, whitespace: true }]}><TextArea rows={5} maxLength={8000} /></Form.Item>
        <Form.Item name="location" label="地点（可选）"><Input maxLength={120} placeholder="例如：图书馆二层" /></Form.Item>
      </Form></Modal><TicketDetail id={ticketId} user={user} onClose={() => setTicketId(undefined)} />
  </>;
}

type SystemMessage = { id: string; sequence: number; ticket_id: string | null; announcement_id: string | null; todo_id: string | null; study_job_id?: string | null; title: string; content: string; created_at: string; read_at: string | null };
function MessageCenter({ user, onNavigate }: { user: User; onNavigate: (view: string, id: string) => void }) {
  const client = useQueryClient();
  const { notification, message } = AntApp.useApp();
  const [open, setOpen] = useState(false);
  const centerOpen = useRef(false);
  useEffect(() => { centerOpen.current = open; if (open) notification.destroy(); }, [open, notification]);
  const [page, setPage] = useState(1);
  const [unread, setUnread] = useState(0);
  const [ticketId, setTicketId] = useState<string>();
  const [connectionError, setConnectionError] = useState(false);
  const [busy, setBusy] = useState(false);
  const list = useQuery({ queryKey: ['notifications', user.id, page], queryFn: () => api('/notifications?page=' + page), enabled: open });
  const refresh = () => client.invalidateQueries({ queryKey: ['notifications', user.id] });
  const viewMessage = async (item: SystemMessage) => {
    try {
      await api('/notifications/' + item.id + '/read', { method: 'POST' });
      await refresh(); setOpen(false);
      if (item.ticket_id) setTicketId(item.ticket_id);
      else if (item.announcement_id) onNavigate('notices', item.announcement_id);
      else if (item.todo_id) onNavigate('todos', item.todo_id);
      else if (item.study_job_id) onNavigate('study', item.study_job_id);
      notification.destroy(item.id);
      const summary = await api('/notifications/updates'); setUnread(summary.unread_count);
    } catch (e) { message.error((e as Error).message); }
  };
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let cursor: number | undefined;
    const controller = new AbortController();
    const poll = async () => {
      let delay = 5000;
      try {
        const data = await api<{ items: SystemMessage[]; cursor: number; unread_count: number }>(
          '/notifications/updates' + (cursor === undefined ? '' : '?after=' + cursor), { signal: controller.signal });
        if (stopped) return;
        cursor = data.cursor; setUnread(data.unread_count); setConnectionError(false);
        const pending = centerOpen.current ? [] : data.items.filter(item => !item.read_at);
        for (const item of pending.slice(0, 3)) notification.info({
          key: item.id, message: item.title, description: item.content, duration: 8,
          actions: <Button type="primary" size="small" onClick={() => void viewMessage(item)}>{item.ticket_id ? '查看工单' : item.todo_id ? '查看待办' : item.study_job_id ? '查看学习任务' : '查看通知'}</Button>,
        });
        if (pending.length > 3) notification.info({ key: 'more-messages', message: '收到多条新消息',
          description: `还有 ${pending.length - 3} 条新消息，请在消息中心查看。`, duration: 8,
          actions: <Button size="small" onClick={() => setOpen(true)}>查看消息</Button> });
        if (data.items.length) { void refresh(); void client.invalidateQueries({ queryKey: ['tickets'] }); void client.invalidateQueries({ queryKey: ['ticket'] }); }
        if (data.items.length === 100) delay = 100;
      } catch (e) { if (!stopped) setConnectionError(true); }
      if (!stopped) timer = setTimeout(poll, delay);
    };
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); notification.destroy(); };
  }, [user.id, client, notification]);
  return <>
    <Badge count={unread} overflowCount={99} size="small"><Button aria-label="消息中心" icon={<BellOutlined aria-hidden="true" />}
      onClick={() => { setOpen(true); void refresh(); }}>消息</Button></Badge>
    <Drawer title="消息中心" width={480} open={open} onClose={() => setOpen(false)}>
      <div className="table-toolbar"><Text>{unread} 条未读消息</Text><Button disabled={!unread || busy} loading={busy} onClick={async () => {
        setBusy(true); try { await api('/notifications/read-all', { method: 'POST' }); setUnread(0); await refresh(); notification.destroy(); }
        catch (e) { message.error((e as Error).message); } finally { setBusy(false); }
      }}>全部标为已读</Button></div>
      {connectionError && <Alert type="warning" showIcon message="消息提醒暂时无法连接，正在自动重试。" />}
      <ErrorNote error={list.error} />
      <List loading={list.isFetching} dataSource={list.data?.items || []} locale={{ emptyText: <Empty description="暂时没有系统消息" /> }}
        renderItem={(item: SystemMessage) => <List.Item className={'system-message ' + (!item.read_at ? 'unread' : '')}>
          <div><Space><b>{item.title}</b>{!item.read_at && <Tag color="cyan">未读</Tag>}</Space>
            <Paragraph>{item.content}</Paragraph><Text type="secondary">{date(item.created_at)}</Text>
            <Button type="link" onClick={() => void viewMessage(item)}>{item.ticket_id ? '查看工单' : item.todo_id ? '查看待办' : item.study_job_id ? '查看学习任务' : '查看通知'}</Button></div>
        </List.Item>} />
      <Pagination current={page} pageSize={20} showSizeChanger={false} total={list.data?.total || 0} onChange={setPage} />
    </Drawer><TicketDetail id={ticketId} user={user} onClose={() => setTicketId(undefined)} />
  </>;
}

function Workspace() {
  const client = useQueryClient(); const { message } = AntApp.useApp();
  const [user, setUser] = useState<User>(); const [view, setView] = useState('chat');
  const [focus, setFocus] = useState<{ view: string; id: string; sequence: number }>();
  const account = useQuery<User>({ queryKey: ['me'], queryFn: () => api('/auth/me') });
  const system = useQuery({ queryKey: ['system'], queryFn: () => api('/system') });
  const aiConfig = useQuery({ queryKey: ['ai-config', user?.id], queryFn: () => api('/ai-config'), enabled: !!user });
  useEffect(() => { if (account.data) setUser(account.data);
    else if (account.error instanceof ApiError && account.error.status === 401) setUser(undefined);
  }, [account.data, account.error]);
  if (account.isPending && !user) return <div className="loading-screen"><Spin size="large" /></div>;
  if (!user) return <>{account.error && !(account.error instanceof ApiError && account.error.status === 401) && <ErrorNote error={account.error} />}
    <Login onLogin={value => { client.clear(); setUser(value); setView('chat'); }} /></>;
  const mode = aiConfig.data && aiConfig.data.mode !== 'default' ? 'real' : system.data?.model_mode || 'mock';
  return <DraftAccount.Provider value={user.id}><Layout className="workspace"><Layout.Sider width={228} breakpoint="lg" collapsedWidth={0} className="sidebar">
    <div className="brand"><span className="brand-mark">IT</span><div>校园 IT 服务台<small>CAMPUS SUPPORT</small></div></div>
    <div className="sidebar-label">服务空间</div><Menu theme="dark" mode="inline" selectedKeys={[view]} onClick={e => { setView(e.key); setFocus(undefined); }} items={[
      { key: 'chat', icon: <CommentOutlined aria-hidden="true" />, label: '知识问答' },
      { key: 'notices', icon: <BellOutlined aria-hidden="true" />, label: '校园通知' },
      { key: 'todos', icon: <CalendarOutlined aria-hidden="true" />, label: '个人待办' },
      { key: 'study', icon: <ReadOutlined aria-hidden="true" />, label: '学习资料助手' },
      { key: 'tickets', icon: <FileTextOutlined aria-hidden="true" />, label: user.role === 'admin' ? '工单工作台' : '我的工单' },
      ...(user.role === 'admin' ? [{ key: 'knowledge', icon: <BookOutlined aria-hidden="true" />, label: '知识库管理' }] : [])]} />
    <div className="sidebar-note"><CheckCircleOutlined /><b>每一步都有记录</b><p>答案可核对<br />问题可跟进</p></div>
  </Layout.Sider><Layout><Layout.Header className="topbar"><span>校园服务 / {({ chat: '知识问答', knowledge: '知识库管理', notices: '校园通知', todos: '个人待办', study: '学习资料助手', tickets: '工单' } as Record<string, string>)[view]}</span>
    <Space><MessageCenter key={user.id} user={user} onNavigate={(next, id) => { setView(next); setFocus({ view: next, id, sequence: Date.now() }); }} /><AIConfiguration key={user.id} onSaved={() => { void client.invalidateQueries({ queryKey: ['ai-config'] }); }} /><Avatar size="small">{user.name[0]}</Avatar>
      <Text>{user.name}</Text><Tag>{user.role === 'admin' ? '管理员' : '学生'}</Tag><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={async () => {
        try { await api('/auth/logout', { method: 'POST' }); setUser(undefined); client.clear(); } catch (e) { message.error((e as Error).message); }
      }} /></Space></Layout.Header><Layout.Content className="content">
      {view === 'chat' && <Chat key={user.id} user={user} mode={mode} />}{view === 'tickets' && <Tickets user={user} />}
      {view === 'notices' && <Notices key={focus?.view === view ? focus.sequence : view} user={user} focusId={focus?.view === view ? focus.id : undefined} />}
      {view === 'todos' && <Todos key={focus?.view === view ? focus.sequence : view} focusId={focus?.view === view ? focus.id : undefined} />}
      {view === 'study' && <Study key={focus?.view === view ? focus.sequence : user.id} Source={SourceButton} focusId={focus?.view === view ? focus.id : undefined} />}
      {view === 'knowledge' && user.role === 'admin' && <Knowledge />}
      <footer>校园 IT 服务台 · {mode === 'mock' ? '模拟原型' : '知识库服务'} · 服务时间显示为北京时间</footer>
    </Layout.Content></Layout></Layout></DraftAccount.Provider>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={queryClient}>
  <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#087f73', borderRadius: 10,
    fontFamily: 'Inter, "Microsoft YaHei", "PingFang SC", sans-serif', colorBgLayout: '#f5f7fa' } }}>
    <AntApp><Workspace /></AntApp></ConfigProvider></QueryClientProvider></React.StrictMode>);
