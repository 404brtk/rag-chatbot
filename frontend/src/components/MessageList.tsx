import { Message } from './Message';
import type { ChatMessage } from '../types';
import './MessageList.css';

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  const grouped: (ChatMessage | { type: 'pair'; left: ChatMessage; right: ChatMessage })[] = [];

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'user') {
      grouped.push(msg);
    } else if (msg.role === 'ai') {
      if (msg.variant === 'rag_on') {
        const nextMsg = messages[i + 1];
        if (nextMsg && nextMsg.role === 'ai' && nextMsg.variant === 'rag_off') {
          grouped.push({ type: 'pair', left: msg, right: nextMsg });
          i++;
        } else {
          grouped.push({
            type: 'pair',
            left: msg,
            right: { id: 'placeholder-right', role: 'ai', variant: 'rag_off', content: '' },
          });
        }
      } else if (msg.variant === 'rag_off') {
        grouped.push({
          type: 'pair',
          left: { id: 'placeholder-left', role: 'ai', variant: 'rag_on', content: '' },
          right: msg,
        });
      } else {
        grouped.push(msg);
      }
    }
  }
  const hasSplitMessages = grouped.some((item) => 'type' in item && item.type === 'pair');

  return (
    <div className={`message-list-container ${hasSplitMessages ? 'has-split' : ''}`}>
      <div className={`message-list-inner ${hasSplitMessages ? 'message-list-inner-wide' : ''}`}>
        {grouped.map((item, idx) => {
          if ('type' in item && item.type === 'pair') {
            return (
              <div className="message-split-container" key={`pair-${idx}`}>
                <div className="message-split-column message-split-left">
                  <div className="column-header label-rag-on">RAG On</div>
                  <Message message={item.left} />
                </div>
                <div className="message-split-column message-split-right">
                  <div className="column-header label-rag-off">RAG Off</div>
                  <Message message={item.right} />
                </div>
              </div>
            );
          } else {
            return <Message key={(item as ChatMessage).id} message={item as ChatMessage} />;
          }
        })}
      </div>
    </div>
  );
}
