export class ApiError extends Error {
  constructor(message: string, public status: number, public code = '') { super(message); }
}
export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch('/api/v1' + path, { ...options, headers, credentials: 'same-origin' });
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.message || '请求失败', response.status, data.code);
  return data;
}
export const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export async function streamAnswer(id: string, content: string, signal: AbortSignal,
  onEvent: (event: string, data: any) => void) {
  const response = await fetch(`/api/v1/conversations/${id}/messages`, {
    ...post({ content }), headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', signal,
  });
  if (!response.ok) { const error = await response.json(); throw new Error(error.message); }
  if (!response.body) throw new Error('浏览器不支持流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  const consume = (frame: string) => {
    let event = 'message';
    const data: string[] = [];
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) data.push(line.slice(5).trim());
    }
    if (data.length) { if (event === 'done') completed = true; onEvent(event, JSON.parse(data.join('\n'))); }
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) { consume(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); }
      if (done) break;
    }
    if (!completed) throw new Error('连接中断，请刷新会话后重试');
  } finally { reader.releaseLock(); }
}

export function date(value?: string) {
  return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) : '—';
}
export const statusText: Record<string, string> = { open: '新建', in_progress: '处理中', awaiting_student: '待补充',
  resolved: '已解决', closed: '已关闭', queued: '排队中', parsing: '解析中', chunking: '分块中',
  embedding: '向量化中', ready: '已发布', failed: '失败', interrupted: '已中断', pending: '处理中', complete: '完成' };
