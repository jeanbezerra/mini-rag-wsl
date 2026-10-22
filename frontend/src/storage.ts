import type { Conversation } from './types';

export const STORAGE_KEY = 'mini-rag.conversations.v1';

export function loadConversations(): Conversation[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is Conversation =>
      item && typeof item.id === 'string' && typeof item.title === 'string' &&
      typeof item.createdAt === 'string' && Array.isArray(item.messages) &&
      item.messages.every((message: unknown) => {
        if (!message || typeof message !== 'object') return false;
        const value = message as Record<string, unknown>;
        return typeof value.id === 'string' && ['user', 'assistant'].includes(String(value.role)) && typeof value.content === 'string';
      }),
    ).slice(0, 40).map((conversation) => ({
      ...conversation,
      messages: conversation.messages.map((message) => message.role === 'assistant' && !message.state
        ? { ...message, state: 'interrupted' }
        : message),
    }));
  } catch { return []; }
}

export function newConversation(): Conversation {
  return { id: crypto.randomUUID(), title: 'Nova conversa', createdAt: new Date().toISOString(), messages: [] };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} KB`;
  return `${(bytes / 1024 ** 2).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`;
}
