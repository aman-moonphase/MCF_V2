"use client"

import React, { useState } from 'react';
import { toast } from 'sonner';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Loader2,
  PlayCircle,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  ProductWorkflowState,
  WorkflowOrchestrationService,
} from '@/lib/services/workflow-orchestration.service';
import { Project } from '@/types/project';

interface OrchestrationPanelProps {
  project: Project;
  state: ProductWorkflowState | null;
  isLoading: boolean;
  error?: string | null;
  onRetry?: () => void;
  onStateUpdate: (newState: ProductWorkflowState) => void;
  onProjectRefresh: () => Promise<void>;
  onSelectStage?: (stageType: string) => void;
}

const PIPELINE_STAGES = [
  { key: 'source-grounding', label: 'Grounding' },
  { key: 'product-understanding', label: 'Understanding' },
  { key: 'competitor-analysis', label: 'Competitors' },
  { key: 'promotion-strategy', label: 'Strategy' },
  { key: 'generate-content', label: 'Generation' },
  { key: 'evaluate-improve', label: 'Evaluation' },
  { key: 'review-approval', label: 'Review & Approval' },
];

export function OrchestrationPanel({
  project,
  state,
  isLoading,
  error,
  onRetry,
  onStateUpdate,
  onProjectRefresh,
  onSelectStage,
}: OrchestrationPanelProps) {
  const [isOrchestrating, setIsOrchestrating] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const handleRunOrchestration = async () => {
    if (isOrchestrating) return;
    setIsOrchestrating(true);
    setRunError(null);
    try {
      toast.info('Starting LangGraph workflow orchestration...');
      const res = await WorkflowOrchestrationService.orchestrate(project.id);
      onStateUpdate(res);
      await onProjectRefresh();

      if (res.status === 'paused_at_approval_boundary') {
        toast.success(`Workflow reached human review boundary (Post v${res.contentVersion} evaluated).`);
        if (onSelectStage) {
          onSelectStage('review-approval');
        }
      } else if (res.status === 'completed') {
        toast.success('Workflow completed successfully.');
      } else if (res.status === 'halted') {
        toast.warning(res.haltReason || 'Workflow paused awaiting required stage input.');
        if (res.currentStage && onSelectStage) {
          onSelectStage(res.currentStage);
        }
      } else if (res.status === 'error') {
        const errMsg = res.haltReason || res.errors?.join('; ') || 'Workflow halted with an error.';
        setRunError(errMsg);
        toast.error(errMsg);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setRunError(msg);
      toast.error(`Orchestration failed: ${msg}`);
    } finally {
      setIsOrchestrating(false);
    }
  };

  const getStageStatus = (stageKey: string) => {
    if (!state) return 'pending';
    if (state.status === 'completed' || state.reviewApproved) return 'completed';

    switch (stageKey) {
      case 'source-grounding':
        return state.sourcesGrounded ? 'completed' : 'pending';
      case 'product-understanding':
        if (state.profileApproved) return 'completed';
        if (state.currentStage === 'product-understanding') return state.status === 'halted' ? 'halted' : 'active';
        return 'pending';
      case 'competitor-analysis':
        if (state.competitorsApproved) return 'completed';
        if (state.currentStage === 'competitor-analysis') return state.status === 'halted' ? 'halted' : 'active';
        return 'pending';
      case 'promotion-strategy':
        if (state.strategyApproved) return 'completed';
        if (state.currentStage === 'promotion-strategy') return state.status === 'halted' ? 'halted' : 'active';
        return 'pending';
      case 'generate-content':
        if (state.contentVersion && state.contentVersion > 0) return 'completed';
        if (state.currentStage === 'generate-content') return 'active';
        return 'pending';
      case 'evaluate-improve':
        if (state.evaluationCurrent) return 'completed';
        if (state.currentStage === 'evaluate-improve') return 'active';
        return 'pending';
      case 'review-approval':
        if (state.reviewApproved) return 'completed';
        if (state.status === 'paused_at_approval_boundary') return 'paused';
        if (state.currentStage === 'review-approval') return 'active';
        return 'pending';
      default:
        return 'pending';
    }
  };

  const statusBadge = () => {
    if (isLoading) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground border border-border/50">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>Checking workflow...</span>
        </span>
      );
    }

    const activeError = runError || error;

    if (activeError || state?.status === 'error') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-destructive/10 text-destructive border border-destructive/20">
          <AlertCircle className="w-3.5 h-3.5" />
          <span>Orchestration Error</span>
        </span>
      );
    }

    if (!state) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-muted text-muted-foreground border border-border/50">
          <Clock className="w-3.5 h-3.5" />
          <span>Not Started</span>
        </span>
      );
    }

    if (state.status === 'completed' || state.reviewApproved) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>Workflow Completed</span>
        </span>
      );
    }

    if (state.status === 'paused_at_approval_boundary') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/20">
          <Clock className="w-3.5 h-3.5" />
          <span>Paused at Human Review Boundary</span>
        </span>
      );
    }

    if (state.status === 'halted') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/20">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Halted: Prerequisite Required</span>
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20">
        <PlayCircle className="w-3.5 h-3.5 animate-pulse" />
        <span>Ready to Orchestrate</span>
      </span>
    );
  };

  return (
    <div className="glass-panel p-4 sm:p-5 rounded-2xl border border-primary/20 bg-primary/[0.02] shadow-sm mb-6 space-y-4">
      {/* Top row: Title, Status badge, and Orchestrate Trigger */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">LangGraph Orchestration Pipeline</h3>
              {statusBadge()}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Deterministic, grounded AI workflow across all 6 stages. Strictly gates on human review.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <button
            onClick={handleRunOrchestration}
            disabled={isOrchestrating || isLoading || state?.status === 'completed' || !!state?.reviewApproved}
            className={cn(
              "inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold transition-all shadow-sm",
              (state?.status === 'completed' || state?.reviewApproved)
                ? "bg-muted text-muted-foreground cursor-not-allowed"
                : "bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isOrchestrating ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Orchestrating Pipeline...</span>
              </>
            ) : (runError || error || state?.status === 'error') ? (
              <>
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Orchestration</span>
              </>
            ) : (state?.status === 'completed' || state?.reviewApproved) ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                <span>Workflow Completed</span>
              </>
            ) : state?.status === 'halted' ? (
              <>
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Resume Orchestration</span>
              </>
            ) : state?.status === 'paused_at_approval_boundary' ? (
              <>
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Re-run Orchestration</span>
              </>
            ) : (
              <>
                <PlayCircle className="w-3.5 h-3.5" />
                <span>Auto-Orchestrate Pipeline</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Recoverable Service or Execution Error with Retry */}
      {(runError || error) && (
        <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <AlertCircle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-destructive">Orchestration Error</div>
              <p className="text-xs text-muted-foreground">{runError || error}</p>
            </div>
          </div>
          <button
            onClick={() => {
              setRunError(null);
              if (error && onRetry) onRetry();
              else handleRunOrchestration();
            }}
            disabled={isOrchestrating || isLoading}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-destructive text-destructive-foreground hover:bg-destructive/90 active:scale-95 transition-all shrink-0 self-start sm:self-auto disabled:opacity-50"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Stepper Visualization */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 pt-1 border-t border-border/40">
        {PIPELINE_STAGES.map((s, idx) => {
          const st = getStageStatus(s.key);
          const isClickable = !!onSelectStage;

          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onSelectStage && onSelectStage(s.key)}
              disabled={!isClickable}
              className={cn(
                "flex flex-col items-start p-2 rounded-xl transition-all text-left",
                st === 'completed' && "bg-emerald-500/5 hover:bg-emerald-500/10",
                st === 'paused' && "bg-amber-500/10 hover:bg-amber-500/15 border border-amber-500/20",
                st === 'halted' && "bg-amber-500/10 hover:bg-amber-500/15 border border-amber-500/30",
                st === 'active' && "bg-primary/10 hover:bg-primary/15 border border-primary/20",
                st === 'pending' && "bg-muted/30 hover:bg-muted/50"
              )}
            >
              <div className="flex items-center gap-1.5 mb-1 w-full justify-between">
                <span className="text-[10px] font-mono text-muted-foreground/70">0{idx + 1}</span>
                {st === 'completed' ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                ) : st === 'paused' ? (
                  <Clock className="w-3.5 h-3.5 text-amber-500" />
                ) : st === 'halted' ? (
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                ) : st === 'active' ? (
                  <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
                )}
              </div>
              <span className="text-xs font-medium text-foreground truncate w-full">{s.label}</span>
              <span className="text-[10px] text-muted-foreground capitalize">
                {st === 'paused' ? 'Paused' : st === 'halted' ? 'Blocked' : st}
              </span>
            </button>
          );
        })}
      </div>

      {/* Completed Workflow Banner */}
      {(state?.status === 'completed' || state?.reviewApproved) && (
        <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-foreground">
                Workflow Completed · Post v{state.approvedVersion || state.contentVersion} Approved
              </div>
              <p className="text-xs text-muted-foreground">
                Post has been reviewed and approved by human. Content evaluation is current (v{state.evaluationVersion || state.contentVersion}). Automatic publishing and scheduling are strictly disabled.
              </p>
            </div>
          </div>
          {onSelectStage && (
            <button
              onClick={() => onSelectStage('review-approval')}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 active:scale-95 transition-all shrink-0 self-start sm:self-auto"
            >
              <span>View Approved Post</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Human Review Boundary Pause Banner */}
      {state?.status === 'paused_at_approval_boundary' && !state?.reviewApproved && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <ShieldCheck className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-foreground">
                Paused at Human Review Boundary (Post v{state.contentVersion})
              </div>
              <p className="text-xs text-muted-foreground">
                Content is evaluated (v{state.evaluationVersion}) and ready. Automatic social publishing and auto-approval are strictly prohibited. Explicit human review is required.
              </p>
            </div>
          </div>
          {onSelectStage && (
            <button
              onClick={() => onSelectStage('review-approval')}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-foreground text-background hover:scale-[1.02] active:scale-95 transition-all shrink-0 self-start sm:self-auto"
            >
              <span>Review & Approve Post</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Halted Prerequisite Banner */}
      {state?.status === 'halted' && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-foreground">Prerequisite Stage Input Required</div>
              <p className="text-xs text-muted-foreground">{state.haltReason}</p>
            </div>
          </div>
          {state.currentStage && onSelectStage && (
            <button
              onClick={() => onSelectStage(state.currentStage)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700 active:scale-95 transition-all shrink-0 self-start sm:self-auto"
            >
              <span>Go to {state.currentStage}</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Error Banner */}
      {state?.status === 'error' && (
        <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <AlertCircle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-destructive">Orchestration Error</div>
              <p className="text-xs text-muted-foreground">{state.haltReason || state.errors?.join('; ')}</p>
            </div>
          </div>
          <button
            onClick={handleRunOrchestration}
            disabled={isOrchestrating}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-destructive text-destructive-foreground hover:bg-destructive/90 active:scale-95 transition-all shrink-0 self-start sm:self-auto"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Retry</span>
          </button>
        </div>
      )}
    </div>
  );
}
