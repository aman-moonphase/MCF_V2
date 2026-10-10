"use client"

import React from 'react';
import { Project, WorkflowStage } from '@/types/project';
import { ProductUnderstandingStage } from './stages/product-understanding-stage';
import { CompetitorAnalysisStage } from './stages/competitor-analysis-stage';
import { PromotionStrategyStage } from './stages/promotion-strategy-stage';
import { ContentTypeStage } from './stages/content-type-stage';
import { GenerateContentStage } from './stages/generate-content-stage';
import { ReviewApprovalStage } from './stages/review-approval-stage';
import { EvaluateImproveStage } from './stages/evaluate-improve-stage';
import { ContentSelectionStage } from './stages/content-selection-stage';
import { PlatformStrategyStage } from './stages/platform-strategy-stage';
import { TopicAngleStage } from './stages/topic-angle-stage';
import { ContentStrategyStage } from './stages/content-strategy-stage';
import { StoryboardStage } from './stages/storyboard-stage';
import { ScriptStage } from './stages/script-stage';

export interface StageComponentProps {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
  /** Switch the workspace to another stage (e.g. back to Generate Content). */
  onSelectStage?: (stageId: string) => void;
}

// Stage type → the interactive component that renders it. A stage with a component here owns its
// own approve/continue controls; any other stage gets the generic "Approve & Continue" button.
// To add a stage: define it in backend/app/core/workflow.py, then register its component here.
export const STAGE_COMPONENTS: Record<string, React.ComponentType<StageComponentProps>> = {
  'product-understanding': ProductUnderstandingStage,
  'competitor-analysis': CompetitorAnalysisStage,
  'promotion-strategy': PromotionStrategyStage,
  'content-type': ContentTypeStage,
  'generate-content': GenerateContentStage,
  'content-selection': ContentSelectionStage,
  'platform-strategy': PlatformStrategyStage,
  'topic-angle': TopicAngleStage,
  'content-strategy': ContentStrategyStage,
  'storyboard': StoryboardStage,
  'final-script': ScriptStage,
};

// Product-workflow-only screens; legacy projects render these stages with the generic workspace instead.
const PRODUCT_WORKFLOW_COMPONENTS: Record<string, React.ComponentType<StageComponentProps>> = {
  'evaluate-improve': EvaluateImproveStage,
  'review-approval': ReviewApprovalStage,
};

export function isProductWorkflow(project: Pick<Project, 'stages'>): boolean {
  return project.stages?.some((s) => s.type === 'product-understanding') ?? false;
}

export function stageComponentFor(project: Project, type: string): React.ComponentType<StageComponentProps> | undefined {
  return STAGE_COMPONENTS[type] ?? (isProductWorkflow(project) ? PRODUCT_WORKFLOW_COMPONENTS[type] : undefined);
}

export function hasDedicatedStageUI(type: string, project?: Project): boolean {
  return project ? stageComponentFor(project, type) !== undefined : type in STAGE_COMPONENTS;
}
