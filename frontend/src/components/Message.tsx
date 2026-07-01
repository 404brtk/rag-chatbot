import { useEffect, useState, useRef, useLayoutEffect } from 'react';
import './Message.css';
import { MarkdownRenderer } from './MarkdownRenderer';
import { Icon } from './Icon';
import type { ChatMessage } from '../types';

interface MessageProps {
  message: ChatMessage;
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';
  const contentRef = useRef<HTMLDivElement>(null);
  const copyResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isCollapsible, setIsCollapsible] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  useEffect(
    () => () => {
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current);
      }
    },
    []
  );

  const handleCopy = async () => {
    if (!navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(message.content);
      setIsCopied(true);

      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current);
      }

      copyResetTimeoutRef.current = setTimeout(() => {
        setIsCopied(false);
      }, 1000);
    } catch (err) {
      console.error('Failed to copy message content:', err);
    }
  };

  const handleImageClick = (content?: string, name?: string) => {
    if (!content) return;
    const newWindow = window.open();
    if (newWindow) {
      const doc = newWindow.document;
      doc.title = name || 'Image Preview';

      const style = doc.createElement('style');
      style.textContent = `
        body {
          margin: 0;
          background-color: #09090e;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
        }
        img {
          max-width: 100%;
          max-height: 100vh;
          object-fit: contain;
        }
      `;
      doc.head.appendChild(style);

      const img = doc.createElement('img');
      img.src = content;
      img.alt = name || 'Preview';
      doc.body.appendChild(img);
    }
  };

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
      <div className={`message-stack ${isUser ? 'message-stack-user' : 'message-stack-ai'}`}>
        {isUser && message.attachments && message.attachments.length > 0 && (
          <div className="message-attachments-container">
            {message.attachments.some((a) => a.kind !== 'image') && (
              <div className="message-attachment-list" role="list" aria-label="Message attachments">
                {message.attachments
                  .filter((a) => a.kind !== 'image')
                  .map((attachment) => (
                    <span className="message-attachment-chip" role="listitem" key={attachment.id}>
                      <span className="message-attachment-icon" aria-hidden>
                        <Icon name="file" size={12} />
                      </span>
                      <span className="message-attachment-name" title={attachment.name}>
                        {attachment.name}
                      </span>
                    </span>
                  ))}
              </div>
            )}

            {message.attachments.some((a) => a.kind === 'image') && (
              <div className="message-image-gallery">
                {message.attachments
                  .filter((a) => a.kind === 'image')
                  .map((attachment) => (
                    <div className="message-image-wrapper" key={attachment.id}>
                      <img
                        src={attachment.url || attachment.content}
                        alt={attachment.name}
                        className="message-image-preview"
                        onClick={() =>
                          handleImageClick(attachment.url || attachment.content, attachment.name)
                        }
                        title="Click to view full size"
                      />
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        <div className="message-content">
          <div className="message-body">
            {!isUser && message.is_compaction_summary && (
              <div className="message-compaction-header">COMPACTION SUMMARY</div>
            )}
            <div
              ref={contentRef}
              className={`message-body-inner ${isCollapsible && !isExpanded ? 'is-collapsed' : ''}`}
            >
              {message.content ? (
                <MarkdownRenderer content={message.content} citations={message.citations} />
              ) : (
                <div className="typing-indicator" aria-label="AI is thinking...">
                  <div className="typing-shape" />
                </div>
              )}
            </div>

            {isCollapsible && (
              <button
                className="message-collapse-toggle"
                onClick={() => setIsExpanded((prev) => !prev)}
                type="button"
              >
                {isExpanded ? 'Show less' : 'Read more'}
              </button>
            )}
          </div>
        </div>

        {message.content ? (
          <div className="message-actions">
            <button
              className={`message-copy-btn${isCopied ? ' copied' : ''}`}
              type="button"
              onClick={handleCopy}
              title={isCopied ? 'Copied' : 'Copy message'}
            >
              <Icon name={isCopied ? 'check' : 'copy'} size={14} />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
