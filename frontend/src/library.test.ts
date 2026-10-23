import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatDuration, formatNumber, groupedHistogram, libraryApi, percent } from './library';

describe('library metrics presentation', () => {
  it('keeps missing measurements distinct from real zeroes', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(formatDuration(0)).toBe('0 ms');
    expect(formatNumber(0)).toBe('0');
    expect(percent(0, 0)).toBe('—');
    expect(percent(0, 100)).toBe('0%');
  });

  it('groups actual token counts into non-overlapping ranges without losing boundaries', () => {
    const bins = groupedHistogram([{ tokens: 1, count: 2 }, { tokens: 32, count: 3 }, { tokens: 33, count: 7 }, { tokens: 64, count: 11 }, { tokens: 65, count: 13 }, { tokens: 96, count: 17 }, { tokens: 97, count: 19 }, { tokens: 128, count: 23 }]);
    expect(bins.map((bin) => bin.count)).toEqual([5, 18, 30, 42]);
    expect(bins.reduce((sum, bin) => sum + bin.count, 0)).toBe(95);
    expect(groupedHistogram([]).every((bin) => bin.count === 0)).toBe(true);
  });

  it('uses readable duration units without converting absence into a value', () => {
    expect(formatDuration(400)).toBe('400 ms');
    expect(formatDuration(1250)).toBe('1,3 s');
    expect(formatDuration(90000)).toBe('1,5 min');
  });
});

describe('advanced library API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('omits the optional status filter when all states are selected', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ documents: [], total: 0, page: 2, page_size: 20 })));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    await libraryApi.documents({ q: 'guia Java', status: '', sort: 'chunks', page: 2 }, controller.signal);
    const [path, options] = fetchMock.mock.calls[0];
    const url = new URL(path, 'http://localhost');
    expect(url.searchParams.has('status')).toBe(false);
    expect(url.searchParams.get('q')).toBe('guia Java');
    expect(url.searchParams.get('page')).toBe('2');
    expect(options.signal).toBe(controller.signal);
  });

  it('sends server-side state filters and bounded page sizes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    await libraryApi.documents({ q: '', status: 'error', sort: 'newest', page: 1 });
    expect(fetchMock.mock.calls[0][0]).toContain('status=error');
    expect(fetchMock.mock.calls[0][0]).toContain('page_size=20');
  });

  it('encodes document and model identifiers and keeps reindex explicit', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}')));
    vi.stubGlobal('fetch', fetchMock);
    await libraryApi.detail('id/with spaces', 3);
    await libraryApi.performance('qwen3:1.7b-q4_K_M');
    await libraryApi.reindex('doc/1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/library/documents/id%2Fwith%20spaces?page=3&page_size=8');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/library/performance?model=qwen3%3A1.7b-q4_K_M');
    expect(fetchMock.mock.calls[2]).toEqual(['/api/library/documents/doc%2F1/reindex', expect.objectContaining({ method: 'POST' })]);
  });

  it('retains useful conflict messages and handles a proxy without JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'O arquivo já está em processamento.' }), { status: 409 })).mockResolvedValueOnce(new Response('proxy error', { status: 503 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(libraryApi.reindex('doc')).rejects.toMatchObject({ status: 409, message: 'O arquivo já está em processamento.' });
    await expect(libraryApi.summary()).rejects.toMatchObject({ status: 503, message: expect.stringContaining('503') });
  });
});
