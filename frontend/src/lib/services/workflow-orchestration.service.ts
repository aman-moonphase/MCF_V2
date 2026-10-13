import { apiClient } from '@/lib/api-client';

export type WorkflowOrchestrationStatus =
  | 'in_progress'
  | 'paused_at_approval_boundary'
  | 'halted'
  | 'completed'
  | 'error';

export interface PostClaim {
  text: string;
  kind: 'product_fact' | 'creative' | 'competitor_context';
  refs: string[];
}

export interface ProductWorkflowState {
  projectId: string;
  productId?: string | null;
  userId?: number;
  currentStage: string;
  status: WorkflowOrchestrationStatus;
  haltReason?: string | null;
  errors?: string[];
  stageHistory?: string[];
  executionLog?: { stage: string; message: string }[];
  sourcesGrounded?: boolean;
  sourceCount?: number;
  sourceEvidence?: Record<string, string>;
  productProfile?: Record<string, unknown> | null;
  profileVersion?: number | null;
  profileApproved?: boolean;
  competitorComparison?: Record<string, unknown> | null;
  competitorVersion?: number | null;
  competitorApprovedVersion?: number | null;
  competitorsApproved?: boolean;
  competitorLimitedEvidence?: boolean;
  promotionStrategy?: Record<string, unknown> | null;
  strategyVersion?: number | null;
  strategyApproved?: boolean;
  contentPillars?: unknown[];
  contentType?: string;
  pillarIndex?: number;
  campaignInstructions?: string | null;
  generatedPost?: Record<string, unknown> | null;
  contentVersion?: number | null;
  claimsTraceability?: PostClaim[];
  generationValidation?: Record<string, unknown> | null;
  evaluation?: Record<string, unknown> | null;
  evaluationVersion?: number | null;
  evaluationCurrent?: boolean;
  reviewApproved?: boolean;
  approvedVersion?: number | null;
  approvedAt?: string | null;
}

export interface OrchestrateOptions {
  pillarIndex?: number;
  campaignInstructions?: string;
}

interface ApiErrorLike {
  status?: number;
  detail?: unknown;
  message?: string;
}

function asApiError(error: unknown): ApiErrorLike | null {
  if (error && typeof error === 'object') {
    return error as ApiErrorLike;
  }
  return null;
}

const url = (projectId: string) => `/projects/${projectId}/orchestration`;
const legacyUrl = (projectId: string) => `/workflow/orchestrate/${projectId}`;

function isNoOrchestrationRunYet(error: unknown): boolean {
  const err = asApiError(error);
  if (!err) return false;
  if (err.status === 204) return true;
  if (err.status === 404) {
    const text = (
      typeof err.detail === 'string'
        ? err.detail
        : typeof err.message === 'string'
        ? err.message
        : ''
    ).toLowerCase();
    return (
      text.includes('no orchestration') ||
      text.includes('not started') ||
      text.includes('no run') ||
      text.includes('no state')
    );
  }
  return false;
}

export const WorkflowOrchestrationService = {
  getStatus: async (projectId: string): Promise<ProductWorkflowState | null> => {
    try {
      return (await apiClient.get(`${url(projectId)}/status`)) as ProductWorkflowState;
    } catch (e: unknown) {
      if (isNoOrchestrationRunYet(e)) {
        return null;
      }
      const err = asApiError(e);
      if (err?.status === 404 && (err?.detail === 'Not Found' || !err?.detail)) {
        try {
          return (await apiClient.get(`${legacyUrl(projectId)}/status`)) as ProductWorkflowState;
        } catch (legacyErr: unknown) {
          if (isNoOrchestrationRunYet(legacyErr)) {
            return null;
          }
          throw legacyErr;
        }
      }
      throw e;
    }
  },

  orchestrate: async (projectId: string, options?: OrchestrateOptions): Promise<ProductWorkflowState> => {
    const body: Record<string, unknown> = {
      pillarIndex: options?.pillarIndex ?? 0,
    };
    if (options?.campaignInstructions !== undefined && options.campaignInstructions !== null) {
      body.campaignInstructions = options.campaignInstructions;
    }
    try {
      return (await apiClient.post(url(projectId), body)) as ProductWorkflowState;
    } catch (e: unknown) {
      const err = asApiError(e);
      if (err?.status === 404 && (err?.detail === 'Not Found' || !err?.detail)) {
        return (await apiClient.post(legacyUrl(projectId), body)) as ProductWorkflowState;
      }
      throw e;
    }
  },

  approve: async (projectId: string, version: number): Promise<ProductWorkflowState> => {
    try {
      return (await apiClient.post(`${url(projectId)}/approve`, { version })) as ProductWorkflowState;
    } catch (e: unknown) {
      const err = asApiError(e);
      if (err?.status === 404 && (err?.detail === 'Not Found' || !err?.detail)) {
        return (await apiClient.post(`${legacyUrl(projectId)}/approve`, { version })) as ProductWorkflowState;
      }
      throw e;
    }
  },
};
