"use client"

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { GenerationService, GenerationState, PostClaim } from '@/lib/services/generation.service';
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, Lock, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/utils';
import { UsageSummary } from '../usage-summary';
import { EvaluationService, EvaluationState } from '@/lib/services/evaluation.service';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
  onSelectStage?: (stageId: string) => void;
}

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pill = 'inline-flex items-center gap-2 h-10 px-5 rounded-full text-sm font-medium whitespace-nowrap transition-all disabled:opacity-50 disabled:cursor-not-allowed';
const label = 'text-xs font-semibold uppercase tracking-wider text-muted-foreground';

const CLAIM_KIND: Record<PostClaim['kind'], { label: string; className: string }> = {
  product_fact: { label: 'Product fact', className: 'bg-primary/10 text-primary border-primary/20' },
  creative: { label: 'Messaging', className: 'bg-muted text-muted-foreground border-border/50' },
  competitor_context: { label: 'Informed by competitors', className: 'bg-sky-500/10 text-sky-500 border-sky-500/20' },
};

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('glass-panel p-6 rounded-3xl space-y-4', className)}>
      <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">{title}</h4>
      {children}
    </div>
  );
}

// Mirrors app/ai/generation_validation.py::assemble — what the post looks like as one piece of text.
const assemble = (hook: string, body: string, cta: string, hashtags: string[]) =>
  [hook.trim(), body.trim(), cta.trim(), hashtags.join(' ')].filter(Boolean).join('\n\n');

/** Review Approval (product workflow): a human reviews the SAVED post and explicitly approves that version.
 *  Approval only records the decision — nothing is published, scheduled or sent to any platform. */
export function ReviewApprovalStage({ project, activeStage, onComplete, onSelectStage }: Props) {
  const [state, setState] = useState<GenerationState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evaluation, setEvaluation] = useState<EvaluationState | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, ev] = await Promise.all([GenerationService.get(project.id), EvaluationService.get(project.id)]);
        if (!cancelled) {
          setState(s);
          setEvaluation(ev);
        }
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id]);

  const generateStage = project.stages.find((s) => s.type === 'generate-content');
  const backToGenerate = generateStage && onSelectStage ? (
    <button onClick={() => onSelectStage(generateStage.id)} disabled={busy} className={cn(pill, 'bg-muted text-foreground')}>
      <ArrowLeft className="w-4 h-4" />Back to Generate Content
    </button>
  ) : null;

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-[40vh]"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  const draft = state?.draft;
  if (!state || !draft) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2"><Lock className="w-8 h-8 text-muted-foreground/50" /></div>
        <h3 className="text-xl font-semibold">Nothing to review yet</h3>
        <p className="text-muted-foreground max-w-md">{error || 'There is no saved post for this project. Generate and save one in Generate Content first.'}</p>
        {backToGenerate}
      </div>
    );
  }

  const post = draft.content;
  const approved = draft.status === 'approved';
  const policy = state.policy;
  const text = assemble(post.hook, post.body, post.cta, post.hashtags);
  const evidence = new Map((draft.evidence ?? []).map((e) => [e.ref, e.description]));
  const warnings = draft.validation?.warnings ?? [];
  const unsupported = draft.validation?.unsupportedClaims ?? [];
  // Missing or out-of-date evaluation blocks approval (only where Evaluate & Improve applies).
  const evaluationBlock = evaluation && !evaluation.canProceed ? evaluation.reason || 'Evaluate the current saved version first.' : null;
  const evaluateStage = project.stages.find((s) => s.type === 'evaluate-improve');
  const blocked = state.stale || !!state.blockingProblem || !!evaluationBlock;

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await GenerationService.approve(project.id, draft.version);
      setState(next);
      toast.success(`Post approved (version ${draft.version}). Nothing has been published.`);
      if (activeStage.status !== 'Completed') await onComplete();
    } catch (e) {
      setError(errorMessage(e));
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div className="min-w-0 flex-[1_1_18rem]">
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">Review · {policy.platform} {policy.contentType}</h3>
            <span className={cn('px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap',
              approved ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : 'bg-amber-500/10 text-amber-500 border-amber-500/20')}>
              {approved ? `Approved · version ${draft.approvedVersion}` : 'Draft · awaiting approval'}
            </span>
            {draft.isDemo && (
              <span className="px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-amber-500/10 text-amber-500 border-amber-500/20">Demo output</span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Saved version {draft.version} · {draft.edited ? 'edited by hand' : 'as generated'} by {draft.provider}
            {draft.contextSnapshot?.pillar && ` · pillar: ${draft.contextSnapshot.pillar}`}
            {approved && draft.approvedAt && ` · approved ${new Date(draft.approvedAt).toLocaleString()}`}
          </p>
          <UsageSummary draft={draft} />
        </div>
        <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
          {!approved && backToGenerate}
          {!approved && (
            <button onClick={approve} disabled={busy || blocked} className={cn(pill, 'bg-primary text-primary-foreground shadow-md')}
              title={blocked ? 'Resolve the issues shown below first' : `Approve saved version ${draft.version}`}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}Approve Post
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /><p>{error}</p>
        </div>
      )}
      {(state.stale || !!state.blockingProblem) && !approved && (
        <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            {state.blockingProblem && <p>{state.blockingProblem}</p>}
            {state.staleReasons.map((r) => <p key={r}>{r}</p>)}
            <p>This post can&apos;t be approved until it is regenerated from the current approved context.</p>
          </div>
        </div>
      )}
      {evaluationBlock && !approved && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4">
          <p className="flex items-start gap-2"><AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />{evaluationBlock}</p>
          {evaluateStage && onSelectStage && (
            <button onClick={() => onSelectStage(evaluateStage.id)} className={cn(pill, 'bg-muted text-foreground')}>
              <ArrowLeft className="w-4 h-4" />Go to Evaluate &amp; Improve
            </button>
          )}
        </div>
      )}
      {evaluation?.status === 'current' && evaluation.evaluation && (
        <p className="text-sm text-muted-foreground">
          Evaluation of version {evaluation.evaluation.contentVersion}: <strong className="text-foreground">{evaluation.evaluation.overallLabel}</strong>
          {' '}({evaluation.evaluation.counts.problems} problem(s), {evaluation.evaluation.counts.recommendations} recommendation(s)).
        </p>
      )}
      <div className="flex items-start gap-2 text-sm text-muted-foreground bg-muted/30 border border-border/50 rounded-2xl p-4">
        <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
        <p>Approving records your decision for this saved version only. It does not publish, schedule or send the post anywhere.
          {!approved && ' To change the post, go back to Generate Content, edit and save it, then return here.'}</p>
      </div>

      <Panel title="Hook">
        <p className="text-sm font-semibold text-foreground">{post.hook}</p>
        <p className={label}>Alternative hooks (not used)</p>
        <ul className="text-sm text-muted-foreground list-disc pl-4 space-y-1">{post.alternativeHooks.map((h) => <li key={h}>{h}</li>)}</ul>
      </Panel>

      <Panel title="Post">
        <div className="space-y-4">
          <div><p className={label}>Body</p><p className="text-sm whitespace-pre-wrap text-foreground/90">{post.body}</p></div>
          <div><p className={label}>Call to action</p><p className="text-sm text-foreground/90">{post.cta}</p></div>
          <div><p className={label}>Hashtags</p><p className="text-sm text-foreground/90">{post.hashtags.join(' ') || '—'}</p></div>
          <p className={cn('text-sm font-medium', (draft.validation?.withinLimit ?? true) ? 'text-muted-foreground' : 'text-destructive')}>
            {(draft.validation?.characterCount ?? text.length).toLocaleString()} / {policy.maxChars.toLocaleString()} characters
          </p>
        </div>
      </Panel>

      <Panel title="Final post preview">
        <div className="rounded-2xl border border-border/50 bg-background p-5 text-sm whitespace-pre-wrap leading-relaxed">{text}</div>
      </Panel>

      <Panel title="Claims & evidence">
        <p className="text-sm text-muted-foreground">{post.strategyAlignment}</p>
        <div className="space-y-2">
          {post.claims.map((c, i) => (
            <div key={i} className="rounded-2xl border border-border/50 p-3 space-y-1.5">
              <p className="text-sm">{c.text}</p>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn('text-[10px] px-2 py-0.5 rounded-full border font-medium', CLAIM_KIND[c.kind].className)}>{CLAIM_KIND[c.kind].label}</span>
                {c.refs.map((r) => (
                  <span key={r} title={evidence.get(r)} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50">{r}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        {evidence.size > 0 && (
          <div className="text-xs text-muted-foreground space-y-0.5">
            <p className={label}>Evidence references</p>
            {[...evidence].map(([ref, d]) => <p key={ref}><span className="font-mono">{ref}</span> — {d}</p>)}
          </div>
        )}
      </Panel>

      <div className="glass-panel p-6 rounded-3xl space-y-2 border-amber-500/20">
        <h4 className="text-sm font-semibold tracking-widest uppercase text-amber-500">Checks, limitations & unsupported claims</h4>
        {warnings.length === 0 && unsupported.length === 0 && <p className="text-sm text-muted-foreground">No validation warnings.</p>}
        {warnings.map((w) => <p key={w} className="text-sm text-muted-foreground">{w}</p>)}
        {unsupported.map((c) => <p key={c} className="text-sm text-amber-500">Unsupported: {c}</p>)}
        {post.limitations.map((l) => <p key={l} className="text-sm text-muted-foreground">{l}</p>)}
      </div>
    </div>
  );
}
