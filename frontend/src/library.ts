import type { DocumentDetail, LibraryDocumentList, LibraryPerformance, LibrarySort, LibraryStatus, LibrarySummary, TokenHistogramBin } from './libraryTypes';

export class LibraryApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'LibraryApiError'; }
}
async function request<T>(path: string, signal?: AbortSignal, method = 'GET'): Promise<T> {
  const response = await fetch(`/api/library${path}`, { signal, method });
  if (!response.ok) {
    let message = `Não foi possível carregar a biblioteca (${response.status}). Tente novamente.`;
    try {
      const payload = await response.json() as { detail?: unknown };
      if (typeof payload.detail === 'string') message = payload.detail;
    } catch { /* A proxy may send a non-JSON response. */ }
    throw new LibraryApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
export const libraryApi = {
  summary: (signal?: AbortSignal) => request<LibrarySummary>('/summary', signal),
  documents: (filters: { q: string; status: LibraryStatus; sort: LibrarySort; page: number; page_size?: number }, signal?: AbortSignal) => {
    const query = new URLSearchParams({ q: filters.q, sort: filters.sort, page: String(filters.page), page_size: String(filters.page_size ?? 20) });
    if (filters.status) query.set('status', filters.status);
    return request<LibraryDocumentList>(`/documents?${query}`, signal);
  },
  detail: (id: string, page: number, signal?: AbortSignal) => request<DocumentDetail>(`/documents/${encodeURIComponent(id)}?page=${page}&page_size=8`, signal),
  performance: (model: string, signal?: AbortSignal) => request<LibraryPerformance>(`/performance${model ? `?model=${encodeURIComponent(model)}` : ''}`, signal),
  reindex: (id: string) => request(`/documents/${encodeURIComponent(id)}/reindex`, undefined, 'POST'),
};

export function groupedHistogram(histogram: TokenHistogramBin[]) {
  const bins = [{ label: '1–32', max: 32, count: 0 }, { label: '33–64', max: 64, count: 0 }, { label: '65–96', max: 96, count: 0 }, { label: '97–128', max: 128, count: 0 }];
  for (const item of histogram) {
    const bin = bins.find((candidate) => item.tokens <= candidate.max);
    if (bin && item.tokens > 0) bin.count += item.count;
  }
  return bins;
}
export function formatNumber(value: number | null | undefined, digits = 0) {
  return value == null ? '—' : value.toLocaleString('pt-BR', { maximumFractionDigits: digits });
}
export function formatDuration(milliseconds: number | null | undefined) {
  if (milliseconds == null) return '—';
  if (milliseconds < 1000) return `${formatNumber(milliseconds)} ms`;
  if (milliseconds < 60000) return `${formatNumber(milliseconds / 1000, 1)} s`;
  return `${formatNumber(milliseconds / 60000, 1)} min`;
}
export function formatDate(iso: string) {
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
export function percent(numerator: number, denominator: number) {
  return denominator > 0 ? `${formatNumber(numerator / denominator * 100, 1)}%` : '—';
}
