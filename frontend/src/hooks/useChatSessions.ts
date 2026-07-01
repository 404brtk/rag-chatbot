import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router';
import { api } from '../services/api';
import type {
  ChatMessage,
  ChatMode,
  ChatSession,
  MessageAttachment,
  CursorPaginated,
} from '../types';
import { useLocalStorage } from './useLocalStorage';
import { useAuth } from './useAuth';
import { useModelConfig } from './useModelConfig';

interface BackendConversation {
  id: string;
  title?: string;
  last_message_at: string;
  status: string;
  mode?: ChatMode;
}

interface BackendMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  raw_question?: string;
  context?: {
    index: number;
    document_filename: string;
    content: string;
  }[];
  is_compaction_summary?: boolean;
  attachments?: MessageAttachment[];
  variant?: 'rag_on' | 'rag_off';
}

function mapBackendMessages(messages: BackendMessage[]): ChatMessage[] {
  return messages.map((m, idx, arr) => {
    const role = (m.role === 'user' ? 'user' : 'ai') as 'user' | 'ai';
    let citations = m.context?.map((chunk) => ({
      id: chunk.index,
      sourceName: chunk.document_filename,
      snippet: chunk.content,
    }));

    if (role === 'ai' && idx > 0) {
      const prev = arr[idx - 1];
      if (prev && prev.role === 'user' && prev.context) {
        citations = prev.context.map((chunk) => ({
          id: chunk.index,
          sourceName: chunk.document_filename,
          snippet: chunk.content,
        }));
      }
    }

    return {
      id: m.id,
      role,
      content: role === 'user' ? (m.raw_question ?? m.content) : m.content,
      citations,
      attachments: m.attachments,
      is_compaction_summary: m.is_compaction_summary,
      variant: m.variant,
    };
  });
}

export function useChatSessions() {
  const { chatId } = useParams<{ chatId?: string }>();
  const navigate = useNavigate();
  const activeChatId = chatId || null;

  const { isAuthenticated } = useAuth();
  const { provider, model, setProvider, setModel, models } = useModelConfig();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [nextConversationsCursor, setNextConversationsCursor] = useState<string | null>(null);
  const [totalConversationsCount, setTotalConversationsCount] = useState<number>(0);
  const [draftMode, setDraftMode] = useLocalStorage<ChatMode>('chat_mode', 'direct');
  const [isTyping, setIsTyping] = useState(false);
  const [ragEnabled, setRagEnabled] = useLocalStorage<boolean>('chat_rag_enabled', false);
  const [compactionEnabled, setCompactionEnabled] = useLocalStorage<boolean>(
    'chat_compaction_enabled',
    false
  );
  const [selectedDocIds, setSelectedDocIds] = useLocalStorage<string[]>(
    'chat_selected_doc_ids',
    []
  );

  const prevActiveChatIdRef = useRef<string | null>(activeChatId);
  const sessionsRef = useRef<ChatSession[]>(sessions);
  sessionsRef.current = sessions;

  useEffect(() => {
    const prevId = prevActiveChatIdRef.current;
    prevActiveChatIdRef.current = activeChatId;
    if (prevId !== null && activeChatId !== prevId) {
      setSelectedDocIds([]);
    }
  }, [activeChatId, setSelectedDocIds]);

  const abortControllerRef = useRef<AbortController | null>(null);

  const refreshActiveChat = async (targetChatId: string) => {
    try {
      const res = await api.get<CursorPaginated<BackendMessage>>(
        `/conversations/${targetChatId}/messages/`
      );
      const mapped = mapBackendMessages([...res.results].reverse());
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== targetChatId) return s;
          return {
            ...s,
            messages: mapped,
            timestamp: Date.now(),
            loaded: true,
            nextCursor: res.next || null,
          };
        })
      );
    } catch (err) {
      console.error('Failed to refresh messages:', err);
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsTyping(false);
    if (activeChatId) {
      refreshActiveChat(activeChatId);
    }
  };

  const activeSession = sessions.find((session) => session.id === activeChatId) ?? null;
  const messages = activeSession?.messages ?? [];
  const mode = activeSession?.mode ?? draftMode;

  useEffect(() => {
    let ignore = false;

    const loadConversations = async () => {
      if (!isAuthenticated) {
        setSessions([]);
        setNextConversationsCursor(null);
        setTotalConversationsCount(0);
        return;
      }
      try {
        const data = await api.get<CursorPaginated<BackendConversation>>('/conversations/');
        if (ignore) return;
        const mapped: ChatSession[] = data.results.map((c) => ({
          id: c.id,
          title: c.title || `Chat ${c.id.slice(0, 8)}`,
          timestamp: new Date(c.last_message_at).getTime(),
          mode: c.mode || 'direct',
          messages: [],
        }));
        setSessions(mapped);
        setNextConversationsCursor(data.next || null);
        setTotalConversationsCount(data.count ?? data.results.length);
      } catch (err) {
        console.error('Failed to load conversations:', err);
      }
    };

    loadConversations();

    return () => {
      ignore = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (!activeChatId) return;

    const active = sessionsRef.current.find((s) => s.id === activeChatId);
    if (active && active.loaded) return;

    let cancelled = false;

    const loadMessages = async () => {
      try {
        const data = await api.get<CursorPaginated<BackendMessage>>(
          `/conversations/${activeChatId}/messages/`
        );
        if (cancelled) return;
        const mappedMessages = mapBackendMessages([...data.results].reverse());

        setSessions((prev) =>
          prev.map((s) => {
            if (s.id !== activeChatId || s.loaded) return s;
            return {
              ...s,
              messages: mappedMessages,
              loaded: true,
              nextCursor: data.next || null,
            };
          })
        );
      } catch (err) {
        console.error('Failed to load messages:', err);
      }
    };

    loadMessages();
    return () => {
      cancelled = true;
    };
  }, [activeChatId]);

  const handleSend = async (
    text: string,
    attachments: MessageAttachment[] = [],
    selectedDocIds: string[] = []
  ) => {
    const normalizedText = text.trim();
    if (normalizedText === '' && attachments.length === 0) {
      return;
    }

    if (!isAuthenticated) {
      return;
    }

    let currentChatId = activeChatId;
    const isSideBySide = mode === 'side-by-side';

    if (!currentChatId) {
      try {
        const newChat = await api.post<{
          id: string;
          title: string;
          last_message_at: string;
          mode?: ChatMode;
        }>('/conversations/', {
          title: normalizedText.slice(0, 30) || 'New Chat',
          mode: draftMode,
        });
        currentChatId = newChat.id;

        const newSession: ChatSession = {
          id: currentChatId,
          title: newChat.title || 'New Chat',
          timestamp: new Date(newChat.last_message_at).getTime(),
          mode: draftMode,
          messages: [],
          loaded: true,
        };

        setSessions((prev) => [newSession, ...prev]);
        setTotalConversationsCount((prev) => prev + 1);
        navigate(`/chat/${currentChatId}`);
      } catch {
        return;
      }
    }

    const newUserMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: normalizedText,
      attachments: attachments.length > 0 ? attachments : undefined,
    };

    setSessions((prev) => {
      const idx = prev.findIndex((s) => s.id === currentChatId);
      if (idx === -1) return prev;
      const updatedSession = {
        ...prev[idx],
        timestamp: Date.now(),
        messages: [...prev[idx].messages, newUserMsg],
      };
      return [updatedSession, ...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });

    setIsTyping(true);

    const finalDocumentIds = ragEnabled || isSideBySide ? selectedDocIds : undefined;

    const payloadAttachments = attachments.map((att) => ({
      id: att.backendId || att.id,
      name: att.name,
      size: att.size,
      mimeType: att.mimeType,
    }));

    const tempLeftId = crypto.randomUUID();
    const tempRightId = crypto.randomUUID();
    const tempAiMsgId = crypto.randomUUID();

    const placeholders: ChatMessage[] = isSideBySide
      ? [
          {
            id: tempLeftId,
            role: 'ai',
            variant: 'rag_on',
            content: '',
            citations: [],
          },
          {
            id: tempRightId,
            role: 'ai',
            variant: 'rag_off',
            content: '',
            citations: [],
          },
        ]
      : [
          {
            id: tempAiMsgId,
            role: 'ai',
            content: '',
            citations: [],
          },
        ];

    setSessions((prev) =>
      prev.map((s) =>
        s.id === currentChatId ? { ...s, messages: [...s.messages, ...placeholders] } : s
      )
    );

    let accumulatedLeft = '';
    let accumulatedRight = '';
    let accumulatedContent = '';

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    await api.stream(
      `/conversations/${currentChatId}/messages/stream/`,
      {
        content: normalizedText,
        attachments: payloadAttachments,
        provider,
        model,
        document_ids: finalDocumentIds,
        compaction_enabled: compactionEnabled,
      },
      (token, tokenVariant) => {
        if (isSideBySide) {
          const side = tokenVariant || 'rag_on';
          if (side === 'rag_on') {
            accumulatedLeft += token;
          } else {
            accumulatedRight += token;
          }
          setSessions((prev) =>
            prev.map((s) =>
              s.id === currentChatId
                ? {
                    ...s,
                    messages: s.messages.map((m) => {
                      if (m.id === tempLeftId && side === 'rag_on') {
                        return { ...m, content: accumulatedLeft };
                      }
                      if (m.id === tempRightId && side === 'rag_off') {
                        return { ...m, content: accumulatedRight };
                      }
                      return m;
                    }),
                  }
                : s
            )
          );
        } else {
          accumulatedContent += token;
          setSessions((prev) =>
            prev.map((s) =>
              s.id === currentChatId
                ? {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === tempAiMsgId ? { ...m, content: accumulatedContent } : m
                    ),
                  }
                : s
            )
          );
        }
      },
      (doneEvent: unknown) => {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
        setIsTyping(false);
        if (currentChatId) {
          refreshActiveChat(currentChatId);
        }

        const doneData = doneEvent as { title?: string };
        const newTitle = doneData?.title;
        if (newTitle) {
          setSessions((prev) =>
            prev.map((s) => (s.id === currentChatId ? { ...s, title: newTitle } : s))
          );
        }
      },
      () => {
        if (currentChatId) {
          refreshActiveChat(currentChatId);
        }
      },
      (err) => {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
        setIsTyping(false);
        setSessions((prev) =>
          prev.map((s) =>
            s.id === currentChatId
              ? {
                  ...s,
                  messages: s.messages.map((m) => {
                    if (isSideBySide) {
                      if (m.id === tempLeftId) {
                        return { ...m, content: m.content || `Error: ${err}` };
                      }
                      if (m.id === tempRightId) {
                        return { ...m, content: m.content || `Error: ${err}` };
                      }
                    } else {
                      if (m.id === tempAiMsgId) {
                        return { ...m, content: m.content || `Error: ${err}` };
                      }
                    }
                    return m;
                  }),
                }
              : s
          )
        );
      },
      controller.signal
    );
  };

  const handleNewChat = () => {
    navigate('/');
  };

  const handleSelectChat = (id: string) => {
    const selectedSession = sessions.find((session) => session.id === id);
    if (selectedSession) {
      setDraftMode(selectedSession.mode);
    }
    navigate(`/chat/${id}`);
  };

  const handleDeleteChat = async (id: string) => {
    try {
      await api.delete(`/conversations/${id}/`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setTotalConversationsCount((prev) => Math.max(0, prev - 1));
      if (activeChatId === id) {
        navigate('/');
      }
    } catch (err) {
      console.error('Failed to delete chat:', err);
    }
  };

  const handleRenameChat = async (id: string, title: string) => {
    try {
      await api.patch(`/conversations/${id}/`, { title });
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    } catch (err) {
      console.error('Failed to rename chat:', err);
    }
  };

  const handleModeChange = (newMode: ChatMode) => {
    if (mode === newMode) {
      return;
    }
    setDraftMode(newMode);
    if (activeSession) {
      navigate('/');
    }
  };

  const isLoadingMoreRef = useRef(false);

  const loadMoreMessages = async () => {
    if (!activeChatId || isLoadingMoreRef.current) return;
    const session = sessions.find((s) => s.id === activeChatId);
    if (!session || !session.nextCursor) return;

    isLoadingMoreRef.current = true;
    try {
      const data = await api.get<CursorPaginated<BackendMessage>>(session.nextCursor);
      const mapped = mapBackendMessages([...data.results].reverse());

      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeChatId) return s;
          return {
            ...s,
            messages: [...mapped, ...s.messages],
            nextCursor: data.next || null,
          };
        })
      );
    } catch (err) {
      console.error('Failed to load more messages:', err);
    } finally {
      isLoadingMoreRef.current = false;
    }
  };

  const isLoadingMoreConversationsRef = useRef(false);

  const loadMoreConversations = async () => {
    if (isLoadingMoreConversationsRef.current || !nextConversationsCursor) return;

    isLoadingMoreConversationsRef.current = true;
    try {
      const data = await api.get<CursorPaginated<BackendConversation>>(nextConversationsCursor);
      const mapped: ChatSession[] = data.results.map((c) => ({
        id: c.id,
        title: c.title || `Chat ${c.id.slice(0, 8)}`,
        timestamp: new Date(c.last_message_at).getTime(),
        mode: c.mode || 'direct',
        messages: [],
      }));

      setSessions((prev) => {
        const existingIds = new Set(prev.map((s) => s.id));
        const newSessions = mapped.filter((s) => !existingIds.has(s.id));
        return [...prev, ...newSessions];
      });
      setNextConversationsCursor(data.next || null);
      if (data.count !== undefined) {
        setTotalConversationsCount(data.count);
      }
    } catch (err) {
      console.error('Failed to load more conversations:', err);
    } finally {
      isLoadingMoreConversationsRef.current = false;
    }
  };

  return {
    sessions,
    activeChatId,
    messages,
    mode,
    isTyping,
    handleSend,
    handleStop,
    handleModeChange,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
    provider,
    model,
    setProvider,
    setModel,
    models,
    isAuthenticated,
    ragEnabled,
    setRagEnabled,
    compactionEnabled,
    setCompactionEnabled,
    loadMoreMessages,
    selectedDocIds,
    setSelectedDocIds,
    loadMoreConversations,
    totalConversationsCount,
  };
}
