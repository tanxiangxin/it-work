import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Alert, Button, Calendar, Input, Modal, Typography } from 'antd';
import { CalendarOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import calendarLocale from 'antd/es/calendar/locale/zh_CN';
import 'dayjs/locale/zh-cn';

const units = ['年', '月', '日', '时', '分'];
const split = (value?: string) => value ? value.split(/[-T:]/) : ['', '', '', '', ''];
const join = (parts: string[]) => parts.every(p => !p) ? undefined : `${parts[0]}-${parts[1]}-${parts[2]}T${parts[3]}:${parts[4]}`;

// Validate before Date conversion: JavaScript otherwise silently normalizes February 30.
export function normalizeTodoTime(value?: string): string | undefined {
  if (!value) return undefined;
  const parts = split(value);
  if (parts.length !== 5 || parts.some(p => !/^\d+$/.test(p))) throw new Error('请完整填写年、月、日、时、分，或清空时间。');
  const [year, month, day, hour, minute] = parts.map(Number);
  if (year < 1900 || year > 9999 || month < 1 || month > 12 || day < 1 ||
      day > new Date(Date.UTC(year, month, 0)).getUTCDate() || hour > 23 || minute > 59) {
    throw new Error('请输入有效日期和时间（时：0–23，分：0–59）。');
  }
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function Parts({ value, onChange, label, disabled }: { value?: string; onChange: (value?: string) => void; label: string; disabled?: boolean }) {
  const parts = split(value);
  return <div className="todo-time-parts">{units.map((unit, index) => <label key={unit}>
    <span>{unit}</span><Input aria-label={`${label}${unit}`} inputMode="numeric" placeholder={index === 0 ? 'YYYY' : index < 3 ? (index === 1 ? 'MM' : 'DD') : index === 3 ? 'hh' : 'mm'}
      maxLength={index === 0 ? 4 : 2} value={parts[index]} disabled={disabled}
      onChange={e => { const next = [...parts]; next[index] = e.target.value.replace(/\D/g, ''); onChange(join(next)); }} />
  </label>)}</div>;
}

function TimeWheel({ value, count, label, active, onChange }: { value: number; count: number; label: string; active: boolean; onChange: (value: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const scrolling = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const id = useId();
  useLayoutEffect(() => {
    if (!active) { scrolling.current = false; clearTimeout(timer.current); }
    // Hidden modal content has no scroll height; position only after it becomes visible.
    if (active && ref.current && !scrolling.current) ref.current.scrollTop = value * 40;
  }, [value, active]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const choose = (next: number) => {
    clearTimeout(timer.current);
    scrolling.current = false;
    if (ref.current) { ref.current.scrollTop = next * 40; ref.current.focus(); }
    onChange(next);
  };
  return <div className="todo-time-wheel-group"><span className="todo-time-wheel-label">{label.endsWith('时') ? '小时' : '分钟'}</span>
    <div className="todo-time-wheel-frame">
      <div ref={ref} className="todo-time-wheel" role="listbox" aria-label={label} tabIndex={0}
        aria-activedescendant={`${id}-${value}`} onScroll={event => {
          if (!active) return;
          scrolling.current = true;
          const next = Math.max(0, Math.min(count - 1, Math.round(event.currentTarget.scrollTop / 40)));
          onChange(next);
          clearTimeout(timer.current);
          timer.current = setTimeout(() => { scrolling.current = false; }, 150);
        }} onKeyDown={event => {
          const next = event.key === 'ArrowDown' ? Math.min(count - 1, value + 1) : event.key === 'ArrowUp' ? Math.max(0, value - 1) : event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : undefined;
          if (next !== undefined) { event.preventDefault(); choose(next); }
        }}>
        {Array.from({ length: count }, (_, index) => <button key={index} id={`${id}-${index}`} type="button" role="option"
          aria-selected={index === value} tabIndex={-1} className={index === value ? 'is-selected' : ''}
          onClick={() => choose(index)}>{String(index).padStart(2, '0')}</button>)}
      </div>
    </div>
  </div>;
}

export function TodoTimeInput({ value, onChange, label, disabled }: { value?: string; onChange?: (value?: string) => void; label: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string>();
  const [error, setError] = useState<string>();
  const [panel, setPanel] = useState(dayjs());
  const [wheelsReady, setWheelsReady] = useState(false);
  let selected;
  try { selected = dayjs(normalizeTodoTime(draft)).locale('zh-cn'); } catch { selected = dayjs().locale('zh-cn'); }
  const launch = () => {
    let initial;
    try { initial = normalizeTodoTime(value); } catch { /* Incomplete manual input can be corrected in the picker. */ }
    const now = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date()).replace(' ', 'T');
    setWheelsReady(false); setDraft(initial || now); setPanel(dayjs(initial || now).locale('zh-cn')); setError(undefined); setOpen(true);
  };
  return <div className="todo-time-control">
    <Parts value={value} onChange={next => onChange?.(next)} label={label} disabled={disabled} />
    <div className="todo-time-actions"><Button icon={<CalendarOutlined aria-hidden="true" />} aria-label={`选择${label}`} disabled={disabled} onClick={launch}>日历选择</Button>
      <Button type="text" disabled={disabled || !value} onClick={() => onChange?.(undefined)} aria-label={`清空${label}`}>清空时间</Button></div>
    <Modal title={`选择${label}（北京时间）`} open={open} afterOpenChange={setWheelsReady} onCancel={() => setOpen(false)} okText="确认时间" cancelText="取消选择" width={480} style={{ top: 24 }} destroyOnHidden onOk={() => {
      try { onChange?.(normalizeTodoTime(draft)); setOpen(false); } catch (e) { setError((e as Error).message); }
    }}>
      <Typography.Paragraph type="secondary">选择日期和时分，确认后返回待办编辑；保存待办后才会生效。</Typography.Paragraph>
      <Calendar locale={calendarLocale} fullscreen={false} value={panel} headerRender={({ value: month, onChange: changeMonth }) =>
        <div className="todo-calendar-header">
          <Button type="text" icon={<LeftOutlined />} aria-label="上个月" onClick={() => changeMonth(month.subtract(1, 'month'))} />
          <Typography.Text strong aria-live="polite">{month.format('YYYY年M月')}</Typography.Text>
          <Button type="text" icon={<RightOutlined />} aria-label="下个月" onClick={() => changeMonth(month.add(1, 'month'))} />
        </div>} onSelect={(date, info) => {
        if (info.source === 'date') { const parts = split(draft); onChangeDraft(`${date.format('YYYY-MM-DD')}T${parts[3]}:${parts[4]}`); }
        setPanel(date);
      }} onPanelChange={date => setPanel(date)} />
      <div className="todo-time-selection">
        <Typography.Text type="secondary">{selected.format('YYYY年M月D日')} · 滚动选择时间</Typography.Text>
        <div className="todo-time-wheels">
          <TimeWheel label={`选择${label}时`} value={selected.hour()} count={24} active={wheelsReady} onChange={hour => changeTime(3, hour)} />
          <span className="todo-time-separator" aria-hidden="true">:</span>
          <TimeWheel label={`选择${label}分`} value={selected.minute()} count={60} active={wheelsReady} onChange={minute => changeTime(4, minute)} />
        </div>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
    </Modal>
  </div>;
  function onChangeDraft(next?: string) { setDraft(next); setError(undefined); }
  function changeTime(index: number, next: number) {
    setDraft(current => { const parts = split(current); parts[index] = String(next).padStart(2, '0'); return join(parts); });
    setError(undefined);
  }
}
