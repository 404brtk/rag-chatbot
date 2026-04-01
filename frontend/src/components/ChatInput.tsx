import { useState, useRef, type ChangeEvent, type KeyboardEvent } from 'react';
import { Icon } from './Icon';
import './ChatInput.css';

interface ChatInputProps {
  placeholder?: string;
  onSend?: (message: string) => void;
  disabled?: boolean;
}

const MAX_HEIGHT = 200;

export function ChatInput({
  placeholder = 'Message...',
  onSend,
  disabled = false,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const hasMessage = message.trim().length > 0;
  const canSend = hasMessage && !disabled;

  const updateOverflow = (el: HTMLTextAreaElement) => {
    el.classList.toggle('has-overflow', el.scrollHeight > MAX_HEIGHT);
  };

  const resetTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    updateOverflow(el);
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
    updateOverflow(el);
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    adjustHeight();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    if (!canSend) return;
    onSend?.(message.trim());
    setMessage('');
    resetTextarea();
  };

  return (
    <div className="chat-input-wrapper">
      <div className="chat-input-container">
        <textarea
          id="chat-message-input"
          ref={textareaRef}
          className="chat-input-textarea"
          placeholder={placeholder}
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          rows={1}
        />

        <div className="chat-input-toolbar">
          <div className="chat-input-toolbar-left">
            <button
              id="chat-attach-btn"
              className="chat-input-icon-btn attach-btn"
              type="button"
              aria-label="Attach file"
            >
              <Icon name="plus" size={20} />
            </button>
          </div>

          <div className="chat-input-toolbar-right">
            <button
              id="chat-mic-btn"
              className="chat-input-icon-btn"
              type="button"
              aria-label="Voice input"
            >
              <Icon name="mic" size={20} />
            </button>

            <button
              id="chat-send-btn"
              className={`chat-input-icon-btn send-btn${canSend ? ' active' : ''}`}
              type="button"
              aria-label="Send message"
              onClick={handleSend}
              disabled={!canSend}
            >
              <Icon name="arrow-up" size={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
