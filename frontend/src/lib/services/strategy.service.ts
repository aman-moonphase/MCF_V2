import { apiClient } from '@/lib/api-client';

export type Basis = 'competitor_observed' | 'evidence_inferred' | 'product_profile' | 'hypothesis';

export interface Grounding {
  basis: Basis;
  refs: string[];
  confidence: 'low' | 'medium' | 'high';
}

export interface PromotionStrategy {
  executiveSummary: { positioning: string; mainOpportunity: string; primaryRecommendation: string; grounding: Grounding };
  audience: {
    primaryAudience: string; problemsAndNeeds: string[]; valueProposition: string; differentiators: string[];
    messagingDirection: string; grounding: Grounding;
  };
  contentPillars: { name: string; purpose: string; relationToProduct: string; grounding: Grounding }[];
  channels: { channel: string; priority: 'primary' | 'secondary'; rationale: string; formats: string[]; grounding: Grounding }[];
  contentDirection: {
    primaryContentType: string; reason: string; alternatives: string[]; subjectAreas: string[]; messagingAngles: string[]; grounding: Grounding;
  };
  cadence: { frequency: string; rationale: string; planningHorizon: string; isHypothesis: boolean; grounding: Grounding };
  roadmap: {
    sequence: number; timing: string; objective: string; topic: string; channel: string; format: string;
    audience: string; successEvaluation: string; grounding: Grounding;
  }[];
  measurement: { indicator: string; whatToMeasure: string; why: string; grounding: Grounding }[];
  limitations: string[];
}

export interface StrategyState {
  productId: string;
  productName: string;
  prerequisitesMet: boolean;
  prerequisiteProblem?: string | null;
  limitedEvidence: boolean;
  status: 'not_generated' | 'draft' | 'approved';
  strategy?: PromotionStrategy | null;
  version?: number | null;
  approvedVersion?: number | null;
  approvedAt?: string | null;
  stale: boolean;
  editedSections: string[];
  basis?: { competitors?: string[]; limitedEvidence?: boolean } | null;
  provider?: string | null;
}

const url = (productId: string) => `/products/${productId}/promotion-strategy`;

export const StrategyService = {
  get: (productId: string): Promise<StrategyState> => apiClient.get(url(productId)),
  generate: (productId: string): Promise<StrategyState> => apiClient.post(url(productId), {}),
  update: (productId: string, sections: Partial<PromotionStrategy>): Promise<StrategyState> =>
    apiClient.patch(url(productId), { strategy: sections }),
  approve: (productId: string, projectId: string, version: number): Promise<StrategyState> =>
    apiClient.post(`${url(productId)}/approve`, { projectId, version }),
};
