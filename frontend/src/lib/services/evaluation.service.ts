import { apiClient } from '@/lib/api-client';

export type FindingType = 'problem' | 'recommendation' | 'unknown';
export type Severity = 'high' | 'medium' | 'low';

export interface EvaluationFinding {
  type: FindingType;
  severity: Severity;
  message: string;
  suggestion: string;
  evidence: { ref: string; description: string }[];
  excerpt: string;
}

export interface EvaluationDimension {
  key: string;
  label: string;
  status: 'pass' | 'attention' | 'problem';
  summary: string;
  findings: EvaluationFinding[];
}

export interface EvaluationResult {
  overall: { level: 'ready' | 'ready_with_recommendations' | 'needs_improvement' | 'not_ready'; label: string; explanation: string };
  dimensions: EvaluationDimension[];
  counts: { problems: number; highProblems: number; recommendations: number; unknowns: number };
  about: string;
}

export interface EvaluationSummary {
  id: string;
  contentVersion: number;
  overall: string;
  overallLabel: string;
  counts: EvaluationResult['counts'];
  evaluator: string;
  mode: string;
  createdAt: string;
}

export interface EvaluationState {
  projectId: string;
  status: 'not_applicable' | 'no_draft' | 'not_evaluated' | 'current' | 'stale';
  reason?: string | null;
  canProceed: boolean;
  evaluator: { name: string; mode: string };
  draft?: { id: string; version: number; status: string; edited: boolean; isDemo: boolean; provider?: string | null };
  evaluation?: (EvaluationSummary & { result: EvaluationResult }) | null;
  history: EvaluationSummary[];
}

const url = (projectId: string) => `/projects/${projectId}/evaluation`;

// Evaluation is rule-based on the backend (no AI call) and never changes the post.
export const EvaluationService = {
  get: (projectId: string): Promise<EvaluationState> => apiClient.get(url(projectId)),
  evaluate: (projectId: string, version: number): Promise<EvaluationState> => apiClient.post(url(projectId), { version }),
};
