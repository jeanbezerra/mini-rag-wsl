import type { ChatEvent, Health, Message, RagDocument } from './types';

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Não foi possível concluir a operação.';
}

async function responseError(response: Response): Promise<Error> {
  try {
    const payload = await response.json() as { detail?: unknown; message?: string };
    if (typeof payload.detail === 'string') return new Error(payload.detail);
    if (payload.message) return new Error(payload.message);
  } catch { /* The server may return a plain-text proxy error. */ }
  return new Error(response.status === 413 ? 'O arquivo excede o limite de envio.' : `O servidor retornou um erro (${response.status}). Tente novamente.`);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', { signal }),
  documents: (signal?: AbortSignal) => request<{ documents: RagDocument[] }>('/documents', { signal }),
  deleteDocument: (id: string) => request<void>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  retryDocument: (id: string) => request<RagDocument>(`/documents/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
};

/** XHR reports actual bytes uploaded; ingestion progress comes from server document status. */
export function uploadDocument(file: File, onProgress: (progress: number) => void): Promise<RagDocument> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/documents');
    xhr.responseType = 'json';
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new Error('A conexão foi interrompida durante o envio. Tente novamente.'));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as RagDocument);
      else {
        const detail: unknown = xhr.response?.detail;
        reject(new Error(typeof detail === 'string' ? detail : xhr.status === 413 ? 'O arquivo excede o limite de envio.' : `Não foi possível enviar ${file.name} (${xhr.status}).`));
      }
    };
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}

/** Decode incrementally: network chunks can split both JSON lines and UTF-8 code points. */
export async function readChatStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  const consume = (line: string) => {
    if (!line.trim()) return;
    let event: ChatEvent;
    try { event = JSON.parse(line) as ChatEvent; }
    catch { throw new Error('O servidor enviou uma resposta inválida. Tente novamente.'); }
    if (event.type === 'error') throw new Error(event.message || 'O modelo não conseguiu responder.');
    if (event.type === 'done') completed = true;
    if (['sources', 'token', 'done'].includes(event.type)) onEvent(event);
  };
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    for (;;) {
      signal?.throwIfAborted();
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      buffer += decoder.decode(value, { stream: !done });
      let newline: number;
      while ((newline = buffer.indexOf('\n')) !== -1) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (completed) return;
      if (done) break;
    }
    consume(buffer);
    if (!completed) throw new Error('A resposta foi interrompida antes de terminar. Tente novamente.');
  } finally {
    signal?.removeEventListener('abort', abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function sendChat(
  message: string,
  history: Message[],
  documentIds: string[],
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      history: history.filter((item) => item.content.trim() && item.state !== 'error' && item.state !== 'interrupted').slice(-12).map(({ role, content }) => ({ role, content: content.slice(0, 4000) })),
      ...(documentIds.length ? { document_ids: documentIds } : {}),
    }),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new Error('Este navegador não oferece suporte a respostas em tempo real.');
  await readChatStream(response.body, onEvent, signal);
}
