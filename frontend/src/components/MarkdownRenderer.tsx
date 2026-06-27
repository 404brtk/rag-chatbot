import React, { useState, useRef, useMemo } from 'react';
import { marked } from 'marked';
import { Citation } from './Citation';
import { Icon } from './Icon';
import './MarkdownRenderer.css';

interface CodeBlockProps {
  code: string;
  lang?: string;
}

function CodeBlock({ code, lang }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<number | undefined>(undefined);

  const lines = code.split('\n');
  let displayCode = code;
  let filename: string | null = null;

  if (lines.length > 0) {
    const firstLine = lines[0].trim();
    const match = /^(?:\/\/|#|<!--|\/\*)\s*([\w\-./\\]+\.[a-zA-Z0-9]+)\s*(?:\*\/|-->)?$/.exec(
      firstLine
    );
    if (match) {
      filename = match[1];
      displayCode = lines.slice(1).join('\n');
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(displayCode);
      setCopied(true);
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy code to clipboard:', err);
    }
  };

  return (
    <div className="code-block-container">
      <div className="code-block-header">
        <span className="code-block-lang">
          {lang ? lang.toLowerCase() : 'code'}
          {filename && <span className="code-block-filename"> • {filename}</span>}
        </span>
        <button
          type="button"
          className={`code-block-copy-btn ${copied ? 'copied' : ''}`}
          onClick={handleCopy}
        >
          <Icon name={copied ? 'check' : 'copy'} size={12} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code-block-body">
        <code>{displayCode}</code>
      </pre>
    </div>
  );
}

interface CustomMarkedToken {
  type: string;
  text?: string;
  lang?: string;
  tokens?: CustomMarkedToken[];
  depth?: number;
  ordered?: boolean;
  start?: number | '';
  items?: { tokens: CustomMarkedToken[] }[];
  align?: ('center' | 'left' | 'right' | null)[];
  header?: { text: string; tokens?: CustomMarkedToken[] }[];
  rows?: { text: string; tokens?: CustomMarkedToken[] }[][];
  href?: string;
  title?: string | null;
}

interface MarkdownRendererProps {
  content: string;
  citations?: {
    id: string | number;
    sourceName: string;
    snippet: string;
  }[];
}

export function MarkdownRenderer({ content, citations }: MarkdownRendererProps) {
  const citationMap = new Map(citations?.map((c) => [String(c.id), c]) ?? []);

  const renderTextWithCitations = (text: string): React.ReactNode => {
    const regex = /\[(\d+)\]/g;
    let lastIndex = 0;
    let match;
    const parts: React.ReactNode[] = [];

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }
      const citId = match[1];
      const citation = citationMap.get(citId);
      if (citation) {
        parts.push(
          <Citation
            key={`cit-${citId}-${match.index}`}
            id={citation.id}
            sourceName={citation.sourceName}
            snippet={citation.snippet}
          />
        );
      } else {
        parts.push(match[0]);
      }
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex));
    }

    return parts.length > 0 ? <>{parts}</> : text;
  };

  const renderTokens = (tokens?: CustomMarkedToken[]): React.ReactNode[] => {
    if (!tokens) return [];
    return tokens.map((token, idx) => {
      const key = `${token.type}-${idx}`;
      switch (token.type) {
        case 'heading': {
          const depth = token.depth;
          const children = renderTokens(token.tokens);
          if (depth === 1) return <h1 key={key}>{children}</h1>;
          if (depth === 2) return <h2 key={key}>{children}</h2>;
          if (depth === 3) return <h3 key={key}>{children}</h3>;
          if (depth === 4) return <h4 key={key}>{children}</h4>;
          if (depth === 5) return <h5 key={key}>{children}</h5>;
          return <h6 key={key}>{children}</h6>;
        }
        case 'paragraph':
          return <p key={key}>{renderTokens(token.tokens)}</p>;
        case 'blockquote':
          return <blockquote key={key}>{renderTokens(token.tokens)}</blockquote>;
        case 'list': {
          const Tag = token.ordered ? 'ol' : 'ul';
          const start =
            token.ordered && token.start !== undefined && token.start !== ''
              ? token.start
              : undefined;
          return (
            <Tag key={key} start={start}>
              {(token.items || []).map((item, i: number) => (
                <li key={`li-${i}`}>{renderTokens(item.tokens)}</li>
              ))}
            </Tag>
          );
        }
        case 'code':
          return <CodeBlock key={key} code={token.text || ''} lang={token.lang} />;
        case 'table':
          return (
            <div key={key} className="table-container">
              <table>
                <thead>
                  <tr>
                    {(token.header || []).map((cell, i: number) => (
                      <th
                        key={`th-${i}`}
                        style={{ textAlign: (token.align || [])[i] || undefined }}
                      >
                        {cell.tokens ? renderTokens(cell.tokens) : cell.text}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(token.rows || []).map((row, rowIndex: number) => (
                    <tr key={`tr-${rowIndex}`}>
                      {row.map((cell, colIndex: number) => (
                        <td
                          key={`td-${rowIndex}-${colIndex}`}
                          style={{ textAlign: (token.align || [])[colIndex] || undefined }}
                        >
                          {cell.tokens ? renderTokens(cell.tokens) : cell.text}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        case 'space':
          return null;
        case 'hr':
          return <hr key={key} />;
        case 'br':
          return <br key={key} />;
        case 'strong':
          return (
            <strong key={key}>{token.tokens ? renderTokens(token.tokens) : token.text}</strong>
          );
        case 'em':
          return <em key={key}>{token.tokens ? renderTokens(token.tokens) : token.text}</em>;
        case 'codespan':
          return (
            <code key={key} className="inline-code">
              {token.text}
            </code>
          );
        case 'del':
          return <del key={key}>{token.tokens ? renderTokens(token.tokens) : token.text}</del>;
        case 'link':
          return (
            <a
              key={key}
              href={token.href}
              title={token.title || undefined}
              target="_blank"
              rel="noopener noreferrer"
            >
              {token.tokens ? renderTokens(token.tokens) : token.text}
            </a>
          );
        case 'image':
          return (
            <img key={key} src={token.href} alt={token.text} title={token.title || undefined} />
          );
        case 'text':
          return token.tokens ? (
            <React.Fragment key={key}>{renderTokens(token.tokens)}</React.Fragment>
          ) : (
            <React.Fragment key={key}>{renderTextWithCitations(token.text || '')}</React.Fragment>
          );
        case 'escape':
          return <React.Fragment key={key}>{token.text || ''}</React.Fragment>;
        default:
          if (token.tokens) {
            return <React.Fragment key={key}>{renderTokens(token.tokens)}</React.Fragment>;
          }
          return <React.Fragment key={key}>{token.text || ''}</React.Fragment>;
      }
    });
  };

  const tokens = useMemo(() => marked.lexer(content), [content]);
  return <div className="markdown-body">{renderTokens(tokens)}</div>;
}
