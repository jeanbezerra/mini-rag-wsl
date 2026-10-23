export interface PublicSettings {
  ollama_model: string;
  temperature: number;
  top_p: number;
  repeat_penalty: number;
  max_output_tokens: number;
  context_tokens: number;
  cpu_threads: number;
  generation_batch_size: number;
  keep_alive_minutes: number;
  generation_timeout_seconds: number;
  retrieval_top_k: number;
  min_similarity: number;
  chunk_tokens: number;
  chunk_overlap: number;
  embedding_batch_size: number;
  max_upload_mb: number;
  max_documents: number;
  max_pdf_pages: number;
  max_text_characters: number;
  max_docx_uncompressed_mb: number;
  max_chunks_per_document: number;
}

export interface SettingsSnapshot { revision: number; updated_at: string | null; values: PublicSettings; defaults: PublicSettings }
export interface InstalledModel { name: string; size_bytes: number; parameter_size?: string | null; quantization_level?: string | null }
export type SettingsKey = keyof PublicSettings;
export type NumericSettingsKey = Exclude<SettingsKey, 'ollama_model'>;
export type SettingsDraft = Record<SettingsKey, string>;
export type SettingsErrors = Partial<Record<SettingsKey, string>>;
export type SettingsGroup = 'answers' | 'performance' | 'retrieval' | 'ingestion';

interface NumericField {
  key: NumericSettingsKey;
  label: string;
  hint: string;
  min: number;
  max: number;
  step?: number;
  unit?: string;
}

export const settingsGroups: { key: SettingsGroup; label: string; description: string; effect: string }[] = [
  { key: 'answers', label: 'Modelo e respostas', description: 'Defina o modelo e o estilo das respostas.', effect: 'Vale para as próximas respostas. Conversas já salvas permanecem como estão.' },
  { key: 'performance', label: 'Velocidade e memória', description: 'Equilibre o tempo de resposta e o uso do seu WSL.', effect: 'Vale para as próximas operações. Salve após concluir a resposta ou ingestão em andamento.' },
  { key: 'retrieval', label: 'Busca nos documentos', description: 'Escolha quanto contexto a IA consulta antes de responder.', effect: 'Vale para as próximas perguntas, inclusive em conversas existentes.' },
  { key: 'ingestion', label: 'Ingestão e limites', description: 'Prepare os documentos e controle o volume de processamento.', effect: 'Vale para novas ingestões e novas tentativas de arquivos com erro. Documentos prontos não são reindexados automaticamente.' },
];

export const numericFields: Record<SettingsGroup, NumericField[]> = {
  answers: [
    { key: 'temperature', label: 'Criatividade (temperatura)', hint: 'Valores baixos deixam as respostas mais previsíveis; valores altos aumentam a variação', min: 0, max: 2, step: 0.05 },
    { key: 'top_p', label: 'Diversidade (top-p)', hint: 'Limita as alternativas de texto consideradas pelo modelo. Reduza para respostas mais focadas', min: 0.05, max: 1, step: 0.05 },
    { key: 'repeat_penalty', label: 'Controle de repetição', hint: '1 mantém o comportamento original. Acima de 1 reduz repetições; valores altos podem prejudicar a fluidez', min: 0.5, max: 2, step: 0.05 },
    { key: 'max_output_tokens', label: 'Tamanho máximo da resposta', hint: 'Limita o texto gerado. Respostas maiores usam mais tempo de CPU; o limite pode cortar uma resposta', min: 128, max: 2048, unit: 'tokens' },
  ],
  performance: [
    { key: 'context_tokens', label: 'Janela de contexto', hint: 'Espaço para instruções, fontes, histórico e resposta. Aumentar exige mais memória; tokens são partes de palavras', min: 4096, max: 16384, unit: 'tokens' },
    { key: 'cpu_threads', label: 'Threads de CPU', hint: 'Mais threads podem acelerar a IA, mas disputam CPU com o WSL. Comece pelo número de núcleos físicos disponíveis', min: 1, max: 128, unit: 'threads' },
    { key: 'generation_batch_size', label: 'Lote de processamento do modelo', hint: 'Um lote maior pode acelerar a leitura do contexto, usando mais memória. Reduza se houver pressão de RAM', min: 32, max: 512, unit: 'tokens' },
    { key: 'keep_alive_minutes', label: 'Modelo mantido na memória', hint: 'Evita recarregar o modelo entre perguntas. 0 libera a memória após cada resposta, com mais espera na próxima', min: 0, max: 60, unit: 'min' },
    { key: 'generation_timeout_seconds', label: 'Tempo máximo de geração', hint: 'Interrompe respostas que excedem esse tempo. Aumente para modelos maiores ou CPUs mais lentas', min: 10, max: 1800, unit: 's' },
  ],
  retrieval: [
    { key: 'retrieval_top_k', label: 'Trechos consultados por pergunta', hint: 'Mais trechos ampliam a cobertura, mas aumentam o contexto e a espera. Menos trechos deixam a busca mais seletiva', min: 1, max: 12, unit: 'trechos' },
    { key: 'min_similarity', label: 'Similaridade mínima', hint: 'Mínimo da busca semântica. Valores altos exigem mais proximidade; correspondências por palavras também participam', min: 0, max: 1, step: 0.05 },
  ],
  ingestion: [
    { key: 'chunk_tokens', label: 'Tamanho dos trechos', hint: 'Trechos maiores preservam mais contexto; menores deixam a busca mais específica. O teto respeita o modelo de embeddings', min: 32, max: 120, unit: 'tokens' },
    { key: 'chunk_overlap', label: 'Sobreposição entre trechos', hint: 'Repete parte do texto entre trechos para preservar a continuidade. Aumentar cria mais trechos e trabalho de indexação', min: 0, max: 32, unit: 'tokens' },
    { key: 'embedding_batch_size', label: 'Lote de embeddings', hint: 'Quantidade de trechos indexados de uma vez. Lotes maiores podem acelerar a ingestão, usando mais memória', min: 1, max: 64, unit: 'trechos' },
    { key: 'max_upload_mb', label: 'Tamanho máximo por arquivo', hint: 'Limita o envio de cada arquivo antes da extração de texto', min: 1, max: 100, unit: 'MB' },
    { key: 'max_documents', label: 'Documentos na biblioteca', hint: 'Limita a quantidade de documentos armazenados. Reduzir não apaga os que já existem', min: 1, max: 10000, unit: 'documentos' },
    { key: 'max_pdf_pages', label: 'Páginas por PDF', hint: 'Limita a quantidade de páginas processadas em cada PDF. Arquivos extensos continuam sujeitos aos outros limites', min: 1, max: 10000, unit: 'páginas' },
    { key: 'max_text_characters', label: 'Texto extraído por documento', hint: 'Limita o volume de texto após a extração, independentemente do tamanho do arquivo', min: 10000, max: 20000000, unit: 'caracteres' },
    { key: 'max_docx_uncompressed_mb', label: 'Conteúdo descompactado do DOCX', hint: 'Limita o conteúdo interno do DOCX ao descompactar, para controlar o consumo de memória', min: 1, max: 200, unit: 'MB' },
    { key: 'max_chunks_per_document', label: 'Trechos por documento', hint: 'Limita a quantidade de embeddings por arquivo. Mais páginas podem exigir elevar este limite também', min: 1, max: 20000, unit: 'trechos' },
  ],
};

export const allNumericFields = Object.values(numericFields).flat();
export function toDraft(values: PublicSettings): SettingsDraft {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, String(value)])) as SettingsDraft;
}

export function validateSettings(draft: SettingsDraft): SettingsErrors {
  const errors: SettingsErrors = {};
  if (!draft.ollama_model.trim()) errors.ollama_model = 'Selecione um modelo disponível';
  for (const field of allNumericFields) {
    const raw = draft[field.key]?.trim();
    const value = Number(raw);
    if (!raw || !Number.isFinite(value)) errors[field.key] = 'Informe um número válido';
    else if (value < field.min || value > field.max) errors[field.key] = `Use um valor entre ${field.min.toLocaleString('pt-BR')} e ${field.max.toLocaleString('pt-BR')}`;
    else if (!field.step && !Number.isInteger(value)) errors[field.key] = 'Informe um número inteiro';
  }
  if (!errors.context_tokens && !errors.max_output_tokens && Number(draft.context_tokens) < Number(draft.max_output_tokens) + 2500) {
    errors.context_tokens = 'Reserve ao menos 2.500 tokens além do tamanho máximo da resposta';
  }
  if (!errors.chunk_overlap && !errors.chunk_tokens && Number(draft.chunk_overlap) >= Number(draft.chunk_tokens)) {
    errors.chunk_overlap = 'Use uma sobreposição menor que o tamanho dos trechos';
  }
  return errors;
}

export function draftValues(draft: SettingsDraft): PublicSettings {
  return { ollama_model: draft.ollama_model.trim(), ...Object.fromEntries(allNumericFields.map(({ key }) => [key, Number(draft[key])])) } as PublicSettings;
}

export function changedSettings(draft: SettingsDraft, saved: PublicSettings): SettingsKey[] {
  return (Object.keys(saved) as SettingsKey[]).filter((key) => key === 'ollama_model' ? draft[key] !== saved[key] : !draft[key].trim() || Number(draft[key]) !== saved[key]);
}

export class SettingsApiError extends Error {
  constructor(public status: number, message: string, public fieldErrors: SettingsErrors = {}, public code?: string) { super(message); this.name = 'SettingsApiError'; }
}

async function settingsRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (response.ok) return response.json() as Promise<T>;
  let payload: { detail?: unknown; message?: string } = {};
  try { payload = await response.json() as typeof payload; } catch { /* Proxy errors can be plain text. */ }
  const detail = payload.detail;
  const object = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail as Record<string, unknown> : {};
  const code = typeof object.code === 'string' ? object.code : undefined;
  const message = typeof detail === 'string' ? detail : typeof object.message === 'string' ? object.message : payload.message;
  const fields: SettingsErrors = {};
  if (Array.isArray(detail)) {
    for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
      const key = item.loc?.at(-1);
      if (typeof key === 'string' && (key === 'ollama_model' || allNumericFields.some((field) => field.key === key))) {
        fields[key as SettingsKey] = 'Valor recusado pelo servidor. Revise este parâmetro';
      }
    }
  }
  const fallback = response.status === 409 ? 'O ambiente está ocupado ou as configurações foram alteradas em outra aba. Seus ajustes foram preservados.' : response.status === 422 ? 'Revise os valores indicados antes de salvar.' : response.status === 503 && path === '/models' ? 'Não foi possível consultar o Ollama. O modelo atual foi mantido; você pode ajustar os demais parâmetros.' : `Não foi possível acessar as configurações (${response.status}). Tente novamente.`;
  throw new SettingsApiError(response.status, message || fallback, fields, code);
}

export const settingsApi = {
  get: (signal?: AbortSignal) => settingsRequest<SettingsSnapshot>('/settings', { signal }),
  save: (revision: number, values: PublicSettings) => settingsRequest<SettingsSnapshot>('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, values }) }),
  models: (signal?: AbortSignal) => settingsRequest<{ models: InstalledModel[] }>('/models', { signal }),
};
