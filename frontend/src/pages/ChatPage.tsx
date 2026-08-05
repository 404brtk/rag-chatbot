import { ChatInput } from '../components/ChatInput';
import { MessageList } from '../components/MessageList';
import { useChatStore, selectActiveMessages } from '../stores/useChatStore';
import './ChatPage.css';

export function ChatPage() {
  const messages = useChatStore(selectActiveMessages);
  const isEmpty = messages.length === 0;

  if (isEmpty) {
    return (
      <div className="chat-page-empty-state-wrapper">
        <div className="hero-section">
          <h1 className="hero-greeting">What do you want to know?</h1>
        </div>
        <div className="chat-page-empty-input-region input-region">
          <ChatInput />
        </div>
      </div>
    );
  }

  return (
    <>
      <MessageList messages={messages} />
      <div className="input-region">
        <ChatInput />
      </div>
    </>
  );
}
