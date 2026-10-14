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
import {
  buildSteps,
  plainMessage,
  summarize,
  type StepStatus,
  type SummaryTone,
} from '@/lib/orchestration-view';
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

const focusRing = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background';

const STEP_STYLES: Record<StepStatus, string> = {
  completed: 'bg-emerald-500/5 hover:bg-emerald-500/10',
  paused: 'bg-amber-500/10 hover:bg-amber-500/15 border border-amber-500/20',
  halted: 'bg-amber-500/10 hover:bg-amber-500/15 border border-amber-500/30',
  active: 'bg-primary/10 hover:bg-primary/15 border border-primary/20',
  pending: 'bg-muted/30 hover:bg-muted/50',
};

const CARD_STYLES: Record<SummaryTone, string> = {
  loading: 'bg-muted/40 border-border/50',
  neutral: 'bg-primary/5 border-primary/20',
  attention: 'bg-amber-500/10 border-amber-500/25',
  success: 'bg-emerald-500/10 border-emerald-500/20',
  error: 'bg-destructive/10 border-destructive/20',
};

const BADGE_STYLES: Record<SummaryTone, string> = {
  loading: 'bg-muted text-muted-foreground border-border/50',
  neutral: 'bg-primary/10 text-primary border-primary/20',
  attention: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20',
  success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
  error: 'bg-destructive/10 text-destructive border-destructive/20',
};

function ToneIcon({ tone, className }: { tone: SummaryTone; className?: string }) {
  if (tone === 'loading') return <Loader2 aria-hidden="true" className={cn('animate-spin', className)} />;
  if (tone === 'success') return <CheckCircle2 aria-hidden="true" className={cn('text-emerald-500', className)} />;
  if (tone === 'attention') return <ShieldCheck aria-hidden="true" className={cn('text-amber-500', className)} />;
  if (tone === 'error') return <AlertCircle aria-hidden="true" className={cn('text-destructive', className)} />;
  return <PlayCircle aria-hidden="true" className={cn('text-primary', className)} />;
}

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
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Moves the project forward as far as it can go without a human decision (the backend still stops at every
  // approval and never approves or publishes anything itself).
  const handleContinue = async () => {
    if (isRunning) return;
    setIsRunning(true);
    setRunError(null);
    try {
      toast.info('Moving your project forward…');
      const res = await WorkflowOrchestrationService.orchestrate(project.id);
      onStateUpdate(res);
      await onProjectRefresh();

      if (res.status === 'paused_at_approval_boundary') {
        toast.success(`Your post is ready for your review (v${res.contentVersion}).`);
        onSelectStage?.('review-approval');
      } else if (res.status === 'completed') {
        toast.success('All done. Your post is approved.');
      } else if (res.status === 'halted') {
        toast.warning(plainMessage(res.haltReason) || 'This step needs your input before we can continue.');
        if (res.currentStage) onSelectStage?.(res.currentStage);
      } else if (res.status === 'error') {
        const message = plainMessage(res.haltReason || res.errors?.join('; ')) || 'The workflow stopped unexpectedly.';
        setRunError(message);
        toast.error(message);
      }
    } catch (e) {
      const message = plainMessage(e instanceof Error ? e.message : String(e));
      setRunError(message);
      toast.error(`Could not continue: ${message}`);
    } finally {
      setIsRunning(false);
    }
  };

  const steps = buildSteps(project.stages, state);
  const summary = summarize(steps, state, { isLoading, error: runError || error });
  const busy = isRunning || isLoading;
  const percent = summary.total ? Math.round((summary.doneCount / summary.total) * 100) : 0;

  const runPrimary = () => {
    if (summary.tone === 'error' && error && onRetry) {
      setRunError(null);
      onRetry();
    } else {
      void handleContinue();
    }
  };

  return (
    <section
      aria-labelledby="project-progress-heading"
      className="glass-panel p-4 sm:p-5 rounded-2xl border border-primary/20 bg-primary/[0.02] shadow-sm mb-6 space-y-4"
    >
      {/* Title, status and how far along the project is */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
            <Sparkles className="w-4 h-4" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id="project-progress-heading" className="text-sm font-semibold text-foreground">Your Project Progress</h3>
              <span className={cn('inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border', BADGE_STYLES[summary.tone])}>
                <ToneIcon tone={summary.tone} className="w-3.5 h-3.5" />
                <span>{summary.badge}</span>
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {summary.doneCount} of {summary.total} steps done. We pause for your review before anything is approved.
            </p>
          </div>
        </div>
      </div>

      <div
        role="progressbar"
        aria-label="Project progress"
        aria-valuemin={0}
        aria-valuemax={summary.total}
        aria-valuenow={summary.doneCount}
        aria-valuetext={`${summary.doneCount} of ${summary.total} steps done`}
        className="h-1.5 w-full rounded-full bg-muted/60 overflow-hidden"
      >
        <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${percent}%` }} />
      </div>

      {/* The steps, in order */}
      <ol className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-border/40" aria-label="Project steps">
        {steps.map((step) => (
          <li key={step.key} className="contents">
            <button
              type="button"
              onClick={() => onSelectStage?.(step.key)}
              disabled={!onSelectStage}
              aria-current={step.status === 'active' || step.status === 'paused' || step.status === 'halted' ? 'step' : undefined}
              className={cn('flex flex-col items-start p-2.5 rounded-xl transition-all text-left min-h-[4.25rem]', focusRing, STEP_STYLES[step.status])}
            >
              <span className="flex items-center gap-1.5 mb-1 w-full justify-between">
                <span className="text-[11px] font-medium text-muted-foreground">Step {step.number}</span>
                {step.status === 'completed' ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" aria-hidden="true" />
                ) : step.status === 'paused' ? (
                  <Clock className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
                ) : step.status === 'halted' ? (
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
                ) : step.status === 'active' ? (
                  <span className="w-2 h-2 rounded-full bg-primary" aria-hidden="true" />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" aria-hidden="true" />
                )}
              </span>
              <span className="text-xs font-medium text-foreground w-full">{step.label}</span>
              <span className="text-[11px] text-muted-foreground">{step.statusText}</span>
            </button>
          </li>
        ))}
      </ol>

      {/* What is happening and the one thing to do next */}
      <div role="status" aria-live="polite" className={cn('p-3.5 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3', CARD_STYLES[summary.tone])}>
        <div className="flex items-start gap-2.5 min-w-0">
          <ToneIcon tone={summary.tone} className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="space-y-0.5 min-w-0">
            <div className="text-sm font-semibold text-foreground">{summary.title}</div>
            <p className="text-xs text-muted-foreground">{summary.description}</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto shrink-0">
          {summary.primary && (
            <button
              type="button"
              disabled={busy || (summary.primary.kind === 'goto' && !onSelectStage)}
              onClick={() => {
                if (summary.primary?.kind === 'goto') onSelectStage?.(summary.primary.stage || 'review-approval');
                else runPrimary();
              }}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold transition-all shadow-sm active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed',
                focusRing,
                summary.tone === 'success' ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                  : summary.tone === 'error' ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90',
              )}
            >
              {isRunning && summary.primary.kind === 'run' ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                  <span>Working on it…</span>
                </>
              ) : (
                <>
                  {summary.primary.kind === 'run' && summary.tone === 'error' ? <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" /> : null}
                  <span>{summary.primary.label}</span>
                  {summary.primary.kind === 'goto' ? <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" /> : null}
                </>
              )}
            </button>
          )}
          {summary.secondary && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleContinue()}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold border border-border bg-background text-foreground hover:bg-muted/60 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed',
                focusRing,
              )}
            >
              {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />}
              <span>{isRunning ? 'Working on it…' : summary.secondary.label}</span>
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
