// Plain-language view of a project's workflow progress, for the "Your Project Progress" panel.
// Pure functions only (no React, no network), so the wording and the status rules can be checked by
// scripts/check-orchestration-panel.mjs. The stage list always comes from the project's own stage rows, which the
// backend defines (backend/app/core/workflow.py); nothing here invents a stage.

import type { ProductWorkflowState } from '@/lib/services/workflow-orchestration.service';
import type { WorkflowStage } from '@/types/project';

/** The product workflow's stages in order (mirrors PRODUCT_WORKFLOW_KEYS on the backend). */
export const PRODUCT_STAGE_KEYS = [
  'source-grounding',
  'product-understanding',
  'competitor-analysis',
  'promotion-strategy',
  'content-type',
  'generate-content',
  'evaluate-improve',
  'review-approval',
] as const;

/** Short, beginner-friendly names. Anything unknown falls back to the name the backend sent. */
const FRIENDLY_LABELS: Record<string, string> = {
  'source-grounding': 'Your Sources',
  'product-understanding': 'Product Profile',
  'competitor-analysis': 'Competitors',
  'promotion-strategy': 'Promotion Strategy',
  'content-type': 'Content Type',
  'generate-content': 'Write the Post',
  'evaluate-improve': 'Quality Check',
  'review-approval': 'Final Review',
};

export type StepStatus = 'completed' | 'active' | 'paused' | 'halted' | 'pending';

export const STEP_STATUS_TEXT: Record<StepStatus, string> = {
  completed: 'Done',
  active: 'Up next',
  paused: 'Waiting for your review',
  halted: 'Needs your input',
  pending: 'Not started',
};

export interface ProgressStep {
  key: string;
  label: string;
  number: number;
  status: StepStatus;
  statusText: string;
}

export function friendlyStageLabel(key: string | null | undefined, apiLabel?: string): string {
  if (!key) return 'the next step';
  return FRIENDLY_LABELS[key] || apiLabel || key.split('-').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/** Backend messages are already plain English, but a few mention internals; keep the meaning, drop the jargon. */
export function plainMessage(text: string | null | undefined): string {
  if (!text) return '';
  return text
    .replace(/workflow orchestration/gi, 'the workflow')
    .replace(/\borchestration\b/gi, 'workflow')
    .replace(/\bLangGraph\b/gi, 'workflow')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Status of one stage, derived only from what the backend reported. */
export function stepStatus(key: string, state: ProductWorkflowState | null, stageRowStatus?: string): StepStatus {
  if (!state) return stageRowStatus === 'Completed' ? 'completed' : 'pending';
  if (state.status === 'completed' || state.reviewApproved) return 'completed';
  const current = state.currentStage === key;
  const halted = state.status === 'halted';

  switch (key) {
    case 'source-grounding':
      // Sources existing is not the same as the step being finished: follow the saved stage state (the sidebar's view),
      // so the panel and the sidebar never disagree. Until the step is completed, it is simply the next thing to do.
      if (!state.sourcesGrounded) return 'pending';
      return stageRowStatus === undefined || stageRowStatus === 'Completed' ? 'completed' : 'active';
    case 'product-understanding':
      if (state.profileApproved) return 'completed';
      return current ? (halted ? 'halted' : 'active') : 'pending';
    case 'competitor-analysis':
      if (state.competitorsApproved) return 'completed';
      return current ? (halted ? 'halted' : 'active') : 'pending';
    case 'promotion-strategy':
      if (state.strategyApproved) return 'completed';
      return current ? (halted ? 'halted' : 'active') : 'pending';
    case 'content-type':
      // The person approves the content type (and re-approves it when the strategy changes); the backend records it on the stage.
      if (stageRowStatus === 'Completed') return 'completed';
      return current ? (halted ? 'halted' : 'active') : 'pending';
    case 'generate-content':
      if (state.contentVersion && state.contentVersion > 0) return 'completed';
      return current ? 'active' : 'pending';
    case 'evaluate-improve':
      if (state.evaluationCurrent) return 'completed';
      return current ? 'active' : 'pending';
    case 'review-approval':
      if (state.status === 'paused_at_approval_boundary') return 'paused';
      return current ? 'active' : 'pending';
    default:
      return 'pending';
  }
}

/** The steps shown to the user: the project's own product-workflow stages, in workflow order. */
export function buildSteps(stages: Pick<WorkflowStage, 'type' | 'label' | 'status'>[] | undefined, state: ProductWorkflowState | null): ProgressStep[] {
  const rows = new Map((stages || []).map((s) => [s.type as string, s]));
  const keys = rows.size ? PRODUCT_STAGE_KEYS.filter((k) => rows.has(k)) : [...PRODUCT_STAGE_KEYS];
  return keys.map((key, i) => {
    const status = stepStatus(key, state, rows.get(key)?.status);
    return { key, label: friendlyStageLabel(key, rows.get(key)?.label), number: i + 1, status, statusText: STEP_STATUS_TEXT[status] };
  });
}

export type SummaryTone = 'loading' | 'neutral' | 'attention' | 'success' | 'error';

export interface ProgressSummary {
  tone: SummaryTone;
  title: string;
  description: string;
  /** Short status pill text. */
  badge: string;
  /** Main call to action: run the next workflow step, or open a specific stage page. */
  primary: { kind: 'run' | 'goto'; label: string; stage?: string } | null;
  /** Optional second action (always a "run"): continue after finishing a step. */
  secondary: { label: string } | null;
  doneCount: number;
  total: number;
}

export function summarize(
  steps: ProgressStep[],
  state: ProductWorkflowState | null,
  opts: { isLoading?: boolean; error?: string | null } = {},
): ProgressSummary {
  const doneCount = steps.filter((s) => s.status === 'completed').length;
  const total = steps.length;
  const base = { doneCount, total, secondary: null as ProgressSummary['secondary'] };
  const failure = opts.error || (state?.status === 'error' ? state.haltReason || state.errors?.join('; ') || 'The workflow stopped unexpectedly.' : null);

  if (opts.isLoading) {
    return { ...base, tone: 'loading', badge: 'Checking…', title: 'Checking your project…', description: 'Looking up what is done so far.', primary: null };
  }
  if (failure) {
    return {
      ...base, tone: 'error', badge: 'Something went wrong', title: 'Something went wrong',
      description: plainMessage(failure) + ' Your saved work is safe. Try again, or open the step that is stuck.',
      primary: { kind: 'run', label: 'Try Again' },
    };
  }
  if (!state) {
    return {
      ...base, tone: 'neutral', badge: 'Not started', title: 'Ready to start',
      description: 'Start the workflow and we will take your project step by step. We pause whenever we need your review.',
      primary: { kind: 'run', label: 'Start Workflow' },
    };
  }
  if (state.status === 'completed' || state.reviewApproved) {
    const version = state.approvedVersion || state.contentVersion;
    return {
      ...base, tone: 'success', badge: 'All done', title: `All done: your post${version ? ` (v${version})` : ''} is approved`,
      description: 'You reviewed and approved this post. Nothing is published or scheduled automatically.',
      primary: { kind: 'goto', label: 'View Approved Post', stage: 'review-approval' },
    };
  }
  if (state.status === 'paused_at_approval_boundary') {
    return {
      ...base, tone: 'attention', badge: 'Waiting for your review', title: 'Waiting for Your Review',
      description: `Your post${state.contentVersion ? ` (v${state.contentVersion})` : ''} passed its quality check. Read it, edit it if you like, then approve it. Nothing is approved or published without you.`,
      primary: { kind: 'goto', label: 'Review & Approve Post', stage: 'review-approval' },
      secondary: { label: 'Re-check Progress' },
    };
  }
  if (state.status === 'halted') {
    const where = friendlyStageLabel(state.currentStage);
    return {
      ...base, tone: 'attention', badge: 'Needs your input', title: 'Your input is needed',
      description: plainMessage(state.haltReason) || `Finish "${where}" to continue.`,
      primary: { kind: 'goto', label: `Go to ${where}`, stage: state.currentStage },
      secondary: { label: 'Continue Workflow' },
    };
  }
  return {
    ...base, tone: 'neutral', badge: 'Ready to continue', title: 'Ready to continue',
    description: `Next up: ${friendlyStageLabel(state.currentStage)}. We will pause when we need your review.`,
    primary: { kind: 'run', label: 'Continue Workflow' },
  };
}
