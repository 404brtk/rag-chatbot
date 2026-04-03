import { useState, useRef, useEffect, useMemo } from 'react';
import './App.css';
import { Sidebar } from './components/Sidebar';
import { ChatInput } from './components/ChatInput';
import { MessageList } from './components/MessageList';
import type { ChatMessage, ChatSession } from './types';

function App() {
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('sidebar-expanded');
    if (stored !== null) {
      return JSON.parse(stored);
    }
    return false;
  });
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const stored = sessionStorage.getItem('chat-history');
    if (stored) {
      try {
        return JSON.parse(stored);
      } catch {
        return [];
      }
    }
    return [];
  });
  const scrollRef = useRef<HTMLElement>(null);

  const messages = useMemo(
    () => sessions.find((s) => s.id === activeChatId)?.messages ?? [],
    [sessions, activeChatId]
  );

  useEffect(() => {
    sessionStorage.setItem('chat-history', JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    localStorage.setItem('sidebar-expanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [messages, isTyping]);

  const handleSend = (text: string) => {
    let currentChatId = activeChatId;

    if (!currentChatId) {
      const newChat: ChatSession = {
        id: crypto.randomUUID(),
        title: text.slice(0, 30),
        timestamp: Date.now(),
        messages: [],
      };
      currentChatId = newChat.id;
      setSessions((prev) => [newChat, ...prev]);
      setActiveChatId(currentChatId);
    }

    const newUserMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
    };

    setSessions((prev) =>
      prev.map((s) =>
        s.id === currentChatId ? { ...s, messages: [...s.messages, newUserMsg] } : s
      )
    );
    setIsTyping(true);

    setTimeout(() => {
      setIsTyping(false);
      const newAiMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'ai',
        content:
          'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae, lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus. Cras porttitor orci vitae ligula scelerisque convallis. [1]\n\nLorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae, lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus. Cras porttitor orci vitae ligula scelerisque convallis. [2]',
        citations: [
          {
            id: 1,
            sourceName: 'test1.pdf',
            snippet:
              'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae, lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus. Cras porttitor orci vitae ligula scelerisque convallis.',
          },
          {
            id: 2,
            sourceName: 'test2.md',
            snippet:
              'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus euismod suscipit tempus. Etiam sed tortor ligula. Quisque tempor sem rhoncus, sollicitudin augue vitae, lacinia purus. In rutrum faucibus metus porta varius. Mauris pharetra gravida tempus. Cras porttitor orci vitae ligula scelerisque convallis.',
          },
        ],
      };
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentChatId ? { ...s, messages: [...s.messages, newAiMsg] } : s
        )
      );
    }, 1500);
  };

  const handleNewChat = () => {
    setActiveChatId(null);
  };

  const handleSelectChat = (id: string) => {
    setActiveChatId(id);
  };

  const handleDeleteChat = (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeChatId === id) {
      setActiveChatId(null);
    }
  };

  const handleRenameChat = (id: string, title: string) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="layout-wrapper">
      <Sidebar
        isExpanded={isExpanded}
        onToggle={() => setIsExpanded(!isExpanded)}
        onNewChat={handleNewChat}
        history={sessions}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
      />
      <main className={`app-container ${isEmpty ? 'app-empty' : ''}`} ref={scrollRef}>
        {isEmpty ? (
          <div className="hero-section">
            <h1 className="hero-greeting">What do you want to know?</h1>
          </div>
        ) : (
          <MessageList messages={messages} isTyping={isTyping} />
        )}
        <div className={`input-region ${isEmpty ? 'input-region-centered' : ''}`}>
          <ChatInput placeholder="Ask anything..." onSend={handleSend} disabled={isTyping} />
        </div>
      </main>
    </div>
  );
}

export default App;
