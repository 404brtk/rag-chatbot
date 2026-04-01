import { useState, useRef, useEffect } from 'react';
import './App.css';
import { ChatInput } from './components/ChatInput';
import { MessageList } from './components/MessageList';
import type { ChatMessage } from './components/Message';
import { Citation } from './components/Citation';

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [messages, isTyping]);

  const handleSend = (text: string) => {
    const newUserMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: <p>{text}</p>,
    };
    setMessages((prev) => [...prev, newUserMsg]);
    setIsTyping(true);

    setTimeout(() => {
      setIsTyping(false);
      const newAiMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'ai',
        content: (
          <div>
            <p>
              Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit
              tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae,
              lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus.
              Cras porttitor orci vitae ligula scelerisque convallis.
              <Citation
                id={1}
                sourceName="test1.pdf"
                snippet="Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit
              tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae,
              lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus.
              Cras porttitor orci vitae ligula scelerisque convallis."
              />
            </p>
            <p>
              Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit
              tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae,
              lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus.
              Cras porttitor orci vitae ligula scelerisque convallis.
              <Citation
                id={2}
                sourceName="test2.md"
                snippet="Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit
              tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae,
              lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus.
              Cras porttitor orci vitae ligula scelerisque convallis."
              />
            </p>
          </div>
        ),
      };
      setMessages((prev) => [...prev, newAiMsg]);
    }, 1500);
  };

  const isEmpty = messages.length === 0;

  return (
    <main className={`app-container ${isEmpty ? 'app-empty' : ''}`} ref={scrollRef}>
      {isEmpty ? (
        <div className="hero-section">
          <h1 className="hero-greeting">Hi, User!</h1>
          <p className="hero-subtext">Ask me anything</p>
        </div>
      ) : (
        <MessageList messages={messages} isTyping={isTyping} />
      )}
      <div className={`input-region ${isEmpty ? 'input-region-centered' : ''}`}>
        <ChatInput placeholder="Ask anything..." onSend={handleSend} disabled={isTyping} />
      </div>
    </main>
  );
}

export default App;
