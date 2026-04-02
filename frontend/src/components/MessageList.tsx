import { Message } from './Message';
import type { ChatMessage } from '../types';
import './MessageList.css';

interface MessageListProps {
  messages: ChatMessage[];
  isTyping?: boolean;
}

export function MessageList({ messages, isTyping }: MessageListProps) {
  return (
    <div className="message-list-container">
      <div className="message-list-inner">
        {messages.map((message) => (
          <Message key={message.id} message={message} />
        ))}

        {isTyping && (
          <div className="typing-indicator" aria-label="AI is thinking...">
            <div className="typing-shape" />
          </div>
        )}
      </div>
    </div>
  );
}
