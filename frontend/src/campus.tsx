import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Alert, Button, Card, Checkbox, Drawer, Empty, Form, Input, List, Modal, Pagination,
  InputNumber, Popconfirm, Radio, Select, Space, Spin, Table, Tag, Typography, Upload } from 'antd';
import { CheckCircleOutlined, DeleteOutlined, PlusOutlined, SearchOutlined, UndoOutlined, UploadOutlined } from '@ant-design/icons';
import { api, date, post, statusText } from './api';
import { TodoTimeInput, normalizeTodoTime } from './TodoTimeInput';
import { DocumentContent } from './DocumentContent';
import { MaterialOrganization } from './MaterialOrganization';

const { Title, Paragraph, Text } = Typography;
const noticeCategories = ['教学', '学工', '招聘', '生活'];
type User = { id: string; role: 'student' | 'admin' };
type Citation = { chunk_id: string; document_name: string; heading: string; number?: number; page?: number; paragraph?: number };
function ErrorNote({ error }: { error: unknown }) {
  return error ? <Alert type="error" showIcon message={error instanceof Error ? error.message : '请求失败'} /> : null;
}
function localTime(value?: string | null) {
  if (!value) return undefined;
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
  return parts.replace(' ', 'T');
}
function utcTime(value?: string) { return value ? new Date(value + ':00+08:00').toISOString() : null; }

function TodoEditor({ item, onClose, onSaved }: { item: any; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (item) { form.resetFields(); form.setFieldsValue({ ...item, due_at: localTime(item.due_at), remind_at: localTime(item.remind_at) }); } }, [item, form]);
  return <Modal title={item?.id ? '编辑个人待办' : '确认加入个人待办'} open={!!item} onCancel={onClose} okText="保存待办" confirmLoading={busy} onOk={() => form.submit()} destroyOnHidden>
    <Paragraph type="secondary">时间按北京时间填写。设置提醒时间后，消息中心会收到一次站内提醒；未填写时不自动提醒。</Paragraph>
    {item?.source_status === 'withdrawn' && <Alert type="warning" message="来源通知已撤回，原事项可能变化，相关提醒已暂停。" />}
    <Form form={form} layout="vertical" onFinish={async values => {
      setBusy(true); try {
        const due = normalizeTodoTime(values.due_at), reminder = normalizeTodoTime(values.remind_at);
        const payload = { ...values, announcement_id: item.announcement_id || null,
          due_at: due === localTime(item.due_at) ? item.due_at || null : utcTime(due),
          remind_at: reminder === localTime(item.remind_at) ? item.remind_at || null : utcTime(reminder), completed: !!values.completed };
        await api(item.id ? '/todos/' + item.id : '/todos', { ...post(payload), method: item.id ? 'PUT' : 'POST' });
        message.success('待办已保存'); onSaved(); onClose();
      } catch (e) { message.error((e as Error).message); } finally { setBusy(false); }
    }}>
      <Form.Item name="title" label="待办标题" rules={[{ required: true, whitespace: true }]}><Input maxLength={160} /></Form.Item>
      <Form.Item name="notes" label="办理要求 / 备注"><Input.TextArea rows={4} maxLength={4000} /></Form.Item>
      <Form.Item name="due_at" label="截止时间（可不填）" extra="最晚完成这件事的时间" rules={[{ validator: async (_, value) => { normalizeTodoTime(value); } }]}>
        <TodoTimeInput label="截止时间" />
      </Form.Item>
      <Form.Item name="remind_at" label="提醒时间（可不填）" extra="希望收到站内消息提醒的时间" rules={[{ validator: async (_, value) => { normalizeTodoTime(value); } }]}>
        <TodoTimeInput label="提醒时间" disabled={!!item?.reminded_at} />
      </Form.Item>
      {item?.reminded_at && <Paragraph type="secondary">此待办已提醒过；下一次提醒请新建待办。</Paragraph>}
      <Form.Item name="completed" valuePropName="checked"><Checkbox>已完成</Checkbox></Form.Item>
    </Form>
  </Modal>;
}

export function Todos({ focusId }: { focusId?: string }) {
  const client = useQueryClient(); const { message } = App.useApp();
  const [page, setPage] = useState(1); const [filter, setFilter] = useState<string>(); const [editing, setEditing] = useState<any>();
  const [completingId, setCompletingId] = useState<string>();
  const data = useQuery({ queryKey: ['todos', page, filter], queryFn: () => api(`/todos?page=${page}${filter ? '&completed=' + (filter === 'done') : ''}`) });
  const refresh = () => client.invalidateQueries({ queryKey: ['todos'] });
  useEffect(() => { if (focusId) void api('/todos/' + focusId).then(setEditing).catch(e => message.error(e.message)); }, [focusId, message]);
  const complete = async (row: any, value: boolean) => {
    setCompletingId(row.id);
    try { await api('/todos/' + row.id, { method: 'PUT', body: JSON.stringify({ title: row.title, notes: row.notes, announcement_id: row.announcement_id, due_at: row.due_at, remind_at: row.remind_at, completed: value }) }); message.success(value ? '待办已完成，可点击“恢复未完成”撤销。' : '待办已恢复为未完成。'); await refresh(); }
    catch (e) { message.error((e as Error).message); }
    finally { setCompletingId(undefined); }
  };
  return <><div className="page-heading"><div className="eyebrow">MY PLANNER</div><Title level={2}>个人待办</Title>
    <Paragraph type="secondary">把通知里的事项变成自己的安排，记录进度并设置提醒。</Paragraph></div>
    <ErrorNote error={data.error} /><Card><div className="table-toolbar"><Space wrap><Select allowClear placeholder="全部待办" style={{ width: 140 }} value={filter} onChange={value => { setFilter(value); setPage(1); }} options={[{ value: 'pending', label: '未完成' }, { value: 'done', label: '已完成' }]} />
      <Button type="primary" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setEditing({ title: '', notes: '', completed: false })}>新建待办</Button></Space></div>
      <Paragraph type="secondary">事项办妥后，点击“确认完成”更新状态；误操作时可点击“恢复未完成”。</Paragraph>
      <List loading={data.isFetching} dataSource={data.data?.items || []} locale={{ emptyText: <Empty description="暂无待办，可手动创建或从校园通知添加。" /> }} renderItem={(row: any) => <List.Item>
        <div className="campus-list-item"><Space wrap><b className={row.completed ? 'todo-done' : ''}>{row.title}</b>
          <Tag color={row.completed ? 'success' : 'processing'}>{row.completed ? '已完成' : '待完成'}</Tag>
          {!row.completed && row.due_at && new Date(row.due_at) < new Date() && <Tag color="red">已过期</Tag>}
          {row.source_status === 'withdrawn' && <Tag color="orange">通知已撤回</Tag>}</Space>
          <Paragraph className="campus-pre">{row.notes}</Paragraph><Space wrap><Text type="secondary">截止：{row.due_at ? date(row.due_at) : '未设置'}</Text>
            <Text type="secondary">提醒：{row.reminded_at ? '已提醒' : row.remind_at ? date(row.remind_at) : '未设置'}</Text>
            {row.source_url && <a href={row.source_url} target="_blank" rel="noopener noreferrer">官方原文</a>}
            {row.completed ? <Button size="small" icon={<UndoOutlined aria-hidden="true" />} loading={completingId === row.id} disabled={!!completingId && completingId !== row.id} onClick={() => void complete(row, false)}>恢复未完成</Button> :
              <Popconfirm title="确认完成这项待办？" description="确认后将标记为已完成，之后可恢复为未完成。" okText="确认完成" cancelText="暂不完成" disabled={!!completingId} onConfirm={() => complete(row, true)}>
                <Button size="small" type="primary" icon={<CheckCircleOutlined aria-hidden="true" />} loading={completingId === row.id} disabled={!!completingId && completingId !== row.id}>确认完成</Button>
              </Popconfirm>}
            <Button size="small" onClick={() => setEditing(row)}>编辑</Button><Popconfirm title="删除这个待办？" onConfirm={async () => {
              try { await api('/todos/' + row.id, { method: 'DELETE' }); await refresh(); } catch (e) { message.error((e as Error).message); }
            }}><Button size="small" danger>删除</Button></Popconfirm></Space></div>
      </List.Item>} /><Pagination current={page} pageSize={20} showSizeChanger={false} total={data.data?.total || 0} onChange={setPage} />
    </Card><TodoEditor item={editing} onClose={() => setEditing(undefined)} onSaved={() => void refresh()} /></>;
}

function NoticeEditor({ item, onClose, onSaved }: { item: any; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm(); const { message } = App.useApp(); const [busy, setBusy] = useState(false); const [extracting, setExtracting] = useState(false); const [extracted, setExtracted] = useState<any>();
  useEffect(() => { if (item) { form.resetFields(); form.setFieldsValue({ category: '教学', ...item, deadline: localTime(item.deadline) }); setExtracted(undefined); } }, [item, form]);
  return <Modal width={700} title="编辑校园通知草稿" open={!!item} onCancel={onClose} okText="保存草稿" confirmLoading={busy} onOk={() => form.submit()} destroyOnHidden>
    <Paragraph type="secondary">粘贴官方通知正文与来源链接。AI 结果需人工核对，保存草稿后再确认发布；不会自动抓取链接内容。</Paragraph>
    <Form form={form} layout="vertical" onFinish={async values => {
      setBusy(true); try { await api(item.id ? '/announcements/' + item.id : '/announcements', { ...post({ ...values, summary: values.summary || '', audience: values.audience || '', location: values.location || '', deadline: utcTime(values.deadline) }), method: item.id ? 'PUT' : 'POST' }); onSaved(); onClose(); }
      catch (e) { message.error((e as Error).message); } finally { setBusy(false); }
    }}>
      <Form.Item name="content" label="官方通知正文" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={7} maxLength={30000} /></Form.Item>
      <Button loading={extracting} disabled={busy} onClick={async () => {
        const content = form.getFieldValue('content'); if (!content?.trim()) { message.warning('请先粘贴正文'); return; }
        setExtracting(true); try { const result = await api('/announcements/extract', post({ content })); setExtracted(result);
          form.setFieldsValue({ title: result.title, summary: result.summary, audience: result.audience, location: result.location, deadline: localTime(result.deadline) });
        } catch (e) { message.error((e as Error).message); } finally { setExtracting(false); }
      }}>AI 提取摘要与办理信息</Button>
      {extracted && <Alert style={{ margin: '16px 0' }} type="warning" showIcon message={`${extracted.model_mode === 'mock' ? '模拟模式 · ' : ''}请核对提取结果后再发布`}
        description={extracted.deadline_evidence ? '截止时间依据：' + extracted.deadline_evidence : '没有提取到明确的完整截止时刻，已留空，可人工核对后填写。'} />}
      <Form.Item name="title" label="通知标题" rules={[{ required: true, whitespace: true }]}><Input maxLength={160} /></Form.Item>
      <Form.Item name="category" label="通知类别" rules={[{ required: true }]}><Select options={noticeCategories.map(value => ({ value, label: value }))} /></Form.Item>
      <Form.Item name="source_url" label="湖南工业大学官方原文链接" rules={[{ required: true, type: 'url' }]}><Input placeholder="https://jwc.hut.edu.cn/..." /></Form.Item>
      <Form.Item name="summary" label="摘要"><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
      <Form.Item name="audience" label="适用对象（未知留空）"><Input maxLength={300} /></Form.Item>
      <Form.Item name="location" label="地点（未知留空）"><Input maxLength={300} /></Form.Item>
      <Form.Item name="deadline" label="截止时间（北京时间，未知留空）"><Input type="datetime-local" /></Form.Item>
    </Form>
  </Modal>;
}

export function Notices({ user, focusId }: { user: User; focusId?: string }) {
  const client = useQueryClient(); const { message } = App.useApp();
  const [page, setPage] = useState(1); const [category, setCategory] = useState<string>(); const [savedOnly, setSavedOnly] = useState(false);
  const [selected, setSelected] = useState<any>(); const [editing, setEditing] = useState<any>(); const [todo, setTodo] = useState<any>();
  const data = useQuery({ queryKey: ['announcements', page, category, savedOnly], queryFn: () => api(`/announcements?page=${page}${category ? '&category=' + category : ''}${savedOnly ? '&saved=true' : ''}`) });
  const subscriptions = useQuery({ queryKey: ['subscriptions', user.id], queryFn: () => api('/subscriptions') });
  const [subscriptionBusy, setSubscriptionBusy] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ['announcements'] });
  useEffect(() => { if (focusId) void api('/announcements/' + focusId).then(setSelected).catch(e => message.error(e.message)); }, [focusId, message]);
  const action = async (id: string, name: string) => {
    try { await api(`/announcements/${id}/${name}`, { method: 'POST' }); setSelected(undefined); await refresh(); message.success(name === 'publish' ? '通知已发布' : '通知已撤回'); }
    catch (e) { message.error((e as Error).message); }
  };
  return <><div className="page-heading"><div className="eyebrow">CAMPUS UPDATES</div><Title level={2}>校园通知</Title>
    <Paragraph type="secondary">查看有来源的教学、学工、招聘和生活通知，订阅关注类别并安排个人待办。</Paragraph></div>
    <Card style={{ marginBottom: 20 }} title="我的通知订阅"><Paragraph type="secondary">订阅后，新发布的通知会发送到消息中心；历史通知不重复推送。</Paragraph>
      <ErrorNote error={subscriptions.error} />{subscriptions.isPending ? <Spin /> : <Checkbox.Group disabled={subscriptionBusy} options={noticeCategories} value={subscriptions.data?.categories || []} onChange={async categories => {
        const previous = subscriptions.data;
        client.setQueryData(['subscriptions', user.id], { categories });
        setSubscriptionBusy(true); try { await api('/subscriptions', { method: 'PUT', body: JSON.stringify({ categories }) }); }
        catch (e) { client.setQueryData(['subscriptions', user.id], previous); message.error((e as Error).message); }
        finally { await client.invalidateQueries({ queryKey: ['subscriptions', user.id] }); setSubscriptionBusy(false); }
      }} />}</Card>
    <ErrorNote error={data.error} /><Card><div className="table-toolbar"><Space wrap><Select allowClear placeholder="全部类别" style={{ width: 130 }} value={category} onChange={value => { setCategory(value); setPage(1); }} options={noticeCategories.map(value => ({ value, label: value }))} />
      <Checkbox checked={savedOnly} onChange={e => { setSavedOnly(e.target.checked); setPage(1); }}>只看收藏</Checkbox></Space>
      {user.role === 'admin' && <Button type="primary" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setEditing({})}>新建通知</Button>}</div>
      <List loading={data.isFetching} dataSource={data.data?.items || []} locale={{ emptyText: <Empty description="暂无通知，管理员核对官方内容后可发布。" /> }} renderItem={(row: any) => <List.Item>
        <div className="campus-list-item"><Space wrap><Tag color="cyan">{row.category}</Tag>{row.status !== 'published' && <Tag>{row.status === 'draft' ? '草稿' : '已撤回'}</Tag>}
          <Button className="notice-title" type="link" onClick={() => setSelected(row)}>{row.title}</Button></Space>
          <Paragraph>{row.summary || '打开查看通知正文'}</Paragraph><Space wrap><Text type="secondary">截止：{row.deadline ? date(row.deadline) : '未明确'}</Text>
            {row.status === 'published' && <Button size="small" onClick={async () => { try { await api(`/announcements/${row.id}/saved`, { method: 'PUT', body: JSON.stringify({ saved: !row.saved }) }); await refresh(); } catch (e) { message.error((e as Error).message); } }}>{row.saved ? '取消收藏' : '收藏'}</Button>}
            {user.role === 'admin' && row.status === 'draft' && <><Button size="small" onClick={() => setEditing(row)}>编辑草稿</Button><Popconfirm title="已核对正文、来源和时间，确认发布？" okText="发布通知" cancelText="取消发布" onConfirm={() => action(row.id, 'publish')}><Button size="small" type="primary">确认发布</Button></Popconfirm></>}
            {user.role === 'admin' && row.status !== 'withdrawn' && <Popconfirm title="撤回后学生无法查看，相关待办提醒将暂停。" onConfirm={() => action(row.id, 'withdraw')}><Button size="small" danger>撤回</Button></Popconfirm>}
          </Space></div>
      </List.Item>} /><Pagination current={page} pageSize={20} showSizeChanger={false} total={data.data?.total || 0} onChange={setPage} />
    </Card><Drawer title="校园通知详情" width={640} open={!!selected} onClose={() => setSelected(undefined)}>
      {selected && <><Tag>{selected.category}</Tag><Title level={3}>{selected.title}</Title><Paragraph>{selected.summary}</Paragraph>
        <Paragraph>适用对象：{selected.audience || '未明确'}<br />地点：{selected.location || '未明确'}<br />截止时间：{selected.deadline ? date(selected.deadline) : '未明确，请核对原文'}</Paragraph>
        <a href={selected.source_url} target="_blank" rel="noopener noreferrer">查看官方原文</a><pre className="source-text">{selected.content}</pre>
        {selected.status === 'published' && <Button type="primary" onClick={() => setTodo({ title: selected.title, notes: selected.summary || selected.content.slice(0, 4000), announcement_id: selected.id, due_at: selected.deadline, completed: false })}>加入个人待办</Button>}
      </>}
    </Drawer><NoticeEditor item={editing} onClose={() => setEditing(undefined)} onSaved={() => void refresh()} />
    <TodoEditor item={todo} onClose={() => setTodo(undefined)} onSaved={() => void client.invalidateQueries({ queryKey: ['todos'] })} />
  </>;
}

function Practice({ exercise, citations, Source }: { exercise: any; citations: Citation[]; Source: React.ComponentType<{ source: Citation }> }) {
  const [answer, setAnswer] = useState(''); const [revealed, setRevealed] = useState(false);
  return <Card size="small" className="practice-card"><Paragraph><b>{exercise.question}</b></Paragraph>
    <Input.TextArea aria-label="我的练习答案" value={answer} onChange={e => setAnswer(e.target.value)} rows={3} placeholder="先写下自己的理解，再查看参考答案。" />
    <Button style={{ marginTop: 12 }} onClick={() => setRevealed(!revealed)}>{revealed ? '收起参考答案' : '查看参考答案'}</Button>
    {revealed && <><Paragraph className="campus-pre">参考答案：{exercise.answer}</Paragraph><Paragraph className="campus-pre">讲解：{exercise.explanation}</Paragraph>
      <Space wrap>{citations.filter(source => exercise.sources.includes(source.number)).map(source => <Source key={source.chunk_id} source={source} />)}</Space></>}
  </Card>;
}

function WebSources({ sources }: { sources: { title: string; url: string }[] }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = React.useId();
  return <div style={{ marginBottom: 12 }}>
    <Button size="small" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(!expanded)}>
      {expanded ? '收起网页来源' : '展开网页来源'}（{sources.length}）
    </Button>
    {expanded && <div id={contentId}><List size="small" dataSource={sources} renderItem={source => <List.Item><a style={{ overflowWrap: 'anywhere' }} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></List.Item>} /></div>}
  </div>;
}

function CourseDocumentDetails({ course, document, onClose }: { course?: string; document?: string; onClose: () => void }) {
  const [page, setPage] = useState(1);
  useEffect(() => { setPage(1); }, [course, document]);
  const detail = useQuery({ queryKey: ['course-document', course, document, page], queryFn: () => api(`/courses/${course}/documents/${document}?page=${page}`), enabled: !!course && !!document,
    refetchInterval: query => query.state.data?.versions?.some((version: any) => ['queued', 'parsing', 'chunking', 'embedding'].includes(version.status)) ? 2000 : false });
  const data = detail.data;
  const markdown = data?.content_format === 'markdown';
  return <Drawer title="课程资料详情" width="min(800px, 100vw)" open={!!document} onClose={onClose} destroyOnHidden>
    <ErrorNote error={detail.error} />{detail.isPending ? <Spin /> : data && <>
      <Title level={4}>{data.name}</Title>
      <Space wrap style={{ marginBottom: 16 }}><Tag color={data.source === 'ai' ? 'gold' : 'blue'}>{data.source === 'ai' ? 'AI 联网整理' : '上传资料'}</Tag>
        <Tag>{statusText[data.versions[0]?.status] || '待处理'}</Tag>{data.active_version_id && data.versions[0]?.status !== 'ready' && <Tag>正在显示已发布版本</Tag>}</Space>
      {data.versions[0]?.error && <Alert type="error" showIcon message={data.versions[0].error} style={{ marginBottom: 16 }} />}
      {data.preview ? <><DocumentContent key={document} content={data.preview} markdown={markdown} />{data.preview_truncated && <Paragraph type="secondary">导入完成前仅预览前 30000 字；导入完成后可分页查看全部内容。</Paragraph>}</> : data.chunks.length ? <>
        {data.chunks.map((chunk: any) => <div key={chunk.id}>{chunk.heading && !chunk.heading.endsWith('网页来源') && <Title level={5}>{chunk.heading}</Title>}
          {chunk.page && <Text type="secondary">第 {chunk.page} 页</Text>}<DocumentContent content={chunk.content} markdown={markdown} sourcesOnly={chunk.heading?.endsWith('网页来源')} /></div>)}
        <Pagination current={page} pageSize={20} showSizeChanger={false} total={data.chunk_total} onChange={setPage} />
      </> : <Empty description={data.versions[0]?.status === 'failed' ? '资料导入失败，请重试或重新上传。' : '资料正在导入，完成后会自动显示正文。'} />}
    </>}
  </Drawer>;
}

export function Study({ Source }: { Source: React.ComponentType<{ source: Citation }> }) {
  const client = useQueryClient(); const { message } = App.useApp();
  const [course, setCourse] = useState<string>(); const [coursePage, setCoursePage] = useState(1); const [docPage, setDocPage] = useState(1); const [historyPage, setHistoryPage] = useState(1);
  const [documentSource, setDocumentSource] = useState('uploaded'); const [deletingCourse, setDeletingCourse] = useState(false);
  const [courseModal, setCourseModal] = useState(false); const [courseName, setCourseName] = useState('');
  const [kind, setKind] = useState('question'); const [question, setQuestion] = useState(''); const [busy, setBusy] = useState(false); const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<unknown>(); const [result, setResult] = useState<any>();
  const [historyKind, setHistoryKind] = useState('question'); const [selectedRun, setSelectedRun] = useState<any>();
  const [selectedDocument, setSelectedDocument] = useState<string>();
  const [searchModal, setSearchModal] = useState(false); const [searchTopic, setSearchTopic] = useState(''); const [searchLimit, setSearchLimit] = useState<number>(3); const [searchSubmitting, setSearchSubmitting] = useState(false);
  useEffect(() => { setSelectedRun(undefined); setSelectedDocument(undefined); setQuestion(''); setSearchTopic(''); setSearchModal(false); setResult(undefined); setError(undefined); setDocPage(1); setHistoryPage(1); }, [course]);
  const courses = useQuery({ queryKey: ['courses', coursePage], queryFn: () => api('/courses?page=' + coursePage) });
  useEffect(() => { if (!course && courses.data?.items.length) setCourse(courses.data.items[0].id); }, [courses.data, course]);
  const documents = useQuery({ queryKey: ['course-documents', course, documentSource, docPage], queryFn: () => api(`/courses/${course}/documents?page=${docPage}&source=${documentSource}`), enabled: !!course, refetchInterval: course ? 3000 : false });
  const history = useQuery({ queryKey: ['study-history', course, historyKind, historyPage], queryFn: () => api(`/courses/${course}/study?page=${historyPage}&kind=${historyKind}`), enabled: !!course });
  const materialSearch = useQuery({ queryKey: ['material-search', course], queryFn: () => api(`/courses/${course}/material-search`), enabled: !!course, refetchInterval: query => ['queued', 'generating', 'importing'].includes(query.state.data?.job?.status) ? 2000 : false });
  const searchJob = materialSearch.data?.job;
  const searching = ['queued', 'generating', 'importing'].includes(searchJob?.status);
  useEffect(() => { if (searchJob?.generated) void client.invalidateQueries({ queryKey: ['course-documents', course] }); }, [searchJob?.generated, searchJob?.ready, searchJob?.failed, course, client]);
  const refresh = () => { void client.invalidateQueries({ queryKey: ['course-documents'] }); void client.invalidateQueries({ queryKey: ['course-document'] }); void client.invalidateQueries({ queryKey: ['study-history'] }); };
  const upload = async (file: File, id?: string) => {
    setUploading(true); const body = new FormData(); body.append('file', file);
    try { await api(`/courses/${course}/documents${id ? '/' + id + '/versions' : ''}`, { method: 'POST', body }); if (!id) { setDocumentSource('uploaded'); setDocPage(1); } refresh(); message.success('资料已接收，后台正在导入'); }
    catch (e) { message.error((e as Error).message); } finally { setUploading(false); }
  };
  const showRun = (run: any) => <div><Space wrap><Tag>{run.kind === 'question' ? '资料问答' : run.kind === 'outline' ? '复习提纲' : '练习题'}</Tag><Tag color={run.model_mode === 'mock' ? 'gold' : 'cyan'}>{run.model_mode === 'mock' ? '模拟模式' : '真实模型'}</Tag><Text type="secondary">{date(run.created_at)}</Text></Space>
    <Title level={5}>{run.question}</Title>
    {run.answer_kind === 'web' && <Alert style={{ marginBottom: 12 }} type="warning" showIcon message="本回答未来自课程知识库，仅供参考" description="课程资料中没有足够依据，以下内容由 AI 联网搜索后整理，请核对网页来源。" />}
    <Paragraph className="campus-pre">{run.content}</Paragraph>
    {run.answer_kind === 'web' && <WebSources key={run.id} sources={run.web_sources || []} />}
    <Space wrap>{run.citations.map((source: Citation) => <Source key={source.chunk_id} source={source} />)}</Space>
    {run.exercises.map((exercise: any, index: number) => <Practice key={run.id + '-' + index} exercise={exercise} citations={run.citations} Source={Source} />)}</div>;
  return <><div className="page-heading"><div className="eyebrow">PERSONAL LEARNING</div><Title level={2}>学习资料助手</Title>
    <Paragraph type="secondary">按课程整理个人资料，带引用问答、生成复习提纲与练习题。资料仅本人可见。</Paragraph></div>
    <Alert style={{ marginBottom: 20 }} type="info" showIcon message="提纲和练习只依据本次选取的资料片段，不保证覆盖整门课程；请核对引用和参考答案。" />
    <ErrorNote error={courses.error} /><Card style={{ marginBottom: 20 }}><div className="table-toolbar"><Space wrap><Select aria-label="选择课程" placeholder="选择课程" disabled={busy || uploading || deletingCourse} value={course} style={{ width: 240 }} onChange={value => { setCourse(value); setDocPage(1); setHistoryPage(1); setResult(undefined); setError(undefined); }} options={(courses.data?.items || []).map((row: any) => ({ value: row.id, label: row.name }))} />
      <Button icon={<PlusOutlined aria-hidden="true" />} disabled={busy || uploading} onClick={() => setCourseModal(true)}>新建课程</Button>
      <Popconfirm title="确认删除这门课程？" description="课程中的上传资料、AI 搜索资料和学习记录将一并删除，进行中的资料任务会终止。" okText="删除课程" cancelText="取消" okButtonProps={{ danger: true }} disabled={!course || busy || uploading || searchSubmitting || deletingCourse} onConfirm={async () => {
        if (!course) return;
        const deletedCourse = course;
        setDeletingCourse(true); setBusy(true);
        try {
          await api(`/courses/${deletedCourse}`, { method: 'DELETE' });
          client.setQueriesData({ queryKey: ['courses'] }, (old: any) => old ? { ...old, items: old.items.filter((row: any) => row.id !== deletedCourse), total: Math.max(0, old.total - 1) } : old);
          for (const key of ['course-documents', 'course-document', 'study-history', 'material-search']) client.removeQueries({ predicate: query => query.queryKey[0] === key && query.queryKey[1] === deletedCourse });
          setCourse(undefined); setCoursePage(1); setSelectedRun(undefined); setSelectedDocument(undefined); setResult(undefined); setQuestion(''); setDocPage(1); setHistoryPage(1);
          await client.invalidateQueries({ queryKey: ['courses'] });
          message.success('课程及相关资料、学习记录已删除');
        } catch (e) { message.error((e as Error).message); }
        finally { setDeletingCourse(false); setBusy(false); }
      }}><Button danger icon={<DeleteOutlined aria-hidden="true" />} loading={deletingCourse} disabled={!course || busy || uploading || searchSubmitting || deletingCourse}>删除课程</Button></Popconfirm>
      <Upload accept=".md,.txt,.docx,.pdf" showUploadList={false} disabled={!course || busy || uploading} beforeUpload={file => { void upload(file); return false; }}><Button icon={<UploadOutlined aria-hidden="true" />} disabled={!course || busy} loading={uploading}>上传学习资料</Button></Upload>
      <Button aria-label="搜索课程资料" icon={<SearchOutlined aria-hidden="true" />} loading={searching || searchSubmitting} disabled={!course || busy || uploading || searching || searchSubmitting || materialSearch.isPending || !!materialSearch.error} onClick={() => setSearchModal(true)}>搜索课程资料</Button></Space></div>
      <ErrorNote error={materialSearch.error} />
      {searchJob && <Alert style={{ marginBottom: 16 }} showIcon type={searchJob.status === 'failed' ? 'error' : searchJob.status === 'partial' ? 'warning' : searchJob.status === 'complete' ? 'success' : 'info'}
        message={searchJob.status === 'queued' ? '搜索任务已提交，等待后台处理' : searchJob.status === 'generating' ? `AI 正在联网搜索并整理资料，本次最多 ${searchJob.limit} 份${searchJob.generated ? `；已存入 ${searchJob.generated} 份，已导入 ${searchJob.ready} 份` : ''}` : searchJob.status === 'importing' ? `已存入 ${searchJob.generated} 份资料，导入进度 ${searchJob.ready + searchJob.failed}/${searchJob.generated}` : searchJob.status === 'complete' ? `本次已生成并导入 ${searchJob.ready} 份资料，可再次搜索生成更多` : '课程资料生成或导入遇到问题'}
        description={searchJob.error || (searching ? '任务在后台继续处理，离开或刷新页面后可查看进度。' : 'AI 联网整理的内容仅供学习参考，请核对资料中的网页来源。')} />}
      {(courses.data?.total || 0) > 20 && <Pagination current={coursePage} total={courses.data.total} pageSize={20} showSizeChanger={false} onChange={value => { setCoursePage(value); setCourse(undefined); }} />}
      <Radio.Group aria-label="资料来源" optionType="button" buttonStyle="solid" style={{ marginBottom: 16 }} value={documentSource} onChange={e => { setDocumentSource(e.target.value); setDocPage(1); }} options={[{ value: 'uploaded', label: '上传资料' }, { value: 'ai', label: 'AI 搜索资料' }]} />
      {course && documentSource === 'ai' && <MaterialOrganization key={course} course={course} disabled={busy || uploading || searching} onDocument={setSelectedDocument} />}
      <ErrorNote error={documents.error} />{course ? <><Table<any> rowKey="id" size="small" loading={documents.isFetching} dataSource={documents.data?.items || []} pagination={false} scroll={{ x: 560 }} locale={{ emptyText: documentSource === 'uploaded' ? '暂无上传资料，点击“上传学习资料”添加课件或笔记。' : '暂无 AI 搜索资料，点击“搜索课程资料”联网整理。' }} columns={[
        { title: '资料', render: (_, row) => <Button type="link" style={{ padding: 0, height: 'auto', whiteSpace: 'normal', textAlign: 'left' }} onClick={() => setSelectedDocument(row.id)}>{row.name}</Button> }, { title: '导入状态', render: (_, row) => <><Tag color={row.versions[0]?.status === 'ready' ? 'green' : row.versions[0]?.status === 'failed' ? 'red' : 'blue'}>{statusText[row.versions[0]?.status] || '待处理'}</Tag>{row.active_version_id && row.versions[0]?.status !== 'ready' && <Tag>旧版本可用</Tag>}{row.versions[0]?.error && <Text type="danger">{row.versions[0].error}</Text>}</> },
        { title: '操作', render: (_, row) => <Space><Button size="small" onClick={() => setSelectedDocument(row.id)}>查看详情</Button><Upload accept=".md,.txt,.docx,.pdf" showUploadList={false} disabled={busy || uploading} beforeUpload={file => { void upload(file, row.id); return false; }}><Button size="small" disabled={busy || uploading}>更新</Button></Upload>
          {row.versions[0]?.status === 'failed' && <Button size="small" disabled={busy} onClick={async () => { try { await api(`/courses/${course}/documents/${row.id}/retry`, { method: 'POST' }); refresh(); } catch (e) { message.error((e as Error).message); } }}>重试</Button>}
          <Popconfirm title="删除后资料退出检索，引用它的历史结果将失效。" onConfirm={async () => { try { await api(`/courses/${course}/documents/${row.id}`, { method: 'DELETE' }); setResult(undefined); refresh(); } catch (e) { message.error((e as Error).message); } }}><Button danger size="small" disabled={busy || uploading}>删除</Button></Popconfirm></Space> },
      ]} /><Pagination current={docPage} pageSize={20} showSizeChanger={false} total={documents.data?.total || 0} onChange={setDocPage} /></> : <Empty description="先创建一门课程，再上传学习资料。" />}
    </Card>
    <Card title="基于课程资料学习" style={{ marginBottom: 20 }}><Space wrap style={{ marginBottom: 16 }}><Radio.Group aria-label="学习任务" optionType="button" buttonStyle="solid" disabled={busy} value={kind} onChange={e => { setKind(e.target.value); setQuestion(''); }} options={[{ value: 'question', label: '资料问答' }, { value: 'outline', label: '复习提纲' }, { value: 'practice', label: '练习题' }]} /></Space>
      {kind === 'question' && <Paragraph type="secondary">优先根据课程资料回答；资料不足时自动联网搜索，并展示网页来源和参考提示。</Paragraph>}
      <Input.TextArea aria-label="学习问题或主题" disabled={busy || !course} value={question} onChange={e => setQuestion(e.target.value)} maxLength={4000} rows={3} placeholder={kind === 'question' ? '例如：什么是数据库事务？请结合资料解释。' : '可填写复习主题；留空时从已发布资料中选择片段整理。'} />
      <Button style={{ marginTop: 16 }} type="primary" loading={busy} disabled={!course || (kind === 'question' && !question.trim())} onClick={async () => {
        setBusy(true); setError(undefined); setResult(undefined);
        try { const run = await api(`/courses/${course}/study`, post({ kind, content: question })); setResult(run); setQuestion(''); setHistoryKind(kind); setHistoryPage(1); refresh(); }
        catch (e) { setError(e); } finally { setBusy(false); }
      }}>{kind === 'question' ? '根据资料回答' : kind === 'outline' ? '生成复习提纲' : '生成练习题'}</Button>
      <div style={{ marginTop: 20 }}><ErrorNote error={error} />{result && showRun(result)}</div>
    </Card><Card title="学习记录">
      <Radio.Group aria-label="学习记录分类" optionType="button" buttonStyle="solid" style={{ marginBottom: 16 }} value={historyKind} onChange={e => { setHistoryKind(e.target.value); setHistoryPage(1); }} options={[{ value: 'question', label: '回复' }, { value: 'outline', label: '摘要' }, { value: 'practice', label: '练习题' }]} />
      <ErrorNote error={history.error} /><List loading={history.isFetching} dataSource={history.data?.items || []} locale={{ emptyText: '该分类暂无学习记录' }} renderItem={(run: any) => <List.Item>
        <div style={{ minWidth: 0, width: '100%' }}><Button type="link" style={{ padding: 0, maxWidth: '100%', height: 'auto', whiteSpace: 'normal', textAlign: 'left' }} onClick={() => setSelectedRun(run)}>{run.question.length > 100 ? run.question.slice(0, 100) + '…' : run.question}</Button>
          <div><Text type="secondary">{date(run.created_at)}</Text>{run.answer_kind === 'web' && <Tag style={{ marginLeft: 8 }} color="gold">联网参考</Tag>}</div>
        </div></List.Item>} />
      <Pagination current={historyPage} pageSize={20} showSizeChanger={false} total={history.data?.total || 0} onChange={setHistoryPage} /></Card>
    <Drawer title="学习记录详情" width="min(720px, 100vw)" open={!!selectedRun} onClose={() => setSelectedRun(undefined)} destroyOnHidden>{selectedRun && showRun(selectedRun)}</Drawer>
    <CourseDocumentDetails course={course} document={selectedDocument} onClose={() => setSelectedDocument(undefined)} />
    <Modal title="搜索课程资料" open={searchModal} confirmLoading={searchSubmitting} okText="开始搜索并存入" cancelText="取消" onCancel={() => setSearchModal(false)} onOk={async () => {
      if (!course || searching || searchSubmitting) return;
      const selectedCourse = course;
      setSearchSubmitting(true);
      try {
        const job = await api(`/courses/${selectedCourse}/material-search`, post({ topic: searchTopic, limit: searchLimit }));
        client.setQueryData(['material-search', selectedCourse], { job });
        setSearchModal(false); setDocumentSource('ai'); setDocPage(1); message.success('已提交后台搜索任务');
      } catch (e) { message.error((e as Error).message); }
      finally { setSearchSubmitting(false); }
    }}>
      <Paragraph>AI 按完整主题或章节整理相关知识点，每份目标约 800～1600 字。默认最多 3 份，每批最多整理 3 份并逐批存入；一次最多 10 份，需要更多时可再次生成。</Paragraph>
      <Form layout="vertical">
        <Form.Item label="搜索主题（可不填）"><Input aria-label="搜索资料主题" value={searchTopic} onChange={e => setSearchTopic(e.target.value)} maxLength={300} placeholder="例如：事务与并发控制；留空时搜索课程核心知识点" disabled={searchSubmitting} /></Form.Item>
        <Form.Item label="本次最多生成份数"><InputNumber aria-label="生成资料份数" min={1} max={10} precision={0} value={searchLimit} onChange={value => setSearchLimit(value ?? 3)} disabled={searchSubmitting} /></Form.Item>
      </Form>
      <Text type="secondary">根据可用网页依据生成，实际份数可能少于设定上限；已生成的同名资料会跳过。</Text>
    </Modal>
    <Modal title="新建个人课程" open={courseModal} okText="创建课程" onCancel={() => setCourseModal(false)} onOk={async () => {
      if (!courseName.trim()) { message.warning('请输入课程名称'); return; }
      try { const row = await api('/courses', post({ name: courseName })); await client.invalidateQueries({ queryKey: ['courses'] }); setCourse(row.id); setDocPage(1); setHistoryPage(1); setResult(undefined); setCourseModal(false); setCourseName(''); }
      catch (e) { message.error((e as Error).message); }
    }}><Input aria-label="课程名称" maxLength={120} value={courseName} onChange={e => setCourseName(e.target.value)} placeholder="例如：数据库原理" /></Modal>
  </>;
}
