import { apiClient } from '@/lib/api-client';

/** Which AI mode generation actions use — from backend configuration only (no secrets, no connection test). */
export interface AiMode {
  mode: 'demo' | 'real';
  provider: string;
  model?: string | null;
  configured: boolean;
  configurationProblem?: string | null;
  mayIncurCharges: boolean;
  /** Always false: MCF reports configuration, it does not test the connection. */
  connectionVerified: boolean;
  costEstimatesAvailable: boolean;
  /** One provider request per AI step: no application or SDK retries (controlled tests). */
  singleAttempt?: boolean;
}

export const AiModeService = {
  get: (): Promise<AiMode> => apiClient.get('/ai/mode'),
};
