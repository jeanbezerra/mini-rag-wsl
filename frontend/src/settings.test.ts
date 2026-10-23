import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  changedSettings, draftValues, SettingsApiError, settingsApi, toDraft, validateSettings,
  type PublicSettings,
} from './settings';

const values: PublicSettings = {
  ollama_model: 'qwen3:1.7b-q4_K_M', temperature: 0.15, top_p: 0.9, repeat_penalty: 1,
  max_output_tokens: 512, context_tokens: 4096, cpu_threads: 4, generation_batch_size: 128,
  keep_alive_minutes: 10, generation_timeout_seconds: 300, retrieval_top_k: 6, min_similarity: 0.3,
  chunk_tokens: 110, chunk_overlap: 16, embedding_batch_size: 16, max_upload_mb: 25,
  max_documents: 200, max_pdf_pages: 500, max_text_characters: 2000000,
  max_docx_uncompressed_mb: 50, max_chunks_per_document: 2000,
};

describe('global settings validation', () => {
  it('round-trips values and permits explicitly disabling keep-alive', () => {
    const draft = toDraft({ ...values, keep_alive_minutes: 0, temperature: 0, min_similarity: 0 });
    expect(validateSettings(draft)).toEqual({});
    expect(draftValues(draft)).toEqual({ ...values, keep_alive_minutes: 0, temperature: 0, min_similarity: 0 });
  });

  it('permits PDFs above the former 500-page ceiling within the configured bounds', () => {
    expect(validateSettings(toDraft({ ...values, max_pdf_pages: 2500, max_chunks_per_document: 15000 }))).toEqual({});
    expect(validateSettings(toDraft({ ...values, max_pdf_pages: 10001 }))).toHaveProperty('max_pdf_pages');
  });

  it('requires room for instructions and sources beyond the generated answer', () => {
    expect(validateSettings(toDraft({ ...values, max_output_tokens: 2048, context_tokens: 4096 })).context_tokens).toContain('2.500');
    expect(validateSettings(toDraft({ ...values, max_output_tokens: 2048, context_tokens: 4548 }))).toEqual({});
  });

  it('prevents an overlap as large as the text chunk and allows zero overlap', () => {
    expect(validateSettings(toDraft({ ...values, chunk_tokens: 32, chunk_overlap: 32 }))).toHaveProperty('chunk_overlap');
    expect(validateSettings(toDraft({ ...values, chunk_tokens: 32, chunk_overlap: 0 }))).toEqual({});
  });

  it('rejects empty, non-finite and fractional integer inputs without coercing blanks to zero', () => {
    const draft = { ...toDraft(values), keep_alive_minutes: ' ', top_p: 'Infinity', cpu_threads: '3.5', ollama_model: '' };
    expect(Object.keys(validateSettings(draft)).sort()).toEqual(['cpu_threads', 'keep_alive_minutes', 'ollama_model', 'top_p']);
  });

  it('tracks unsaved changes by their value, so equivalent number formatting is clean', () => {
    const draft = { ...toDraft(values), temperature: '0.150', max_pdf_pages: '1000' };
    expect(changedSettings(draft, values)).toEqual(['max_pdf_pages']);
    expect(changedSettings({ ...toDraft(values), keep_alive_minutes: '' }, values)).toEqual(['keep_alive_minutes']);
  });
});

describe('settings API contract', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends the saved revision and complete editable values in one atomic update', async () => {
    const snapshot = { revision: 4, updated_at: null, values, defaults: values };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot)));
    vi.stubGlobal('fetch', fetchMock);
    expect(await settingsApi.save(3, values)).toEqual(snapshot);
    expect(fetchMock).toHaveBeenCalledWith('/api/settings', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ revision: 3, values }) }));
  });

  it.each(['runtime_busy', 'settings_conflict'])('keeps the server conflict code available: %s', async (code) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code, message: 'Aguarde ou revise os valores.' } }), { status: 409 })));
    await expect(settingsApi.save(1, values)).rejects.toMatchObject({ name: 'SettingsApiError', status: 409, code });
  });

  it('maps server validation to editable fields without displaying internal validation details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ loc: ['body', 'values', 'max_pdf_pages'], msg: 'Input should be less than or equal to 10000' }, { loc: ['body', 'database_url'], msg: 'Internal details' }] }), { status: 422 })));
    try { await settingsApi.save(1, values); throw new Error('Expected validation error'); }
    catch (cause) {
      expect(cause).toBeInstanceOf(SettingsApiError);
      expect((cause as SettingsApiError).fieldErrors).toEqual({ max_pdf_pages: 'Valor recusado pelo servidor. Revise este parâmetro' });
      expect((cause as Error).message).not.toContain('Internal');
    }
  });

  it('handles unavailable model discovery separately from settings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('proxy unavailable', { status: 503 })));
    await expect(settingsApi.models()).rejects.toMatchObject({ status: 503, message: expect.stringContaining('demais parâmetros') });
  });

  it('forwards cancellation when loading settings', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ revision: 1, values, defaults: values, updated_at: null })));
    vi.stubGlobal('fetch', fetchMock);
    await settingsApi.get(controller.signal);
    expect(fetchMock).toHaveBeenCalledWith('/api/settings', { signal: controller.signal });
  });
});
