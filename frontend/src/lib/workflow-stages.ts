import { Project, WorkflowStage } from '@/types/project';

// Stage keys, order and labels are defined once, on the backend (backend/app/core/workflow.py),
// and arrive with every stage as `label` / `order`. This file only formats what the API sent.

function humanize(type: string): string {
  return type
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export function getStageLabel(stage: Pick<WorkflowStage, 'type' | 'label'>): string {
  return stage.label || humanize(stage.type);
}

/** Label for a stage referenced only by its type (e.g. `project.currentStage`). */
export function getStageLabelByType(project: Pick<Project, 'stages'>, type: string): string {
  const stage = project.stages?.find((s) => s.type === type);
  return stage ? getStageLabel(stage) : humanize(type);
}
