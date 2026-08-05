export type ChatMode = 'direct' | 'side-by-side';

export type AttachmentKind = 'document' | 'image';

export interface MessageAttachment {
  id: string;
  name: string;
  size: number;
  mimeType: string;
  kind: AttachmentKind;
  backendId?: string;
  uploading?: boolean;
  content?: string;
  url?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  mode: ChatMode;
  messages: ChatMessage[];
  loaded?: boolean;
  nextCursor?: string | null;
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
  is_compaction_summary?: boolean;
  variant?: 'rag_on' | 'rag_off';
}

export interface DocumentData {
  id: string;
  filename: string;
  content_type: string;
  language: string;
  status?: 'pending' | 'in_progress' | 'completed' | 'failed';
  error_message?: string | null;
  created_at: string;
}

export interface CursorPaginated<T> {
  results: T[];
  next?: string | null;
  count?: number;
}
