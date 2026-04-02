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
