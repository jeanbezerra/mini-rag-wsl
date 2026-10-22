import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, loadConversations } from './storage';

describe('local conversation persistence', () => {
  afterEach(() => vi.unstubAllGlobals());
  const saved = (value: unknown) => vi.stubGlobal('localStorage', { getItem: () => JSON.stringify(value) });

  it('discards malformed history entries', () => {
    saved([{ id: 'bad' }, { id: 'bad2', title: 'x', createdAt: 'now', messages: [{ id: 'x', role: 'script', content: 'x' }] }]);
    expect(loadConversations()).toEqual([]);
  });

  it('marks an unfinished response as interrupted after reload', () => {
    saved([{ id: 'chat', title: 'Pergunta', createdAt: '2026-01-01', messages: [{ id: 'u', role: 'user', content: 'Pergunta' }, { id: 'a', role: 'assistant', content: 'Texto parcial' }] }]);
    expect(loadConversations()[0].messages[1].state).toBe('interrupted');
  });

  it('recovers from unavailable browser storage', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('Denied'); } });
    expect(loadConversations()).toEqual([]);
  });

  it('formats actual file sizes in Portuguese', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1536)).toBe('1,5 KB');
    expect(formatBytes(2 * 1024 * 1024)).toBe('2 MB');
  });
});
