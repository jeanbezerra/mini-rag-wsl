import { describe, expect, it, vi, afterEach } from 'vitest';
import { readChatStream, sendChat } from './api';
import type { ChatEvent, Message } from './types';

function stream(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({ start(controller) { chunks.forEach((chunk) => controller.enqueue(chunk)); controller.close(); } });
}

describe('NDJSON chat transport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('preserves accented text split across UTF-8 bytes and JSON lines', async () => {
    const payload = new TextEncoder().encode('\n{"type":"sources","sources":[]}\r\n{"type":"token","content":"Informação útil"}\n{"type":"done"}');
    const events: ChatEvent[] = [];
    await readChatStream(stream(Array.from(payload, (byte) => new Uint8Array([byte]))), (event) => events.push(event));
    expect(events).toEqual([{ type: 'sources', sources: [] }, { type: 'token', content: 'Informação útil' }, { type: 'done' }]);
  });

  it('rejects an incomplete response rather than marking partial text complete', async () => {
    const bytes = new TextEncoder().encode('{"type":"token","content":"parcial"}\n');
    const onEvent = vi.fn();
    await expect(readChatStream(stream([bytes]), onEvent)).rejects.toThrow('interrompida');
    expect(onEvent).toHaveBeenCalledWith({ type: 'token', content: 'parcial' });
  });

  it('surfaces an explicit server error', async () => {
    const bytes = new TextEncoder().encode('{"type":"error","message":"Modelo indisponível"}\n');
    await expect(readChatStream(stream([bytes]), vi.fn())).rejects.toThrow('Modelo indisponível');
  });

  it('rejects malformed JSON with a readable message', async () => {
    await expect(readChatStream(stream([new TextEncoder().encode('{invalid}\n')]), vi.fn())).rejects.toThrow('resposta inválida');
  });

  it('cancels a pending reader when the user interrupts generation', async () => {
    const cancel = vi.fn();
    const controller = new AbortController();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const result = readChatStream(body, vi.fn(), controller.signal);
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('sends selected document IDs and bounded completed history', async () => {
    const history: Message[] = Array.from({ length: 24 }, (_, i) => ({ id: String(i), role: i % 2 ? 'assistant' : 'user', content: 'a'.repeat(5000), state: 'complete' }));
    history.push({ id: 'failed', role: 'assistant', content: 'partial failure', state: 'error' });
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"type":"done"}\n', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await sendChat('Qual é o resultado?', history, ['document-1'], vi.fn(), new AbortController().signal);
    const [url, init] = fetchMock.mock.calls[0];
    const payload = JSON.parse(init.body);
    expect(url).toBe('/api/chat');
    expect(payload.message).toBe('Qual é o resultado?');
    expect(payload.document_ids).toEqual(['document-1']);
    expect(payload.history).toHaveLength(12);
    expect(payload.history.every((message: Message) => message.content.length === 4000)).toBe(true);
    expect(payload.history.some((message: Message) => message.content === 'partial failure')).toBe(false);
  });

  it('presents API errors without trying to parse an NDJSON stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Aguarde a indexação.' }), { status: 409, headers: { 'Content-Type': 'application/json' } })));
    await expect(sendChat('Pergunta', [], [], vi.fn(), new AbortController().signal)).rejects.toThrow('Aguarde a indexação.');
  });
});
