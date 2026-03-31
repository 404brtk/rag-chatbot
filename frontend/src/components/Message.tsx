import { useState, useRef, useLayoutEffect } from 'react';
import type { ReactNode } from 'react';
import './Message.css';

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: ReactNode;
}

interface MessageProps {
  message: ChatMessage;
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';
  const contentRef = useRef<HTMLDivElement>(null);
  const [isCollapsible, setIsCollapsible] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useLayoutEffect(() => {
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
  }, [message.content]);

  return (
    <div className={`message-wrapper ${isUser ? 'message-user' : 'message-ai'}`}>
      <div className="message-content">
        <div className="message-body">
          <div
            ref={contentRef}
            className={`message-body-inner ${isCollapsible && !isExpanded ? 'is-collapsed' : ''}`}
          >
            {message.content}
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
