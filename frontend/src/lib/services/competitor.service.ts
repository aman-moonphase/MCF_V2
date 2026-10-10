import { apiClient } from '@/lib/api-client';
import { errorFromResponse } from '@/lib/api-errors';

export interface Finding {
  statement: string;
  status: 'observed' | 'inferred';
  refs: string[];
}

export interface Reference {
  kind: string;
  evidenceId?: string | null;
  title?: string | null;
  url?: string | null;
  competitor?: string;
}

export interface CompetitorAnalysis {
  overview: Finding[];
  positioning: Finding[];
  targetAudience: Finding[];
  overlappingFeatures: Finding[];
  messagingThemes: Finding[];
  promotionChannels: Finding[];
  contentFormats: Finding[];
  contentExamples: { description: string; ref: string; excerpt: string }[];
  postingCadence: Finding[];
  strengths: Finding[];
  opportunitiesForUs: Finding[];
  coverage: Record<string, 'observed' | 'inferred' | 'unknown'>;
  unknowns: string[];
  /** Section keys with no findings (shown as empty sections, never as unknown items). */
  unknownSections?: string[];
  performanceData: string;
  confidence: 'low' | 'medium' | 'high';
  references: Record<string, Reference>;
  provider?: string;
}

export interface Suggestion {
  suggestion: string;
  rationale: string;
  refs: string[];
}

export interface Comparison {
  similarities: Finding[];
  differences: Finding[];
  messagingGaps: Finding[];
  positioningOpportunities: Suggestion[];
  promotionPatternsToInvestigate: Suggestion[];
  evidenceNeeded: string[];
  references: Record<string, Reference>;
  provider?: string;
}

export interface Evidence {
  id: string;
  evidenceType: 'url' | 'note' | 'pdf';
  sourceUrl?: string | null;
  title?: string | null;
  status: 'completed' | 'failed' | 'not_fetched';
  error?: string | null;
  excerpt?: string | null;
  charCount: number;
}

export interface Competitor {
  id: string;
  name: string;
  websiteUrl?: string | null;
  description?: string | null;
  notes?: string | null;
  origin: 'user' | 'product_sources' | 'ai_suggested';
  suggestionReason?: string | null;
  verification: 'user_added' | 'named_in_sources' | 'unverified' | 'evidence_backed';
  analysisStatus: 'not_analyzed' | 'analyzed' | 'insufficient_evidence' | 'failed';
  analysis?: CompetitorAnalysis | null;
  analysisError?: string | null;
  lastAnalyzedAt?: string | null;
  evidence: Evidence[];
}

export interface CompetitorAnalysisState {
  productId: string;
  productName: string;
  productProfileApproved: boolean;
  productSummary: Record<string, string | string[] | null>;
  status: 'locked' | 'not_started' | 'in_progress' | 'ready_for_review' | 'approved';
  version: number;
  approvedVersion?: number | null;
  approvedAt?: string | null;
  limitedEvidence: boolean;
  comparison?: Comparison | null;
  comparisonOutdated: boolean;
  competitors: Competitor[];
}

export interface CompetitorInput {
  name?: string;
  websiteUrl?: string | null;
  description?: string | null;
  notes?: string | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
const base = (productId: string) => `/products/${productId}`;

export const CompetitorService = {
  getState: (productId: string): Promise<CompetitorAnalysisState> => apiClient.get(`${base(productId)}/competitor-analysis`),

  create: (productId: string, input: CompetitorInput): Promise<Competitor> => apiClient.post(`${base(productId)}/competitors`, input),

  update: (productId: string, competitorId: string, input: CompetitorInput): Promise<Competitor> =>
    apiClient.patch(`${base(productId)}/competitors/${competitorId}`, input),

  remove: (productId: string, competitorId: string) => apiClient.delete(`${base(productId)}/competitors/${competitorId}`),

  discover: (productId: string): Promise<{ added: string[]; messages: string[]; state: CompetitorAnalysisState }> =>
    apiClient.post(`${base(productId)}/competitors/discover`, {}),

  /** Evidence is multipart (a PDF may be attached), so it bypasses the JSON client. */
  addEvidence: async (productId: string, competitorId: string, type: 'url' | 'note' | 'pdf', content: string, file?: File | null) => {
    const form = new FormData();
    form.append('evidence_type', type);
    if (content) form.append('content', content);
    if (file) form.append('file', file);
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    const res = await fetch(`${API_URL}${base(productId)}/competitors/${competitorId}/evidence`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!res.ok) throw await errorFromResponse(res);
    const data = await res.json();
    return { status: data.status as Evidence['status'], error: data.error as string | null };
  },

  removeEvidence: (productId: string, competitorId: string, evidenceId: string) =>
    apiClient.delete(`${base(productId)}/competitors/${competitorId}/evidence/${evidenceId}`),

  analyze: (productId: string, competitorId: string): Promise<Competitor> =>
    apiClient.post(`${base(productId)}/competitors/${competitorId}/analyze`, {}),

  compare: (productId: string): Promise<CompetitorAnalysisState> => apiClient.post(`${base(productId)}/competitor-comparison`, {}),

  approve: (productId: string, projectId: string, version: number, limitedEvidence = false): Promise<CompetitorAnalysisState> =>
    apiClient.post(`${base(productId)}/competitor-analysis/approve`, { projectId, version, limitedEvidence }),
};
