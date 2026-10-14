"use client"

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { EvaluationFinding, EvaluationService, EvaluationState } from '@/lib/services/evaluation.service';
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, CircleHelp, ClipboardCheck, Lightbulb, Loader2, Lock, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
  onSelectStage?: (stageId: string) => void;
  onRefreshOrchestration?: () => Promise<void> | void;
}

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pill = 'inline-flex items-center gap-2 h-10 px-5 rounded-full text-sm font-medium whitespace-nowrap transition-all disabled:opacity-50 disabled:cursor-not-allowed';

const OVERALL_STYLE: Record<string, string> = {
  ready: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  ready_with_recommendations: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  needs_improvement: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  not_ready: 'bg-destructive/10 text-destructive border-destructive/20',
};
const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  pass: { label: 'No problems found', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
  attention: { label: 'Recommendations', className: 'bg-sky-500/10 text-sky-500 border-sky-500/20' },
  problem: { label: 'Problems', className: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
};
const TYPE_STYLE: Record<EvaluationFinding['type'], { label: string; icon: React.ReactNode; className: string }> = {
  problem: { label: 'Problem', icon: <XCircle className="w-4 h-4" />, className: 'text-amber-500' },
  recommendation: { label: 'Recommendation', icon: <Lightbulb className="w-4 h-4" />, className: 'text-sky-500' },
  unknown: { label: 'Unknown', icon: <CircleHelp className="w-4 h-4" />, className: 'text-muted-foreground' },
};

function Finding({ f }: { f: EvaluationFinding }) {
  const t = TYPE_STYLE[f.type];
  return (
    <li className="rounded-2xl border border-border/50 p-3 space-y-1.5">
      <div className="flex items-start gap-2">
        <span className={cn('mt-0.5 shrink-0', t.className)}>{t.icon}</span>
        <div className="min-w-0 space-y-1">
          <p className="text-sm">
            <span className={cn('mr-2 text-[10px] uppercase tracking-wider font-semibold', t.className)}>{t.label} · {f.severity}</span>
            {f.message}
          </p>
          {f.excerpt && <p className="text-xs text-muted-foreground italic">&ldquo;{f.excerpt}&rdquo;</p>}
          {f.suggestion && <p className="text-xs text-foreground/80">Suggestion: {f.suggestion}</p>}
          {f.evidence.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {f.evidence.map((e) => (
                <span key={e.ref} title={e.description} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50">
                  {e.ref} — {e.description}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

/** Evaluate & Improve (product workflow): rule-based evaluation of the SAVED post version. It never edits the post;
 *  improvements are made in Generate Content, then the new saved version is evaluated again. */
export function EvaluateImproveStage({ project, activeStage, onComplete, onSelectStage, onRefreshOrchestration }: Props) {
  const [state, setState] = useState<EvaluationState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState<'evaluate' | 'continue' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const s = await EvaluationService.get(project.id);
        if (!cancelled) setState(s);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id, activeStage?.id]);

  const generateStage = project.stages.find((s) => s.type === 'generate-content');
  const backToGenerate = generateStage && onSelectStage ? (
    <button onClick={() => onSelectStage(generateStage.id)} disabled={!!busy} className={cn(pill, 'bg-muted text-foreground')}>
      <ArrowLeft className="w-4 h-4" />Back to Generate Content to edit
    </button>
  ) : null;

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-[40vh]"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }
  if (!state || state.status === 'no_draft' || state.status === 'not_applicable') {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2"><Lock className="w-8 h-8 text-muted-foreground/50" /></div>
        <h3 className="text-xl font-semibold">Nothing to evaluate yet</h3>
        <p className="text-muted-foreground max-w-md">{error || state?.reason}</p>
        {backToGenerate}
      </div>
    );
  }

  const draft = state.draft!;
  const evaluation = state.evaluation;
  const result = evaluation?.result;
  const current = state.status === 'current';

  const evaluate = async () => {
    setBusy('evaluate');
    setError(null);
    try {
      setState(await EvaluationService.evaluate(project.id, draft.version));
      toast.success(`Version ${draft.version} evaluated. The post was not changed.`);
      if (onRefreshOrchestration) {
        await onRefreshOrchestration();
      }
    } catch (e) {
      setError(errorMessage(e));
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const proceed = async () => {
    setBusy('continue');
    try {
      await onComplete();
      if (onRefreshOrchestration) {
        await onRefreshOrchestration();
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 sticky top-0 -mt-4 sm:mt-0 pt-4 pb-4 -mx-4 sm:mx-0 px-4 sm:px-0 bg-background/95 sm:bg-background/80 backdrop-blur-md z-20 border-b border-border/50">
        <div className="min-w-0 flex-[1_1_18rem]">
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">Evaluate · saved version {draft.version}</h3>
            <span className={cn('px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap',
              current ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                : state.status === 'stale' ? 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                  : 'bg-muted text-muted-foreground border-border/50')}>
              {current ? 'Evaluation current' : state.status === 'stale' ? 'Evaluation out of date' : 'Not evaluated'}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            {draft.edited ? 'Edited by hand' : 'As generated'} · {draft.isDemo ? 'Demo output' : `generated by ${draft.provider}`} · post status: {draft.status}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
          {backToGenerate}
          <button onClick={evaluate} disabled={!!busy} className={cn(pill, current ? 'bg-muted text-foreground' : 'bg-foreground text-background font-semibold')}>
            {busy === 'evaluate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardCheck className="w-4 h-4" />}
            {evaluation ? `Re-evaluate version ${draft.version}` : `Evaluate version ${draft.version}`}
          </button>
          {activeStage.status !== 'Completed' && (
            <button onClick={proceed} disabled={!!busy || !current} title={current ? '' : 'Evaluate the current saved version first'}
              className={cn(pill, 'bg-primary text-primary-foreground shadow-md')}>
              {busy === 'continue' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}Continue to Review
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /><p>{error}</p>
        </div>
      )}
      {state.status !== 'current' && state.reason && (
        <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <p>{state.reason} Review Approval stays blocked until the current saved version is evaluated.</p>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {result?.about ?? 'Rule-based, deterministic evaluation (Demo Mode). Not an AI judgment; no scores or engagement predictions.'}
        {' '}Evaluation never changes the post — improve it in Generate Content, save, then evaluate again.
      </p>

      {result && (
        <>
          <div className={cn('glass-panel p-6 rounded-3xl space-y-2 border', OVERALL_STYLE[result.overall.level])}>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5" />
              <h4 className="text-lg font-semibold">{result.overall.label}</h4>
              {!current && <span className="text-xs text-muted-foreground">(version {evaluation!.contentVersion} — out of date)</span>}
            </div>
            <p className="text-sm text-muted-foreground">{result.overall.explanation}</p>
          </div>

          {result.dimensions.map((d) => (
            <div key={d.key} className="glass-panel p-6 rounded-3xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">{d.label}</h4>
                <span className={cn('text-[10px] px-2 py-0.5 rounded-full border font-medium', STATUS_STYLE[d.status].className)}>{STATUS_STYLE[d.status].label}</span>
              </div>
              {d.summary && <p className="text-sm text-muted-foreground">{d.summary}</p>}
              {d.findings.length > 0 ? <ul className="space-y-2">{d.findings.map((f, i) => <Finding key={i} f={f} />)}</ul>
                : <p className="text-sm italic text-muted-foreground">No findings.</p>}
            </div>
          ))}
        </>
      )}

      {state.history.length > 0 && (
        <div className="glass-panel p-6 rounded-3xl space-y-2">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Evaluation history</h4>
          <ul className="text-sm text-muted-foreground space-y-1">
            {state.history.map((h) => (
              <li key={h.id}>
                Version {h.contentVersion} · {h.overallLabel} · {h.counts.problems} problem(s), {h.counts.recommendations} recommendation(s) ·{' '}
                {new Date(h.createdAt).toLocaleString()}{h.contentVersion !== draft.version && ' · out of date'}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
