import { createContext, useContext, useEffect, useState } from 'react';
import { Alert, Button, Space } from 'antd';
import type { FormInstance } from 'antd';

export const DraftAccount = createContext('');
type Entry<T> = { values: T; savedAt: string };
const ttl = 30 * 24 * 60 * 60 * 1000;

export function useDraft<T>(scope: string, active = true, validate?: (values: unknown) => boolean) {
  const userId = useContext(DraftAccount);
  const key = `campus-draft:v1:${userId}:${scope}`;
  const read = (): Entry<T> | undefined => {
    if (!active || !userId) return;
    try {
      const entry = JSON.parse(localStorage.getItem(key) || 'null');
      if (!entry || typeof entry !== 'object' || typeof entry.savedAt !== 'string' || !Object.hasOwn(entry, 'values')
        || !Number.isFinite(Date.parse(entry.savedAt)) || Date.now() - Date.parse(entry.savedAt) > ttl
        || (validate && !validate(entry.values))) return;
      return entry;
    } catch { return; }
  };
  const [entry, setEntry] = useState<Entry<T> | undefined>(read);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => { setEntry(read()); setUnavailable(false); }, [key, active]);
  const save = (values: T) => {
    if (!active || !userId) return;
    const next = { values, savedAt: new Date().toISOString() };
    try {
      localStorage.setItem(key, JSON.stringify(next, (_, value) => value === undefined ? null : value));
      setEntry(next); setUnavailable(false);
    } catch { setUnavailable(true); }
  };
  const clear = () => {
    try { localStorage.removeItem(key); setEntry(undefined); } catch { setUnavailable(true); }
  };
  return { entry, save, clear, unavailable };
}

export function useFormDraft(scope: string, form: FormInstance, active: boolean) {
  const draft = useDraft<Record<string, unknown>>(scope, active, values => !!values && typeof values === 'object' && !Array.isArray(values));
  const [pending, setPending] = useState(false);
  useEffect(() => { setPending(!!draft.entry); }, [scope, active]);
  // Entry loading follows the account/scope effect; allow restoration until the first edit.
  const [edited, setEdited] = useState(false);
  useEffect(() => { setEdited(false); }, [scope, active]);
  const save = () => { setEdited(true); setPending(false); draft.save(form.getFieldsValue(true)); };
  const restore = () => { if (draft.entry) form.setFieldsValue(draft.entry.values); setEdited(true); setPending(false); };
  return { ...draft, save, restore, pending: !edited && (!!draft.entry || pending) };
}

export function DraftNote({ draft }: { draft: ReturnType<typeof useFormDraft> }) {
  if (draft.unavailable) return <Alert type="warning" showIcon message="浏览器无法保存本地草稿，请勿关闭页面。" style={{ marginBottom: 16 }} />;
  if (!draft.entry) return null;
  return <Alert type="info" showIcon style={{ marginBottom: 16 }}
    message={draft.pending ? '发现未提交的本地草稿' : '输入已自动保存到本机草稿'}
    description="关闭或刷新后可恢复；草稿仅在当前浏览器保存，30 天后过期。"
    action={<Space wrap>{draft.pending && <Button size="small" onClick={draft.restore}>恢复草稿</Button>}
      <Button size="small" onClick={draft.clear}>清除本地草稿</Button></Space>} />;
}
