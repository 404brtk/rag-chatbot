import { Message } from './Message';
import type { ChatMessage } from './Message';
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
          <Message
            message={{
              id: 'typing-indicator',
              role: 'ai',
              content: (
                <div className="typing-indicator" aria-label="AI is thinking...">
                  <div className="typing-shape" />
                </div>
              ),
            }}
          />
        )}
      </div>
    </div>
  );
}
