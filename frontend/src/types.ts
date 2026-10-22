export interface RagDocument {
  id: string;
  name: string;
  size_bytes: number;
  status: 'queued' | 'processing' | 'ready' | 'error';
  chunk_count: number;
  created_at: string;
  error?: string | null;
}

export interface Health {
  status: 'ok' | 'degraded';
  database: { status: string; version?: string };
  model: { status: string; name: string };
  embedding: { status: string; name: string };
  limits?: { max_upload_mb?: number };
}

export interface Source {
  id: string;
  document_id: string;
  name: string;
  page: number | null;
  content: string;
  score: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  state?: 'complete' | 'interrupted' | 'error';
  error?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  messages: Message[];
}

export type ChatEvent =
  | { type: 'sources'; sources: Source[] }
  | { type: 'token'; content: string }
  | { type: 'done' }
  | { type: 'error'; message: string };
