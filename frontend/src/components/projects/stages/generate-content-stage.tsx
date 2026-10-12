"use client"

import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { CompetitorFindings, GenerationService, GenerationState, LinkedInPost, PostClaim } from '@/lib/services/generation.service';
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Circle, Loader2, Lock, PenLine, RefreshCw, Save, Sparkles, Undo2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { UsageSummary } from '../usage-summary';
import { CreativeImagePreview } from '../creative-image-preview';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
  onSelectStage?: (stageId: string) => void;
  onRefreshOrchestration?: () => Promise<void> | void;
}

interface Edits {
  hook: string;
  alternativeHooks: string[];
  body: string;
  cta: string;
  hashtags: string;
}

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pill = 'inline-flex items-center gap-2 h-10 px-5 rounded-full text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed';
const field = 'w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary';
const label = 'text-xs font-semibold uppercase tracking-wider text-muted-foreground';

const CLAIM_KIND: Record<PostClaim['kind'], { label: string; className: string }> = {
  product_fact: { label: 'Product fact', className: 'bg-primary/10 text-primary border-primary/20' },
  creative: { label: 'Messaging', className: 'bg-muted text-muted-foreground border-border/50' },
  competitor_context: { label: 'Informed by competitors', className: 'bg-sky-500/10 text-sky-500 border-sky-500/20' },
};

const toEdits = (post: LinkedInPost): Edits => ({
  hook: post.hook, alternativeHooks: [...post.alternativeHooks], body: post.body, cta: post.cta, hashtags: post.hashtags.join(' '),
});

const parseTags = (text: string) =>
  text.split(/[\s,]+/).map((t) => t.replace(/[^\w]/g, '')).filter(Boolean).map((t) => `#${t}`);

// Mirrors app/ai/generation_validation.py::assemble so the counter matches the server's count.
const assemble = (e: Edits) =>
  [e.hook.trim(), e.body.trim(), e.cta.trim(), parseTags(e.hashtags).join(' ')].filter(Boolean).join('\n\n');

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('glass-panel p-6 rounded-3xl space-y-4', className)}>
      <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">{title}</h4>
      {children}
    </div>
  );
}

function Fact({ name, value }: { name: string; value?: string | null | string[] }) {
  const empty = !value || (Array.isArray(value) && !value.length);
  return (
    <div>
      <p className={label}>{name}</p>
      {empty ? <p className="text-sm italic text-muted-foreground">Not in the approved profile</p>
        : Array.isArray(value) ? <ul className="text-sm text-foreground/90 list-disc pl-4">{value.map((v) => <li key={v}>{v}</li>)}</ul>
          : <p className="text-sm text-foreground/90">{value}</p>}
    </div>
  );
}

function RefChips({ refs }: { refs: string[] }) {
  return <>{refs.map((r) => (
    <span key={r} className="ml-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50 align-middle">{r}</span>
  ))}</>;
}

function StatusTag({ text, className }: { text: string; className: string }) {
  return <span className={cn('mr-2 text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded', className)}>{text}</span>;
}

/** The approved comparison with its uncertainty kept visible: differences, possible overlaps, suggestions, unknowns. */
function CompetitorInsights({ findings }: { findings: CompetitorFindings }) {
  const sub = 'text-[11px] font-semibold text-foreground/80';
  const byCompetitor = findings.unresolved.reduce<Record<string, string[]>>((acc, u) => {
    (acc[u.competitor] ||= []).push(u.feature);
    return acc;
  }, {});
  return (
    <div className="space-y-3 text-sm">
      <div className="space-y-1">
        <p className={sub}>Differences & messaging gaps</p>
        {findings.differences.length ? (
          <ul className="space-y-1">{findings.differences.map((f) => (
            <li key={f.statement} className="text-muted-foreground">
              <StatusTag text={f.status} className={f.status === 'observed' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'} />
              {f.statement}<RefChips refs={f.refs} />
            </li>
          ))}</ul>
        ) : <p className="italic text-muted-foreground">No evidence-based differences or messaging gaps.</p>}
      </div>
      {findings.similarities.length > 0 && (
        <div className="space-y-1">
          <p className={sub}>Possible overlaps — not unique advantages</p>
          <ul className="space-y-1">{findings.similarities.map((f) => (
            <li key={f.statement} className="text-muted-foreground">
              <StatusTag text={`${f.status} · unconfirmed`} className="bg-amber-500/10 text-amber-500" />
              {f.statement}<RefChips refs={f.refs} />
            </li>
          ))}</ul>
        </div>
      )}
      {findings.suggestions.length > 0 && (
        <div className="space-y-1">
          <p className={sub}>Suggestions to evaluate — not facts</p>
          <ul className="space-y-1">{findings.suggestions.map((s) => (
            <li key={s.suggestion} className="text-muted-foreground">
              <StatusTag text="suggestion" className="bg-sky-500/10 text-sky-500" />
              {s.suggestion}<RefChips refs={s.refs} />
            </li>
          ))}</ul>
        </div>
      )}
      {Object.entries(byCompetitor).map(([competitor, features]) => (
        <div key={competitor} className="space-y-1">
          <p className={sub}>Unresolved comparisons — unknown</p>
          <p className="text-muted-foreground">
            The supplied evidence does not establish whether {competitor} offers: {features.join(', ')}.
            This is unknown — not evidence that {competitor} lacks them.
          </p>
        </div>
      ))}
    </div>
  );
}

export function GenerateContentStage({ project, activeStage, onComplete, onRefreshOrchestration }: Props) {
  const [state, setState] = useState<GenerationState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState<'generate' | 'save' | 'continue' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pillarIndex, setPillarIndex] = useState(0);
  const [instructions, setInstructions] = useState('');
  const [edits, setEdits] = useState<Edits | null>(null);

  const apply = (next: GenerationState) => {
    setState(next);
    setEdits(next.draft ? toEdits(next.draft.content) : null);
    const snap = next.draft?.contextSnapshot;
    if (snap) {
      setPillarIndex(snap.pillarIndex ?? 0);
      setInstructions(snap.instructions ?? '');
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await GenerationService.get(project.id);
        if (!cancelled) apply(s);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id]);

  const draft = state?.draft;
  const nextStage = project.stages[project.stages.findIndex((s) => s.id === activeStage.id) + 1];
  const nextStageLabel = nextStage?.label ?? 'next stage';
  const dirty = useMemo(() => {
    if (!draft || !edits) return false;
    return JSON.stringify(edits) !== JSON.stringify(toEdits(draft.content));
  }, [draft, edits]);

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-[40vh]"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  if (!state) {
    return (
      <div className="flex items-center gap-2 text-destructive bg-destructive/10 px-4 py-3 rounded-lg text-sm">
        <AlertTriangle className="w-4 h-4 shrink-0" /><p>Could not load Generate Content: {error}</p>
      </div>
    );
  }

  if (state.status === 'not_applicable' || (state.status === 'blocked' && !draft)) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2"><Lock className="w-8 h-8 text-muted-foreground/50" /></div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-md">{state.blockingProblem}</p>
        {state.prerequisites.length > 0 && (
          <ul className="text-sm text-left space-y-1.5">
            {state.prerequisites.map((p) => (
              <li key={p.key} className="flex items-center gap-2">
                {p.met ? <CheckCircle2 className="w-4 h-4 text-emerald-500" /> : <Circle className="w-4 h-4 text-muted-foreground" />}
                <span className={p.met ? 'text-foreground' : 'text-muted-foreground'}>{p.label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const ctx = state.context;
  const policy = state.policy;
  const approved = state.status === 'approved';

  const generate = async () => {
    if (dirty && !window.confirm('Regenerating replaces your unsaved edits with a new draft. Continue?')) return;
    setBusy('generate');
    setError(null);
    try {
      apply(await GenerationService.generate(project.id, pillarIndex, instructions));
      toast.success(draft ? 'New draft generated' : 'LinkedIn post generated');
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

  const save = async () => {
    if (!draft || !edits) return;
    setBusy('save');
    setError(null);
    try {
      apply(await GenerationService.update(project.id, {
        hook: edits.hook, alternativeHooks: edits.alternativeHooks, body: edits.body, cta: edits.cta, hashtags: parseTags(edits.hashtags),
      }, draft.version));
      toast.success('Post saved');
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

  const chooseHook = (index: number) => setEdits((e) => {
    if (!e) return e;
    const alternatives = [...e.alternativeHooks];
    const chosen = alternatives[index];
    alternatives[index] = e.hook;
    return { ...e, hook: chosen, alternativeHooks: alternatives };
  });

  const text = edits ? assemble(edits) : '';
  const overLimit = text.length > policy.maxChars;
  const hookLong = (edits?.hook.length ?? 0) > policy.hookMaxChars;
  const evidence = new Map((draft?.evidence ?? []).map((e) => [e.ref, e.description]));

  const controls = (
    <Panel title="Generate">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <p className={label}>Content pillar</p>
          <select value={pillarIndex} onChange={(e) => setPillarIndex(Number(e.target.value))} disabled={!!busy || approved} className={field}>
            {(ctx?.pillars ?? []).map((p, i) => <option key={i} value={i}>{p.name}</option>)}
          </select>
          {ctx?.pillars[pillarIndex] && <p className="text-xs text-muted-foreground">{ctx.pillars[pillarIndex].purpose}</p>}
        </div>
        <div className="space-y-1.5">
          <p className={label}>Campaign instructions (optional)</p>
          <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={3} maxLength={1000} disabled={!!busy || approved}
            placeholder="e.g. Focus on the end-of-quarter tax deadline" className={field} />
        </div>
      </div>
      {state.provider === 'demo' && (
        <p className="text-xs text-amber-500">
          Demo mode: the post is assembled deterministically from your approved data. It does not follow free-text instructions.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={generate} disabled={!!busy || !state.canGenerate} className={cn(pill, draft ? 'bg-muted text-foreground' : 'bg-foreground text-background font-semibold h-12 px-8')}>
          {busy === 'generate' ? <><Loader2 className="w-4 h-4 animate-spin" />Generating…</>
            : draft ? <><RefreshCw className="w-4 h-4" />Regenerate</> : <><Sparkles className="w-4 h-4" />Generate LinkedIn Post</>}
        </button>
        {!state.canGenerate && state.blockingProblem && <p className="text-xs text-amber-500">{state.blockingProblem}</p>}
      </div>
    </Panel>
  );

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">{policy.platform} {policy.contentType} · {ctx?.productName}</h3>
            {draft && (
              <span className={cn('px-3 py-1 rounded-full text-xs font-medium border',
                approved ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : 'bg-amber-500/10 text-amber-500 border-amber-500/20')}>
                {approved ? 'Approved' : draft.edited ? 'Draft · edited' : 'Draft'}
              </span>
            )}
            {draft?.isDemo && (
              <span className="px-3 py-1 rounded-full text-xs font-medium border bg-amber-500/10 text-amber-500 border-amber-500/20">Demo output</span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {draft ? `Version ${draft.version} · generated by ${draft.provider}` : 'Grounded in your approved profile, competitor insights and strategy'}
          </p>
          {draft && <UsageSummary draft={draft} />}
        </div>
        {draft && (
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            {dirty && (
              <>
                <button onClick={save} disabled={!!busy || overLimit} className={cn(pill, 'bg-primary text-primary-foreground')}>
                  {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}Save
                </button>
                <button onClick={() => setEdits(toEdits(draft.content))} disabled={!!busy} className={cn(pill, 'bg-muted text-foreground')}>
                  <Undo2 className="w-4 h-4" />Discard
                </button>
              </>
            )}
            {!dirty && activeStage.status !== 'Completed' && (
              <button onClick={proceed} disabled={!!busy} className={cn(pill, 'bg-primary text-primary-foreground shadow-md')}>
                {busy === 'continue' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}Continue to {nextStageLabel}
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /><p>{error}</p>
        </div>
      )}
      {state.stale && (
        <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>{state.staleReasons.map((r) => <p key={r}>{r}</p>)}<p>Regenerate once the earlier stages are approved again.</p></div>
        </div>
      )}

      {ctx && (
        <Panel title="Approved context used for generation">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Fact name="Audience" value={ctx.targetAudience} />
            <Fact name="Problem" value={ctx.problemSolved} />
            <Fact name="Value proposition" value={ctx.valueProposition} />
            <Fact name="Messaging direction" value={ctx.messagingDirection} />
            <Fact name="Key features" value={ctx.keyFeatures} />
            <Fact name="Differentiators" value={ctx.differentiators} />
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
            <span>Content type: {ctx.approvedType || '—'}</span>
            <span>Primary channel: {ctx.primaryChannel || '—'}</span>
          </div>
          <div className="space-y-3">
            <p className={label}>Competitor insights (inform emphasis only)</p>
            {ctx.limitedEvidence ? <p className="text-sm text-amber-500">Limited competitor evidence — the post is positioned from the profile only.</p>
              : !ctx.competitor ? <p className="text-sm italic text-muted-foreground">No approved, current competitor comparison.</p>
                : <CompetitorInsights findings={ctx.competitor} />}
          </div>
        </Panel>
      )}

      {!approved && controls}

      {busy === 'generate' && !draft && (
        <div className="flex items-center justify-center gap-3 py-12 text-muted-foreground"><Loader2 className="w-6 h-6 animate-spin text-primary" />Writing the post from your approved context…</div>
      )}

      {draft && edits && (
        <>
          <Panel title="Hook">
            <div className="space-y-2">
              <div className="flex items-start gap-3 rounded-2xl border-2 border-primary bg-primary/5 p-4">
                <Check className="w-4 h-4 text-primary mt-1 shrink-0" />
                {approved ? <p className="text-sm font-semibold">{edits.hook}</p>
                  : <textarea value={edits.hook} rows={2} onChange={(e) => setEdits({ ...edits, hook: e.target.value })} className={cn(field, 'font-semibold')} />}
              </div>
              <p className={cn('text-xs', hookLong ? 'text-amber-500' : 'text-muted-foreground')}>
                {edits.hook.length} characters · about {policy.hookMaxChars} show before &ldquo;…see more&rdquo;
              </p>
              <p className={label}>Alternative hooks</p>
              {edits.alternativeHooks.map((h, i) => (
                <button key={i} onClick={() => chooseHook(i)} disabled={approved}
                  className="w-full text-left flex items-start gap-3 rounded-2xl border border-border/50 p-3 text-sm hover:border-primary/50 transition-colors disabled:cursor-default">
                  <PenLine className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <span className="flex-1">{h}</span>
                  {!approved && <span className="text-xs text-primary shrink-0">Use this</span>}
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Post">
            <div className="space-y-4">
              <div className="space-y-1.5">
                <p className={label}>Body</p>
                <textarea value={edits.body} rows={10} readOnly={approved} onChange={(e) => setEdits({ ...edits, body: e.target.value })} className={field} />
              </div>
              <div className="space-y-1.5">
                <p className={label}>Call to action</p>
                <input value={edits.cta} readOnly={approved} onChange={(e) => setEdits({ ...edits, cta: e.target.value })} className={field} />
              </div>
              <div className="space-y-1.5">
                <p className={label}>Hashtags (max {policy.maxHashtags})</p>
                <input value={edits.hashtags} readOnly={approved} onChange={(e) => setEdits({ ...edits, hashtags: e.target.value })} className={field} />
              </div>
              <p className={cn('text-sm font-medium', overLimit ? 'text-destructive' : 'text-muted-foreground')}>
                {text.length.toLocaleString()} / {policy.maxChars.toLocaleString()} characters{overLimit && ' — over the LinkedIn limit'}
                {dirty && <span className="ml-2 text-amber-500">· unsaved changes</span>}
              </p>
            </div>
          </Panel>

          <Panel title="Creative Preview">
            <CreativeImagePreview
              projectId={project.id}
              draft={draft}
              approved={approved}
              productName={ctx?.productName}
              onStateChange={(next) => setState(next)}
            />
          </Panel>

          <Panel title="Claims & evidence">
            <p className="text-sm text-muted-foreground">{draft.content.strategyAlignment}</p>
            <div className="space-y-2">
              {draft.content.claims.map((c, i) => (
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
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">Evidence labels</summary>
                <ul className="mt-2 space-y-0.5">{[...evidence].map(([ref, d]) => <li key={ref}><span className="font-mono">{ref}</span> — {d}</li>)}</ul>
              </details>
            )}
          </Panel>

          {((draft.validation?.warnings?.length ?? 0) > 0 || (draft.validation?.unsupportedClaims?.length ?? 0) > 0 || draft.content.limitations.length > 0) && (
            <div className="glass-panel p-6 rounded-3xl space-y-2 border-amber-500/20">
              <h4 className="text-sm font-semibold tracking-widest uppercase text-amber-500">Checks, limitations & unsupported claims</h4>
              {draft.validation?.warnings?.map((w) => <p key={w} className="text-sm text-muted-foreground">{w}</p>)}
              {draft.validation?.unsupportedClaims?.map((c) => <p key={c} className="text-sm text-amber-500">Unsupported: {c}</p>)}
              {draft.content.limitations.map((l) => <p key={l} className="text-sm text-muted-foreground">{l}</p>)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
