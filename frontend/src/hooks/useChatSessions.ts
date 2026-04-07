import { useState, useEffect } from 'react';
import type { ChatMessage, ChatMode, ChatSession } from '../types';

const CHAT_HISTORY_STORAGE_KEY = 'chat-history';
const CHAT_DRAFT_MODE_STORAGE_KEY = 'chat-draft-mode';

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const stored = sessionStorage.getItem(CHAT_HISTORY_STORAGE_KEY);
    if (stored) return JSON.parse(stored) as ChatSession[];
    return [];
  });
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [draftMode, setDraftMode] = useState<ChatMode>(() => {
    const stored = localStorage.getItem(CHAT_DRAFT_MODE_STORAGE_KEY);
    if (stored) return stored as ChatMode;
    return 'direct';
  });
  const [isTyping, setIsTyping] = useState(false);
  const activeSession = sessions.find((session) => session.id === activeChatId) ?? null;
  const messages = activeSession?.messages ?? [];
  const mode = activeSession?.mode ?? draftMode;

  useEffect(() => {
    sessionStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    localStorage.setItem(CHAT_DRAFT_MODE_STORAGE_KEY, draftMode);
  }, [draftMode]);

  const handleSend = (text: string) => {
    let currentChatId = activeChatId;

    if (!currentChatId) {
      const newChat: ChatSession = {
        id: crypto.randomUUID(),
        title: text.slice(0, 30),
        timestamp: Date.now(),
        mode: draftMode,
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
    const selectedSession = sessions.find((session) => session.id === id);
    if (selectedSession) {
      setDraftMode(selectedSession.mode);
    }

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

  const handleModeChange = (newMode: ChatMode) => {
    if (mode === newMode) {
      return;
    }

    setDraftMode(newMode);

    if (activeSession) {
      setActiveChatId(null);
    }
  };

  return {
    sessions,
    activeChatId,
    messages,
    mode,
    isTyping,
    handleSend,
    handleModeChange,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
  };
}
