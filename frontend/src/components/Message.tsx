import { useState, useRef, useLayoutEffect } from 'react';
import './Message.css';
import { Citation } from './Citation';
import type { ChatMessage } from '../types';

interface MessageProps {
  message: ChatMessage;
}

function renderContent(content: string, citations?: ChatMessage['citations']) {
  const paragraphs = content.split('\n').filter(Boolean);
  const citationMap = new Map(citations?.map((c) => [String(c.id), c]));

  return paragraphs.map((paragraph, i) => {
    const parts: React.ReactNode[] = [];
    const regex = /\[(\d+)\]/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(paragraph)) !== null) {
      if (match.index > lastIndex) {
        parts.push(paragraph.slice(lastIndex, match.index));
      }
      const citation = citationMap.get(match[1]);
      if (citation) {
        parts.push(
          <Citation
            key={`cit-${match[1]}`}
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

    parts.push(paragraph.slice(lastIndex));

    return <p key={i}>{parts}</p>;
  });
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';
  const contentRef = useRef<HTMLDivElement>(null);
  const [isCollapsible, setIsCollapsible] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useLayoutEffect(() => {
    if (!isUser) return;
    const el = contentRef.current;
    if (!el) return;

    const updateCollapsible = () => {
      const next = el.scrollHeight > 360;
      setIsCollapsible((prev) => (prev !== next ? next : prev));
    };

    updateCollapsible();

    const observer = new ResizeObserver(updateCollapsible);
    observer.observe(el);

    return () => observer.disconnect();
  }, [message.content, isUser]);

  return (
    <div className={`message-wrapper ${isUser ? 'message-user' : 'message-ai'}`}>
      <div className="message-content">
        <div className="message-body">
          <div
            ref={contentRef}
            className={`message-body-inner ${isCollapsible && !isExpanded ? 'is-collapsed' : ''}`}
          >
            {renderContent(message.content, message.citations)}
          </div>

          {isCollapsible && (
            <button
              className="message-collapse-toggle"
              onClick={() => setIsExpanded((prev) => !prev)}
            >
              {isExpanded ? 'Show less' : 'Read more'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
