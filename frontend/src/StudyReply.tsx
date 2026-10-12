import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function replyMarkdown(content: string) {
  // Some models wrap the entire prose reply in a Markdown/text fence.
  // Keep genuine Java/SQL/code fences and their symbols intact.
  const trimmed = content.trim();
  const wrapper = /^```(?:markdown|md|text)\s*\n([\s\S]*)\n```$/i.exec(trimmed);
  return wrapper ? wrapper[1] : content;
}

export function StudyReply({ content }: { content: string }) {
  return <div className="study-reply"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: ({ alt }) => <span>{alt || '图片说明'}</span>,
    table: ({ children }) => <div className="study-reply-table" role="region" aria-label="回复表格" tabIndex={0}><table>{children}</table></div>,
  }}>{replyMarkdown(content)}</ReactMarkdown></div>;
}
