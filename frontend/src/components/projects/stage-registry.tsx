"use client"

import React from 'react';
import { Project, WorkflowStage } from '@/types/project';
import { ProductUnderstandingStage } from './stages/product-understanding-stage';
import { CompetitorAnalysisStage } from './stages/competitor-analysis-stage';
import { PromotionStrategyStage } from './stages/promotion-strategy-stage';
import { ContentTypeStage } from './stages/content-type-stage';
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
}

// Stage type → the interactive component that renders it. A stage with a component here owns its
// own approve/continue controls; any other stage gets the generic "Approve & Continue" button.
// To add a stage: define it in backend/app/core/workflow.py, then register its component here.
export const STAGE_COMPONENTS: Record<string, React.ComponentType<StageComponentProps>> = {
  'product-understanding': ProductUnderstandingStage,
  'competitor-analysis': CompetitorAnalysisStage,
  'promotion-strategy': PromotionStrategyStage,
  'content-type': ContentTypeStage,
  'content-selection': ContentSelectionStage,
  'platform-strategy': PlatformStrategyStage,
  'topic-angle': TopicAngleStage,
  'content-strategy': ContentStrategyStage,
  'storyboard': StoryboardStage,
  'final-script': ScriptStage,
};

export function hasDedicatedStageUI(type: string): boolean {
  return type in STAGE_COMPONENTS;
}
