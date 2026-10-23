import type { RagDocument } from './types';

export interface TokenHistogramBin { tokens: number; count: number }
export interface TokenSummary {
  measured_chunks: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  p50: number | null;
  p95: number | null;
}
export interface StructuralIndexing {
  tokens: TokenSummary;
  histogram: TokenHistogramBin[];
  duplicate_chunks: number | null;
  duplicate_ratio: number | null;
}
export interface LibrarySummary {
  documents: { total: number; queued: number; processing: number; ready: number; error: number };
  storage_bytes: number;
  chunks: number;
  formats: { extension: string; documents: number; size_bytes: number }[];
  largest_documents: { id: string; name: string; chunk_count: number }[];
  indexing: StructuralIndexing & {
    measured_documents: number;
    legacy_documents: number;
    total_pages: number | null;
    text_pages: number | null;
    empty_pages: number | null;
  };
}
export interface LibraryDocument extends RagDocument {
  extension: string;
  updated_at: string;
  error: string | null;
  ingestion_ms: number | null;
  extracted_characters: number | null;
  total_pages: number | null;
  text_pages: number | null;
}
export interface LibraryDocumentList {
  documents: LibraryDocument[];
  total: number;
  page: number;
  page_size: number;
}
export interface DocumentDetail {
  document: LibraryDocument;
  indexing: StructuralIndexing;
  ingestion: {
    duration_ms: number;
    extraction_ms: number;
    embedding_ms: number;
    finished_at: string;
    settings: Record<string, number | string>;
  } | null;
  chunks: {
    items: { id: string; ordinal: number; page: number | null; content: string; token_count: number | null; char_count: number }[];
    total: number;
    page: number;
    page_size: number;
  };
}
export interface Percentiles { p50: number | null; p95: number | null }
export type ChatOutcome = 'completed' | 'no_sources' | 'error' | 'cancelled';
export type IngestionOutcome = 'completed' | 'error';
export interface ChatMeasurement {
  id: string;
  created_at: string;
  model: string;
  outcome: ChatOutcome;
  duration_ms: number;
  search_ms: number | null;
  first_token_ms: number | null;
  output_tokens: number | null;
  tokens_per_second: number | null;
}
export interface IngestionMeasurement {
  id: string;
  document_name: string;
  created_at: string;
  outcome: IngestionOutcome;
  duration_ms: number;
  chunks: number | null;
  extraction_ms: number | null;
  embedding_ms: number | null;
}
export interface LibraryPerformance {
  window: { limit: number; from: string | null; to: string | null };
  models: string[];
  chat: {
    samples: number;
    completed: number;
    no_sources: number;
    error: number;
    cancelled: number;
    latency_ms: Percentiles;
    search_ms: Percentiles;
    first_token_ms: Percentiles;
    tokens_per_second: Percentiles;
    output_tokens: number;
  };
  ingestion: {
    samples: number;
    completed: number;
    error: number;
    duration_ms: Percentiles;
    chunks_per_second: Percentiles;
  };
  recent_chat: ChatMeasurement[];
  recent_ingestion: IngestionMeasurement[];
}
export type LibrarySort = 'newest' | 'name' | 'size' | 'chunks';
export type LibraryStatus = RagDocument['status'] | '';
