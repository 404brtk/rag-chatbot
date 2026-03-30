import { useState, useRef, type ChangeEvent, type KeyboardEvent } from 'react';
import './ChatInput.css';

const ICON_SIZE = 20;
const ICON_DEFAULTS = {
  width: ICON_SIZE,
  height: ICON_SIZE,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function IconPlus() {
  return (
    <svg {...ICON_DEFAULTS}>
      <path d="M5 12h14" />
      <path d="M12 5v14" />
    </svg>
  );
}

function IconMic() {
  return (
    <svg {...ICON_DEFAULTS}>
      <path d="M12 19v3" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <rect x="9" y="2" width="6" height="13" rx="3" />
    </svg>
  );
}
function IconArrowUp() {
  return (
    <svg {...ICON_DEFAULTS}>
      <path d="m5 12 7-7 7 7" />
      <path d="M12 19V5" />
    </svg>
  );
}

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
              <IconPlus />
            </button>
          </div>

          <div className="chat-input-toolbar-right">
            <button
              id="chat-mic-btn"
              className="chat-input-icon-btn"
              type="button"
              aria-label="Voice input"
            >
              <IconMic />
            </button>

            <button
              id="chat-send-btn"
              className={`chat-input-icon-btn send-btn${canSend ? ' active' : ''}`}
              type="button"
              aria-label="Send message"
              onClick={handleSend}
              disabled={!canSend}
            >
              <IconArrowUp />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
