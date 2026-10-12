import { useState } from 'react';
import { Button } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function Markdown({ content }: { content: string }) {
  return <div className="document-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: ({ alt }) => <span>{alt || '图片'}</span>,
  }}>{content}</ReactMarkdown></div>;
}

export function DocumentContent({ content, markdown, sourcesOnly = false }: { content: string; markdown: boolean; sourcesOnly?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  if (!markdown) return <div className="campus-pre">{content}</div>;
  // Generated materials append a dedicated sources section. Keep it after the body and folded.
  const sourceHeading = /^##\s+网页来源\s*$/m.exec(content);
  const body = sourcesOnly ? '' : sourceHeading ? content.slice(0, sourceHeading.index) : content;
  const sources = sourcesOnly ? content : sourceHeading ? content.slice(sourceHeading.index + sourceHeading[0].length) : '';
  return <>
    {body && <Markdown content={body} />}
    {sources && <div className="document-sources">
      <Button size="small" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起网页来源' : '展开网页来源'}</Button>
      {expanded && <Markdown content={sources} />}
    </div>}
  </>;
}
