import { create } from 'zustand';
import type { NavigateFunction } from 'react-router';
import { api } from '../services/api';
import type {
  ChatMessage,
  ChatMode,
  ChatSession,
  MessageAttachment,
  CursorPaginated,
} from '../types';

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

function getStored<T>(key: string, defaultValue: T): T {
  try {
    const item = localStorage.getItem(key);
    return item ? (JSON.parse(item) as T) : defaultValue;
  } catch {
    return defaultValue;
  }
}

function setStored<T>(key: string, value: T): void {
  if (!key || key.trim() === '') return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (err) {
    console.error(`Error setting localStorage key "${key}":`, err);
  }
}

interface ChatState {
  sessions: ChatSession[];
  activeChatId: string | null;
  nextConversationsCursor: string | null;
  totalConversationsCount: number;
  draftMode: ChatMode;
  isTyping: boolean;
  ragEnabled: boolean;
  compactionEnabled: boolean;
  selectedDocIds: string[];
  provider: string;
  model: string;
  savedModels: Record<string, string[]>;
  models: Record<string, string[]>;

  setActiveChatId: (id: string | null) => void;
  loadModels: (isAuthenticated: boolean) => Promise<void>;
  setProvider: (provider: string) => void;
  setModel: (model: string) => void;
  saveModelHistory: (model?: string) => void;
  removeSavedModel: (provider: string, modelToRemove: string) => void;
  setRagEnabled: (enabled: boolean) => void;
  setCompactionEnabled: (enabled: boolean) => void;
  setSelectedDocIds: (ids: string[]) => void;
  loadConversations: (isAuthenticated: boolean) => Promise<void>;
  loadMoreConversations: () => Promise<void>;
  loadMessages: (chatId: string) => Promise<void>;
  loadMoreMessages: () => Promise<void>;
  sendMessage: (
    text: string,
    attachments?: MessageAttachment[],
    overrideDocIds?: string[],
    navigate?: NavigateFunction
  ) => Promise<void>;
  stopStreaming: () => void;
  newChat: (navigate?: NavigateFunction) => void;
  selectChat: (id: string, navigate?: NavigateFunction) => void;
  deleteChat: (id: string, navigate?: NavigateFunction) => Promise<void>;
  renameChat: (id: string, title: string) => Promise<void>;
  setMode: (mode: ChatMode, navigate?: NavigateFunction) => void;
}

let activeAbortController: AbortController | null = null;
let isLoadingMoreConversations = false;
let isLoadingMoreMessages = false;

export const useChatStore = create<ChatState>((set, get) => {
  const initialProvider = getStored<string>('chat_provider', 'openai');
  const rawSavedModels = getStored<Record<string, string[]>>('chat_saved_models', {
    openai: [],
    openrouter: [],
    gemini: [],
  });
  delete rawSavedModels.llamacpp;
  const initialSavedModels = rawSavedModels;

  const refreshActiveChat = async (targetId: string) => {
    try {
      const res = await api.get<CursorPaginated<BackendMessage>>(
        `/conversations/${targetId}/messages/`
      );
      const mapped = mapBackendMessages([...res.results].reverse());
      set((state) => ({
        sessions: state.sessions.map((s) => {
          if (s.id !== targetId) return s;
          return {
            ...s,
            messages: mapped,
            timestamp: Date.now(),
            loaded: true,
            nextCursor: res.next || null,
          };
        }),
      }));
    } catch (err) {
      console.error('Failed to refresh messages:', err);
    }
  };

  return {
    sessions: [],
    activeChatId: null,
    nextConversationsCursor: null,
    totalConversationsCount: 0,
    draftMode: getStored<ChatMode>('chat_mode', 'direct'),
    isTyping: false,
    ragEnabled: getStored<boolean>('chat_rag_enabled', false),
    compactionEnabled: getStored<boolean>('chat_compaction_enabled', false),
    selectedDocIds: [],
    provider: initialProvider,
    savedModels: initialSavedModels,
    model: initialProvider === 'llamacpp' ? '' : initialSavedModels[initialProvider]?.[0] || '',
    models: {},

    setActiveChatId: (id) => {
      const current = get().activeChatId;
      if (current === id) return;
      get().setSelectedDocIds([]);
      set({ activeChatId: id });
    },

    loadModels: async (isAuthenticated) => {
      if (!isAuthenticated) {
        set({ models: {} });
        return;
      }
      try {
        const data = await api.get<Record<string, string[]>>('/models/');
        const currentProvider = get().provider;

        if (currentProvider === 'llamacpp') {
          const llamacppList = data.llamacpp || [];
          const currentModel = get().model;
          const nextModel = llamacppList.includes(currentModel)
            ? currentModel
            : llamacppList[0] || '';
          set({ models: data, model: nextModel });
        } else {
          set({ models: data });
        }
      } catch (err) {
        console.error('Failed to load models:', err);
      }
    },

    setProvider: (provider) => {
      setStored('chat_provider', provider);
      const currentSaved = get().savedModels;
      const discoveredLlama = get().models.llamacpp || [];
      const modelForProvider =
        provider === 'llamacpp' ? discoveredLlama[0] || '' : currentSaved[provider]?.[0] || '';
      set({ provider, model: modelForProvider });
    },

    setModel: (model: string) => {
      set({ model });
    },

    saveModelHistory: (modelToSave) => {
      const provider = get().provider;
      if (provider === 'llamacpp') return;

      const target = (modelToSave !== undefined ? modelToSave : get().model).trim();
      if (!target) return;

      const currentList = get().savedModels[provider] || [];
      const updatedList = [target, ...currentList.filter((m) => m !== target)];

      const updatedSavedModels = {
        ...get().savedModels,
        [provider]: updatedList,
      };
      delete updatedSavedModels.llamacpp;
      setStored('chat_saved_models', updatedSavedModels);
      set({ model: target, savedModels: updatedSavedModels });
    },

    removeSavedModel: (provider, modelToRemove) => {
      const currentList = get().savedModels[provider] || [];
      const updatedList = currentList.filter((m) => m !== modelToRemove);
      const updatedSavedModels = {
        ...get().savedModels,
        [provider]: updatedList,
      };
      setStored('chat_saved_models', updatedSavedModels);

      const activeModel = get().model;
      const nextModel =
        get().provider === provider && activeModel === modelToRemove
          ? updatedList[0] || ''
          : activeModel;

      set({ savedModels: updatedSavedModels, model: nextModel });
    },

    setRagEnabled: (ragEnabled) => {
      setStored('chat_rag_enabled', ragEnabled);
      set({ ragEnabled });
    },

    setCompactionEnabled: (compactionEnabled) => {
      setStored('chat_compaction_enabled', compactionEnabled);
      set({ compactionEnabled });
    },

    setSelectedDocIds: (selectedDocIds) => {
      set({ selectedDocIds });
    },

    loadConversations: async (isAuthenticated) => {
      if (!isAuthenticated) {
        set({ sessions: [], nextConversationsCursor: null, totalConversationsCount: 0 });
        return;
      }
      try {
        const data = await api.get<CursorPaginated<BackendConversation>>('/conversations/');
        const mapped: ChatSession[] = data.results.map((c) => ({
          id: c.id,
          title: c.title || `Chat ${c.id.slice(0, 8)}`,
          timestamp: new Date(c.last_message_at).getTime(),
          mode: c.mode || 'direct',
          messages: [],
        }));

        set({
          sessions: mapped,
          nextConversationsCursor: data.next || null,
          totalConversationsCount: data.count ?? data.results.length,
        });
      } catch (err) {
        console.error('Failed to load conversations:', err);
      }
    },

    loadMoreConversations: async () => {
      const { nextConversationsCursor } = get();
      if (isLoadingMoreConversations || !nextConversationsCursor) return;

      isLoadingMoreConversations = true;
      try {
        const data = await api.get<CursorPaginated<BackendConversation>>(nextConversationsCursor);
        const mapped: ChatSession[] = data.results.map((c) => ({
          id: c.id,
          title: c.title || `Chat ${c.id.slice(0, 8)}`,
          timestamp: new Date(c.last_message_at).getTime(),
          mode: c.mode || 'direct',
          messages: [],
        }));

        set((state) => {
          const existingIds = new Set(state.sessions.map((s) => s.id));
          const newSessions = mapped.filter((s) => !existingIds.has(s.id));
          return {
            sessions: [...state.sessions, ...newSessions],
            nextConversationsCursor: data.next || null,
            totalConversationsCount:
              data.count !== undefined ? data.count : state.totalConversationsCount,
          };
        });
      } catch (err) {
        console.error('Failed to load more conversations:', err);
      } finally {
        isLoadingMoreConversations = false;
      }
    },

    loadMessages: async (chatId) => {
      if (!chatId) return;
      const session = get().sessions.find((s) => s.id === chatId);
      if (session && session.loaded) return;

      try {
        const data = await api.get<CursorPaginated<BackendMessage>>(
          `/conversations/${chatId}/messages/`
        );
        const mappedMessages = mapBackendMessages([...data.results].reverse());

        set((state) => ({
          sessions: state.sessions.map((s) => {
            if (s.id !== chatId || s.loaded) return s;
            return {
              ...s,
              messages: mappedMessages,
              loaded: true,
              nextCursor: data.next || null,
            };
          }),
        }));
      } catch (err) {
        console.error('Failed to load messages:', err);
      }
    },

    loadMoreMessages: async () => {
      const { activeChatId, sessions } = get();
      if (!activeChatId || isLoadingMoreMessages) return;
      const session = sessions.find((s) => s.id === activeChatId);
      if (!session || !session.nextCursor) return;

      isLoadingMoreMessages = true;
      try {
        const data = await api.get<CursorPaginated<BackendMessage>>(session.nextCursor);
        const mapped = mapBackendMessages([...data.results].reverse());

        set((state) => ({
          sessions: state.sessions.map((s) => {
            if (s.id !== activeChatId) return s;
            return {
              ...s,
              messages: [...mapped, ...s.messages],
              nextCursor: data.next || null,
            };
          }),
        }));
      } catch (err) {
        console.error('Failed to load more messages:', err);
      } finally {
        isLoadingMoreMessages = false;
      }
    },

    sendMessage: async (text, attachments = [], overrideDocIds = [], navigate) => {
      const normalizedText = text.trim();
      if (normalizedText === '' && attachments.length === 0) return;

      const {
        activeChatId,
        draftMode,
        provider,
        model,
        ragEnabled,
        compactionEnabled,
        selectedDocIds,
      } = get();

      if (model.trim()) {
        get().saveModelHistory(model);
      }

      let currentChatId = activeChatId;
      const currentMode = selectActiveMode(get());
      const isSideBySide = currentMode === 'side-by-side';

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

          set((state) => ({
            sessions: [newSession, ...state.sessions],
            totalConversationsCount: state.totalConversationsCount + 1,
            activeChatId: currentChatId,
          }));

          if (navigate) {
            navigate(`/chat/${currentChatId}`);
          }
        } catch (err) {
          console.error('Failed to create new conversation:', err);
          return;
        }
      }

      const newUserMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: normalizedText,
        attachments: attachments.length > 0 ? attachments : undefined,
      };

      set((state) => {
        const idx = state.sessions.findIndex((s) => s.id === currentChatId);
        if (idx === -1) return state;
        const updatedSession = {
          ...state.sessions[idx],
          timestamp: Date.now(),
          messages: [...state.sessions[idx].messages, newUserMsg],
        };
        return {
          sessions: [
            updatedSession,
            ...state.sessions.slice(0, idx),
            ...state.sessions.slice(idx + 1),
          ],
          isTyping: true,
        };
      });

      const activeDocIds = overrideDocIds.length > 0 ? overrideDocIds : selectedDocIds;
      const finalDocumentIds = ragEnabled || isSideBySide ? activeDocIds : undefined;

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

      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.id === currentChatId ? { ...s, messages: [...s.messages, ...placeholders] } : s
        ),
      }));

      let accumulatedLeft = '';
      let accumulatedRight = '';
      let accumulatedContent = '';

      if (activeAbortController) {
        activeAbortController.abort();
      }
      const controller = new AbortController();
      activeAbortController = controller;

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
            set((state) => ({
              sessions: state.sessions.map((s) =>
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
              ),
            }));
          } else {
            accumulatedContent += token;
            set((state) => ({
              sessions: state.sessions.map((s) =>
                s.id === currentChatId
                  ? {
                      ...s,
                      messages: s.messages.map((m) =>
                        m.id === tempAiMsgId ? { ...m, content: accumulatedContent } : m
                      ),
                    }
                  : s
              ),
            }));
          }
        },
        (doneEvent: unknown) => {
          if (activeAbortController === controller) {
            activeAbortController = null;
          }
          set({ isTyping: false });
          if (currentChatId) {
            void refreshActiveChat(currentChatId);
          }

          const doneData = doneEvent as { title?: string };
          const newTitle = doneData?.title;
          if (newTitle) {
            set((state) => ({
              sessions: state.sessions.map((s) =>
                s.id === currentChatId ? { ...s, title: newTitle } : s
              ),
            }));
          }
        },
        () => {
          if (currentChatId) {
            void refreshActiveChat(currentChatId);
          }
        },
        (err) => {
          if (activeAbortController === controller) {
            activeAbortController = null;
          }
          set({ isTyping: false });
          set((state) => ({
            sessions: state.sessions.map((s) =>
              s.id === currentChatId
                ? {
                    ...s,
                    messages: s.messages.map((m) => {
                      if (isSideBySide) {
                        if (m.id === tempLeftId || m.id === tempRightId) {
                          return { ...m, content: m.content || `Error: ${err}` };
                        }
                      } else if (m.id === tempAiMsgId) {
                        return { ...m, content: m.content || `Error: ${err}` };
                      }
                      return m;
                    }),
                  }
                : s
            ),
          }));
          if (currentChatId) {
            void refreshActiveChat(currentChatId);
          }
        },
        controller.signal
      );
    },

    stopStreaming: () => {
      if (activeAbortController) {
        activeAbortController.abort();
        activeAbortController = null;
      }
      set({ isTyping: false });
      const { activeChatId } = get();
      if (activeChatId) {
        void refreshActiveChat(activeChatId);
      }
    },

    newChat: (navigate) => {
      set({ activeChatId: null });
      if (navigate) {
        navigate('/');
      }
    },

    selectChat: (id, navigate) => {
      const session = get().sessions.find((s) => s.id === id);
      if (session) {
        setStored('chat_mode', session.mode);
        set({ draftMode: session.mode });
      }
      if (navigate) {
        navigate(`/chat/${id}`);
      }
    },

    deleteChat: async (id, navigate) => {
      try {
        await api.delete(`/conversations/${id}/`);
        const { activeChatId } = get();
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== id),
          totalConversationsCount: Math.max(0, state.totalConversationsCount - 1),
        }));

        if (activeChatId === id && navigate) {
          navigate('/');
        }
      } catch (err) {
        console.error('Failed to delete chat:', err);
      }
    },

    renameChat: async (id, title) => {
      try {
        await api.patch(`/conversations/${id}/`, { title });
        set((state) => ({
          sessions: state.sessions.map((s) => (s.id === id ? { ...s, title } : s)),
        }));
      } catch (err) {
        console.error('Failed to rename chat:', err);
      }
    },

    setMode: (newMode, navigate) => {
      const currentMode = selectActiveMode(get());
      if (currentMode === newMode) return;

      setStored('chat_mode', newMode);
      set({ draftMode: newMode });

      const { activeChatId } = get();
      if (activeChatId && navigate) {
        navigate('/');
      }
    },
  };
});

const EMPTY_MESSAGES: ChatMessage[] = [];

export const selectActiveMessages = (state: ChatState) => {
  const active = state.sessions.find((s) => s.id === state.activeChatId);
  return active?.messages ?? EMPTY_MESSAGES;
};

export const selectActiveMode = (state: ChatState) => {
  const active = state.sessions.find((s) => s.id === state.activeChatId);
  return active?.mode ?? state.draftMode;
};
