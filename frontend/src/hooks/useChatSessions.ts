import { useState, useMemo, useEffect } from 'react';
import type { ChatMessage, ChatSession } from '../types';

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const stored = sessionStorage.getItem('chat-history');
    if (stored) return JSON.parse(stored);
    return [];
  });
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);

  const messages = useMemo(
    () => sessions.find((s) => s.id === activeChatId)?.messages ?? [],
    [sessions, activeChatId]
  );

  useEffect(() => {
    sessionStorage.setItem('chat-history', JSON.stringify(sessions));
  }, [sessions]);

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

  return {
    sessions,
    activeChatId,
    messages,
    isTyping,
    handleSend,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
  };
}
