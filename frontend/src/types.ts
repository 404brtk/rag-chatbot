export type ChatMode = 'direct' | 'side-by-side';

export type AttachmentKind = 'document' | 'image';

export interface MessageAttachment {
  id: string;
  name: string;
  size: number;
  mimeType: string;
  kind: AttachmentKind;
}

export interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  mode: ChatMode;
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
  attachments?: MessageAttachment[];
}

export interface AppRouteContext {
  sessions: ChatSession[];
  activeChatId: string | null;
  messages: ChatMessage[];
  isTyping: boolean;
  handleSend: (message: string, attachments?: MessageAttachment[]) => void;
  handleNewChat: () => void;
  handleSelectChat: (id: string) => void;
  handleDeleteChat: (id: string) => void;
  handleRenameChat: (id: string, title: string) => void;
}
