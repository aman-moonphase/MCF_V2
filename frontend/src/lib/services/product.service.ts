import { apiClient } from '@/lib/api-client';

// Keys arrive camelCased by apiClient. Field NAMES inside values (missingFields, question.fields)
// stay snake_case, as the backend defines them.
export interface ProductProfile {
  name?: string | null;
  description?: string | null;
  category?: string | null;
  problemSolved?: string | null;
  targetAudience?: string | null;
  primaryUsers: string[];
  keyFeatures: string[];
  keyBenefits: string[];
  differentiators: string[];
  useCases: string[];
  valueProposition?: string | null;
  positioning?: string | null;
  marketGeography?: string | null;
  businessModel?: string | null;
  knownCompetitors: string[];
  websiteUrl?: string | null;
  constraints: string[];
  sourceReferences: { sourceId: string; name: string; sourceType: string }[];
  missingFields: string[];
  confidence: 'low' | 'medium' | 'high';
}

export interface ClarificationQuestion {
  id: string;
  question: string;
  whyItMatters: string;
  fields: string[];
  status: 'open' | 'answered' | 'resolved';
  answer?: string | null;
}

export type UnderstandingStatus = 'not_started' | 'needs_clarification' | 'ready_for_review' | 'approved';

export interface Product {
  id: string;
  name: string;
  understandingStatus: UnderstandingStatus;
  profile: ProductProfile | null;
  clarificationQuestions: ClarificationQuestion[];
  editedFields: string[];
  profileVersion: number;
  approvedVersion?: number | null;
  approvedAt?: string | null;
  projectIds: string[];
}

export const ProductService = {
  getForProject: (projectId: string): Promise<Product | null> => apiClient.get(`/projects/${projectId}/product`),

  runUnderstanding: (projectId: string): Promise<Product> =>
    apiClient.post(`/projects/${projectId}/product-understanding`, {}),

  submitAnswers: (productId: string, projectId: string, answers: { questionId: string; answer: string }[]): Promise<Product> =>
    apiClient.post(`/products/${productId}/clarifications`, { projectId, answers }),

  updateProfile: (productId: string, profile: Partial<ProductProfile>): Promise<Product> =>
    apiClient.patch(`/products/${productId}/profile`, { profile }),

  approve: (productId: string, projectId: string, profileVersion: number): Promise<Product> =>
    apiClient.post(`/products/${productId}/approve`, { projectId, profileVersion }),
};
