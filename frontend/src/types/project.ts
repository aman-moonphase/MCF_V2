export type ProjectStatus = 'Draft' | 'In Progress' | 'Needs Review' | 'Approved' | 'Completed' | 'Failed';

export type StageStatus = 'Locked' | 'Not Started' | 'In Progress' | 'Completed' | 'Needs Review' | 'Failed';

// Stage keys are defined by the backend workflow config (backend/app/core/workflow.py).
// The known keys are listed for type hints; new stages added on the backend remain valid strings.
export type KnownWorkflowStageType =
  | 'source-grounding'
  | 'product-understanding'
  | 'competitor-analysis'
  | 'promotion-strategy'
  | 'content-type'
  | 'generate-content'
  | 'evaluate-improve'
  | 'content-selection'
  | 'platform-strategy'
  | 'topic-angle'
  | 'content-strategy'
  | 'storyboard'
  | 'final-script'
  | 'review-approval';

export type WorkflowStageType = KnownWorkflowStageType | (string & {});

export interface WorkflowStage {
  id: string;
  projectId: string;
  type: WorkflowStageType;
  /** Display name from the backend workflow definition. */
  label?: string;
  /** Position in the canonical workflow order. */
  order?: number;
  status: StageStatus;
  data?: any;
  createdAt: string;
  updatedAt: string;
}

export interface Project {
  id: string;
  title: string;
  description: string;
  status: ProjectStatus;
  sourceType: string;
  sourceReference: string;
  currentStage: WorkflowStageType;
  /** The Product this project promotes (its profile lives on the product). */
  productId?: string | null;
  createdAt: string;
  updatedAt: string;
  stages: WorkflowStage[];
}

export interface CreateProjectInput {
  title: string;
  description: string;
  sourceType: string;
  sourceReference: string;
}
