import { ChatInput } from '../components/ChatInput';
import { MessageList } from '../components/MessageList';
import { useAppRouteContext } from '../hooks/useAppRouteContext';
import './ChatPage.css';

export function ChatPage() {
  const { messages, isTyping, handleSend } = useAppRouteContext();
  const isEmpty = messages.length === 0;

  if (isEmpty) {
    return (
      <div className="chat-page-empty-state-wrapper">
        <div className="hero-section">
          <h1 className="hero-greeting">What do you want to know?</h1>
        </div>
        <div className="chat-page-empty-input-region input-region input-region-centered">
          <ChatInput placeholder="Ask anything..." onSend={handleSend} disabled={isTyping} />
        </div>
      </div>
    );
  }

  return (
    <>
      <MessageList messages={messages} isTyping={isTyping} />
      <div className="input-region">
        <ChatInput placeholder="Ask anything..." onSend={handleSend} disabled={isTyping} />
      </div>
    </>
  );
}
