export type ChatMode = 'direct' | 'side-by-side';

export interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  messages: ChatMessage[];
}

export interface CitationData {
  id: string | number;
  sourceName: string;
  snippet: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  citations?: CitationData[];
}

export interface AppRouteContext {
  sessions: ChatSession[];
  activeChatId: string | null;
  messages: ChatMessage[];
  isTyping: boolean;
  handleSend: (message: string) => void;
  handleNewChat: () => void;
  handleSelectChat: (id: string) => void;
  handleDeleteChat: (id: string) => void;
  handleRenameChat: (id: string, title: string) => void;
}
