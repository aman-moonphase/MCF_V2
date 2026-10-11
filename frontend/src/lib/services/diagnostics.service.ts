import { apiClient } from '../api-client';

/**
 * Status of one diagnostic check (backend: app/schemas/diagnostics.py).
 * "Not checked" = the check did not run because something it depends on failed (it did not fail itself).
 */
export type DiagnosticStatus =
  | 'Healthy' | 'Warning' | 'Degraded' | 'Unavailable' | 'Unknown' | 'Not checked' | 'Not configured' | 'Ready' | 'Enabled';

export interface OverallDiagnostic {
  status: DiagnosticStatus;
  message?: string;
}

export interface BackendDiagnostic {
  status: DiagnosticStatus;
  message?: string;
}

export interface DatabaseDiagnostic {
  status: DiagnosticStatus;
  message?: string;
}

export interface VectorStoreDiagnostic {
  status: DiagnosticStatus;
  extension?: string;
  message?: string;
}

export interface MigrationDiagnostic {
  status: DiagnosticStatus;
  currentRevision?: string | null;
  headRevision?: string | null;
  message?: string;
}

export interface AIDiagnostic {
  status: DiagnosticStatus;
  provider: string;
  model: string;
  message?: string;
  mode?: 'demo' | 'real';
  /** A boolean only — the value is never sent. */
  credentialsConfigured?: boolean;
  /** Always false: diagnostics never call the provider. */
  connectionVerified?: boolean;
  mayIncurCharges?: boolean;
  singleAttempt?: boolean;
}

export interface EmbeddingDiagnostic {
  status: DiagnosticStatus;
  provider: string;
  message?: string;
  model?: string | null;
  /** True when vectors carry meaning (semantic retrieval); demo embeddings are keyword-only. */
  semantic?: boolean;
  credentialsConfigured?: boolean;
}

export interface RAGDiagnostic {
  status: DiagnosticStatus;
  message?: string;
}

export interface IngestionDiagnostic {
  status: DiagnosticStatus;
  message?: string;
  sourcesTotal: number;
  /** Status → count. Status values are data, kept exactly as stored (e.g. completed, failed, duplicate). */
  sourcesByStatus: Record<string, number>;
  chunksTotal: number;
  staleChunks: number;
  /** Chunks indexed before embedding details were recorded, or by another provider/model (keyword-ranked). */
  otherEmbeddingChunks: number;
  failedSources: { name: string; updatedAt?: string | null }[];
}

export interface EnvironmentDiagnostic {
  mode: string;
  message?: string;
}

export interface DiagnosticsResponse {
  checkedAt?: string | null;
  overall?: OverallDiagnostic | null;
  backend: BackendDiagnostic;
  database: DatabaseDiagnostic;
  vectorStore: VectorStoreDiagnostic;
  migration?: MigrationDiagnostic | null;
  ai: AIDiagnostic;
  embeddings: EmbeddingDiagnostic;
  rag: RAGDiagnostic;
  ingestion?: IngestionDiagnostic | null;
  environment: EnvironmentDiagnostic;
}

export const DiagnosticsService = {
  async getDiagnostics(): Promise<DiagnosticsResponse> {
    return apiClient.get('/diagnostics/');
  }
};
