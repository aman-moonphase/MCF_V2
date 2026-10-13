import { apiClient } from '@/lib/api-client';

export interface PostClaim {
  text: string;
  kind: 'product_fact' | 'creative' | 'competitor_context';
  refs: string[];
}

export interface LinkedInPost {
  hook: string;
  alternativeHooks: string[];
  body: string;
  cta: string;
  hashtags: string[];
  claims: PostClaim[];
  pillar: string;
  strategyAlignment: string;
  limitations: string[];
}

/** API usage of the request(s) that generated a post (backend: app/ai/usage.py). Null in Demo Mode. */
export interface GenerationUsage {
  generatedVersion: number;
  provider: string;
  models: string[];
  requestCount: number;
  failedRequests: number;
  totals: { inputTokens: number; outputTokens: number; cacheCreationInputTokens: number; cacheReadInputTokens: number };
  durationMs: number;
  estimatedCostUsd: number | null;
  costIsEstimate: boolean;
  costNote: string;
}

export interface GeneratedDraft {
  id: string;
  content: LinkedInPost;
  validation?: {
    warnings?: string[];
    unsupportedClaims?: string[];
    characterCount?: number;
    platformLimit?: number;
    withinLimit?: boolean;
  } | null;
  status: 'draft' | 'approved';
  version: number;
  edited: boolean;
  provider?: string | null;
  isDemo: boolean;
  generatedAt?: string | null;
  editedAt?: string | null;
  approvedVersion?: number | null;
  usage?: GenerationUsage | null;
  approvedAt?: string | null;
  contextSnapshot?: {
    pillar?: string;
    pillarIndex?: number;
    instructions?: string;
    audiencePersona?: string;
    editorialTone?: string;
    emphasis?: string | null;
    limitedEvidence?: boolean;
  } | null;
  evidence: { ref: string; description: string }[];
  image?: ContentImageAsset | null;
}

export interface ContentImageAsset {
  id: string;
  projectId: string;
  generatedContentId: string;
  contentVersion: number;
  versionMatchesPost: boolean;
  prompt: string;
  altText: string;
  imageUrl: string;
  aspectRatio: string;
  style: string;
  provider: string;
  isDemo: boolean;
  status: 'generated' | 'saved';
  createdAt?: string;
  updatedAt?: string;
}

export interface CompetitorFinding {
  statement: string;
  status: 'observed' | 'inferred';
  refs: string[];
  section: string;
}

/** The approved competitor comparison, in the groups the generator receives (backend: competitor_findings). */
export interface CompetitorFindings {
  differences: CompetitorFinding[];  // evidence-based differences and messaging gaps
  similarities: CompetitorFinding[];  // possible overlaps — not unique advantages
  suggestions: { suggestion: string; rationale: string; refs: string[]; section: string }[];  // not facts
  unresolved: { competitor: string; feature: string }[];  // unknown — never "the competitor lacks it"
}

export interface GenerationContext {
  productId: string;
  productName: string;
  targetAudience?: string | null;
  problemSolved?: string | null;
  valueProposition?: string | null;
  keyFeatures: string[];
  differentiators: string[];
  messagingDirection?: string | null;
  pillars: { name: string; purpose: string }[];
  availablePersonas?: string[];
  availableTones?: string[];
  selectedPersona?: string | null;
  selectedTone?: string | null;
  primaryChannel?: string | null;
  approvedType?: string | null;
  limitedEvidence: boolean;
  /** Null when competitor evidence was limited or the comparison is not approved and current. */
  competitor?: CompetitorFindings | null;
}

export interface GenerationState {
  projectId: string;
  status: 'not_applicable' | 'blocked' | 'not_generated' | 'draft' | 'approved';
  canGenerate: boolean;
  blockingProblem?: string | null;
  prerequisites: { key: string; label: string; met: boolean; detail?: string | null }[];
  context?: GenerationContext | null;
  draft?: GeneratedDraft | null;
  stale: boolean;
  staleReasons: string[];
  policy: { platform: string; contentType: string; maxChars: number; hookMaxChars: number; maxHashtags: number };
  provider: string;
}

export type PostEdits = Partial<Pick<LinkedInPost, 'hook' | 'alternativeHooks' | 'body' | 'cta' | 'hashtags'>>;

export interface GenerateParams {
  pillarIndex: number;
  instructions?: string;
  audiencePersona?: string | null;
  editorialTone?: string | null;
}

export interface GenerateImageParams {
  prompt?: string | null;
  aspectRatio?: string;
  style?: string;
  altText?: string | null;
  provider?: string | null;
}

export interface UpdateImageParams {
  prompt?: string | null;
  altText?: string | null;
  style?: string;
  aspectRatio?: string;
}

const url = (projectId: string) => `/projects/${projectId}/generated-content`;

// Only choices (pillar, instructions, persona, tone) and the user's own edits are sent; the backend loads all context itself.
export const GenerationService = {
  get: (projectId: string): Promise<GenerationState> => apiClient.get(url(projectId)),
  generate: (
    projectId: string,
    pillarIndexOrParams: number | GenerateParams,
    instructions?: string,
    audiencePersona?: string | null,
    editorialTone?: string | null
  ): Promise<GenerationState> => {
    if (typeof pillarIndexOrParams === 'object') {
      const { pillarIndex, instructions: inst, audiencePersona: ap, editorialTone: et } = pillarIndexOrParams;
      return apiClient.post(url(projectId), {
        pillarIndex,
        instructions: (inst || '').trim() || null,
        audiencePersona: ap || null,
        editorialTone: et || null,
      });
    }
    return apiClient.post(url(projectId), {
      pillarIndex: pillarIndexOrParams,
      instructions: (instructions || '').trim() || null,
      audiencePersona: audiencePersona || null,
      editorialTone: editorialTone || null,
    });
  },
  savePreferences: (
    projectId: string,
    preferences: { audiencePersona?: string | null; editorialTone?: string | null }
  ): Promise<GenerationState> =>
    apiClient.put(`${url(projectId)}/preferences`, preferences),
  update: (projectId: string, edits: PostEdits, version: number): Promise<GenerationState> =>
    apiClient.patch(url(projectId), { ...edits, version }),
  // Human approval of the saved version. Records the decision only: nothing is published or scheduled.
  approve: (projectId: string, version: number): Promise<GenerationState> =>
    apiClient.post(`${url(projectId)}/approve`, { version }),
  // Image generation and creative preview
  generateImage: (projectId: string, params?: GenerateImageParams): Promise<GenerationState> =>
    apiClient.post(`${url(projectId)}/image`, params || {}),
  updateImage: (projectId: string, params: UpdateImageParams): Promise<GenerationState> =>
    apiClient.patch(`${url(projectId)}/image`, params),
  deleteImage: async (projectId: string): Promise<GenerationState> => {
    await apiClient.delete(`${url(projectId)}/image`);
    return GenerationService.get(projectId);
  },
};
