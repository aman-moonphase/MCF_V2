"use client"

import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { ProductService } from '@/lib/services/product.service';
import {
  Comparison, Competitor, CompetitorAnalysis, CompetitorAnalysisState, CompetitorInput, CompetitorService, Finding, Reference,
} from '@/lib/services/competitor.service';
import {
  CheckCircle2, ChevronDown, ChevronUp, Edit3, ExternalLink, FileText, GitCompare, Link2, Loader2, Lock, Plus, Search, Swords, Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
}

const SECTIONS: { key: keyof CompetitorAnalysis; coverageKey: string; label: string; empty?: string }[] = [
  { key: 'overview', coverageKey: 'overview', label: 'Overview' },
  { key: 'positioning', coverageKey: 'positioning', label: 'Positioning & value proposition' },
  { key: 'targetAudience', coverageKey: 'target_audience', label: 'Target audience' },
  { key: 'overlappingFeatures', coverageKey: 'overlapping_features', label: 'Overlap with our product' },
  { key: 'messagingThemes', coverageKey: 'messaging_themes', label: 'Messaging & themes' },
  { key: 'promotionChannels', coverageKey: 'promotion_channels', label: 'Promotion channels (in evidence)' },
  { key: 'contentFormats', coverageKey: 'content_formats', label: 'Content formats' },
  { key: 'postingCadence', coverageKey: 'posting_cadence', label: 'Posting cadence' },
  { key: 'strengths', coverageKey: 'strengths', label: 'Strengths & differentiators' },
  { key: 'opportunitiesForUs', coverageKey: 'opportunities_for_us', label: 'Opportunities for our product — suggestions, not facts',
    empty: 'No evidence-based opportunities yet: nothing in the supplied evidence points to one. See the evidence gaps below for what to investigate.' },
];

const VERIFICATION: Record<Competitor['verification'], { label: string; className: string }> = {
  user_added: { label: 'Added by you', className: 'bg-muted text-muted-foreground border-border/50' },
  named_in_sources: { label: 'Named in your sources', className: 'bg-primary/10 text-primary border-primary/20' },
  unverified: { label: 'AI suggestion · unverified', className: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
  evidence_backed: { label: 'Evidence added', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
};

const ANALYSIS_STATUS: Record<Competitor['analysisStatus'], string> = {
  not_analyzed: 'Not analyzed',
  analyzed: 'Analyzed',
  insufficient_evidence: 'Needs evidence',
  failed: 'Analysis failed',
};

const STATE_BADGE: Record<string, { label: string; className: string }> = {
  not_started: { label: 'No competitors yet', className: 'bg-muted text-muted-foreground border-border/50' },
  in_progress: { label: 'In progress', className: 'bg-primary/10 text-primary border-primary/20' },
  ready_for_review: { label: 'Ready for review', className: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
  approved: { label: 'Approved', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
};

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const inputClass = 'w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary';
const pillButton = 'inline-flex items-center gap-2 h-9 px-4 rounded-full text-sm font-medium whitespace-nowrap transition-all disabled:opacity-50 disabled:cursor-not-allowed';

function RefChips({ refs, references }: { refs: string[]; references: Record<string, Reference> }) {
  if (!refs.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 ml-2 align-middle">
      {refs.map((r) => {
        const ref = references[r];
        const title = [ref?.competitor, ref?.title, ref?.url].filter(Boolean).join(' · ');
        return (
          <span key={r} title={title} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50">
            {r}
          </span>
        );
      })}
    </span>
  );
}

function FindingList({ findings, references }: { findings: Finding[]; references: Record<string, Reference> }) {
  return (
    <ul className="space-y-1.5">
      {findings.map((f, i) => (
        <li key={i} className="text-sm text-foreground/90">
          <span className={cn(
            'text-[10px] uppercase tracking-wider font-semibold mr-2 px-1.5 py-0.5 rounded',
            f.status === 'observed' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500',
          )}>
            {f.status}
          </span>
          {f.statement}
          <RefChips refs={f.refs} references={references} />
        </li>
      ))}
    </ul>
  );
}

function AnalysisView({ analysis }: { analysis: CompetitorAnalysis }) {
  const refs = analysis.references || {};
  // Every section keeps its own heading; an empty one shows an empty state under it. The evidence-gaps box
  // lists only specific unknown items (older analyses also stored per-section "not supported" lines and
  // section names there; those are skipped because the sections already say so).
  const sectionLabels = new Set(SECTIONS.map((s) => s.label.toLowerCase()));
  const gaps = (analysis.unknowns || []).filter((u) =>
    !u.includes('not supported by the available evidence') && !sectionLabels.has(u.trim().toLowerCase()));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Confidence: <strong className="text-foreground">{analysis.confidence}</strong></span>
        {analysis.provider === 'demo' && (
          <span className="px-2 py-0.5 rounded-full border border-border/50 bg-muted">Demo mode: extracted from your evidence, not AI research</span>
        )}
      </div>
      {SECTIONS.map((s) => {
        const findings = (analysis[s.key] as Finding[]) || [];
        return (
          <div key={s.key} className="space-y-1.5">
            <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{s.label}</h5>
            {findings.length > 0
              ? <FindingList findings={findings} references={refs} />
              : <p className="text-sm italic text-muted-foreground">{s.empty || 'Unknown: the supplied evidence does not show this.'}</p>}
          </div>
        );
      })}
      {analysis.contentExamples?.length > 0 && (
        <div className="space-y-1.5">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Content examples</h5>
          {analysis.contentExamples.map((ex, i) => (
            <blockquote key={i} className="text-sm border-l-2 border-primary/40 pl-3 text-foreground/80">
              “{ex.excerpt}” <span className="text-muted-foreground">— {ex.description}</span>
              <RefChips refs={[ex.ref]} references={refs} />
            </blockquote>
          ))}
        </div>
      )}
      <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 p-4 space-y-2">
        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Unknown / evidence gaps — not shown by the supplied evidence (not proof of absence)</h5>
        {gaps.length > 0 ? (
          <ul className="space-y-1.5 list-disc pl-4">
            {gaps.map((u) => <li key={u} className="text-sm text-muted-foreground">{u}</li>)}
          </ul>
        ) : (
          <p className="text-sm italic text-muted-foreground">No specific evidence gaps recorded.</p>
        )}
        <p className="text-sm text-muted-foreground">{analysis.performanceData}</p>
      </div>
      {Object.keys(refs).length > 0 && (
        <div className="space-y-1">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Evidence references</h5>
          {Object.entries(refs).map(([label, r]) => (
            <p key={label} className="text-xs text-muted-foreground">
              <span className="font-mono mr-2">{label}</span>{r.title}{r.url && <> · <a href={r.url} target="_blank" rel="noreferrer" className="underline">{r.url}</a></>}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function ComparisonView({ comparison, outdated }: { comparison: Comparison; outdated: boolean }) {
  const refs = comparison.references || {};
  const observations: [string, Finding[]][] = [
    ['Similarities', comparison.similarities], ['Differences', comparison.differences], ['Messaging gaps', comparison.messagingGaps],
  ];
  const suggestions: [string, typeof comparison.positioningOpportunities][] = [
    ['Positioning opportunities', comparison.positioningOpportunities],
    ['Promotion patterns worth investigating', comparison.promotionPatternsToInvestigate],
  ];
  return (
    <div className="glass-panel p-6 rounded-3xl space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h4 className="flex items-center gap-2 text-lg font-semibold text-foreground"><GitCompare className="w-5 h-5 text-primary" />Comparison with our product</h4>
        {outdated && <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-500 border border-amber-500/20">Outdated — competitors changed</span>}
      </div>
      <div className="space-y-4">
        <h5 className="text-sm font-semibold tracking-widest uppercase text-primary">Evidence-based observations</h5>
        {observations.map(([label, items]) => (
          <div key={label} className="space-y-1.5">
            <h6 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</h6>
            {items.length ? <FindingList findings={items} references={refs} /> : <p className="text-sm text-muted-foreground italic">Nothing supported by the evidence.</p>}
          </div>
        ))}
      </div>
      <div className="space-y-4 pt-4 border-t border-border/50">
        <h5 className="text-sm font-semibold tracking-widest uppercase text-primary">Strategic suggestions (not facts)</h5>
        {suggestions.map(([label, items]) => (
          <div key={label} className="space-y-1.5">
            <h6 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</h6>
            {items.length ? items.map((s, i) => (
              <div key={i} className="text-sm">
                <p className="text-foreground">{s.suggestion}<RefChips refs={s.refs} references={refs} /></p>
                <p className="text-muted-foreground">{s.rationale}</p>
              </div>
            )) : <p className="text-sm text-muted-foreground italic">None yet.</p>}
          </div>
        ))}
      </div>
      {comparison.evidenceNeeded.length > 0 && (
        <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 p-4 space-y-1">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">More evidence needed</h5>
          {comparison.evidenceNeeded.map((e) => <p key={e} className="text-sm text-muted-foreground">{e}</p>)}
        </div>
      )}
    </div>
  );
}

function CompetitorForm({ initial, onSubmit, onCancel, submitLabel, busy }: {
  initial?: CompetitorInput; onSubmit: (v: CompetitorInput) => void; onCancel?: () => void; submitLabel: string; busy: boolean;
}) {
  const [values, setValues] = useState<CompetitorInput>(initial || { name: '', websiteUrl: '', description: '', notes: '' });
  const set = (k: keyof CompetitorInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setValues((v) => ({ ...v, [k]: e.target.value }));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input value={values.name || ''} onChange={set('name')} placeholder="Competitor name *" className={inputClass} />
        <input value={values.websiteUrl || ''} onChange={set('websiteUrl')} placeholder="Website (optional)" className={inputClass} />
      </div>
      <textarea value={values.description || ''} onChange={set('description')} placeholder="What you know about their product or positioning (optional)" className={cn(inputClass, 'min-h-[60px]')} />
      <textarea value={values.notes || ''} onChange={set('notes')} placeholder="Your observations, e.g. posts or ads you have seen (optional)" className={cn(inputClass, 'min-h-[60px]')} />
      <div className="flex gap-2">
        <button onClick={() => onSubmit(values)} disabled={busy || !values.name?.trim()} className={cn(pillButton, 'bg-foreground text-background')}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}{submitLabel}
        </button>
        {onCancel && <button onClick={onCancel} className={cn(pillButton, 'bg-muted text-foreground')}>Cancel</button>}
      </div>
    </div>
  );
}

function EvidenceForm({ onAdd, busy }: { onAdd: (type: 'url' | 'note' | 'pdf', content: string, file: File | null) => Promise<boolean>; busy: boolean }) {
  const [type, setType] = useState<'url' | 'note' | 'pdf'>('url');
  const [content, setContent] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const submit = async () => {
    if (await onAdd(type, content, file)) { setContent(''); setFile(null); }
  };
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        {(['url', 'note', 'pdf'] as const).map((t) => (
          <button key={t} onClick={() => setType(t)} className={cn(pillButton, 'h-8 px-3 text-xs', type === t ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground')}>
            {t === 'url' ? 'Web page URL' : t === 'note' ? 'Pasted observations' : 'PDF'}
          </button>
        ))}
      </div>
      {type === 'url' && <input value={content} onChange={(e) => setContent(e.target.value)} placeholder="https://competitor.example/pricing" className={inputClass} />}
      {type === 'note' && <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="Paste what you observed: post text, ad copy, landing-page claims…" className={cn(inputClass, 'min-h-[80px]')} />}
      {type === 'pdf' && <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" />}
      <p className="text-xs text-muted-foreground">Social media pages are not fetched — paste what you saw there as observations.</p>
      <button onClick={submit} disabled={busy || (type === 'pdf' ? !file : !content.trim())} className={cn(pillButton, 'bg-muted text-foreground')}>
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}Add evidence
      </button>
    </div>
  );
}

export function CompetitorAnalysisStage({ project, activeStage, onComplete }: Props) {
  const [productId, setProductId] = useState<string | null>(null);
  const [state, setState] = useState<CompetitorAnalysisState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const reload = useCallback(async (id: string) => setState(await CompetitorService.getState(id)), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const product = await ProductService.getForProject(project.id);
        if (cancelled || !product) return;
        setProductId(product.id);
        const s = await CompetitorService.getState(product.id);
        if (!cancelled) setState(s);
      } catch (e) {
        toast.error(`Could not load Competitor Analysis: ${errorMessage(e)}`);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id]);

  const run = async (key: string, action: () => Promise<unknown>, success?: string) => {
    if (!productId) return false;
    setBusy(key);
    try {
      await action();
      await reload(productId);
      if (success) toast.success(success);
      return true;
    } catch (e) {
      toast.error(errorMessage(e));
      return false;
    } finally {
      setBusy(null);
    }
  };

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-[40vh]"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  if (!productId || !state || state.status === 'locked') {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2"><Lock className="w-8 h-8 text-muted-foreground/50" /></div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-sm">Approve the Product Profile in Product Understanding before analyzing competitors.</p>
      </div>
    );
  }

  const pid = productId;
  const analyzedCount = state.competitors.filter((c) => c.analysisStatus === 'analyzed').length;
  const badge = STATE_BADGE[state.status];
  const summary = state.productSummary;

  const discover = () => run('discover', async () => {
    const res = await CompetitorService.discover(pid);
    if (res.added.length) toast.success(`Added: ${res.added.join(', ')}`);
    else toast.message(res.messages.join(' '));
  });

  const approve = async (limited = false) => {
    if (limited && !confirm(
      'Approve with limited evidence?\n\nThe Promotion Strategy will be told competitor evidence is limited: ' +
      'competitor-based ideas become hypotheses and confidence is lowered. You can add evidence later.')) return;
    const ok = await run('approve', () => CompetitorService.approve(pid, project.id, state.version, limited),
      limited ? 'Approved with limited competitor evidence' : 'Competitor Analysis approved');
    if (ok && activeStage.status !== 'Completed') await onComplete();
  };

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      {/* Title and actions share one wrapping row: the title takes the remaining width (min 18rem) and the
          action group wraps below it, and its buttons wrap among themselves, instead of squeezing the title. */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div className="min-w-0 flex-[1_1_18rem]">
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">Competitor Analysis</h3>
            {badge && <span className={cn('px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap', badge.className)}>{badge.label}</span>}
            {state.limitedEvidence && (
              <span className="px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap bg-amber-500/10 text-amber-500 border-amber-500/20">Limited evidence</span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">Evidence you supply → observed, inferred, or unknown. Nothing is researched or invented behind the scenes.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
          <button onClick={discover} disabled={!!busy} className={cn(pillButton, 'bg-muted text-foreground')}>
            {busy === 'discover' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}Find candidates
          </button>
          <button onClick={() => run('compare', () => CompetitorService.compare(pid), 'Comparison updated')} disabled={!!busy || !analyzedCount} className={cn(pillButton, 'bg-muted text-foreground')}>
            {busy === 'compare' ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitCompare className="w-4 h-4" />}Compare with {state.productName}
          </button>
          {state.status !== 'approved' && state.status !== 'ready_for_review' && (
            <button onClick={() => approve(true)} disabled={!!busy} className={cn(pillButton, 'bg-muted text-foreground')}
              title="Continue without full competitor evidence; the strategy will treat competitor ideas as hypotheses">
              <CheckCircle2 className="w-4 h-4" />Approve with limited evidence
            </button>
          )}
          {state.status !== 'approved' && (
            <button onClick={() => approve()} disabled={!!busy || state.status !== 'ready_for_review'} title={state.status !== 'ready_for_review' ? 'Analyze at least one competitor and generate the comparison first' : ''}
              className={cn(pillButton, 'bg-primary text-primary-foreground shadow-md')}>
              {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}Approve Competitor Analysis
            </button>
          )}
        </div>
      </div>

      <div className="glass-panel p-6 rounded-3xl space-y-3">
        <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Our approved product</h4>
        <p className="text-lg font-semibold text-foreground">{state.productName}{summary.category ? <span className="text-sm font-normal text-muted-foreground"> · {summary.category as string}</span> : null}</p>
        {summary.valueProposition && <p className="text-sm text-foreground/90">{summary.valueProposition as string}</p>}
        {summary.targetAudience && <p className="text-sm text-muted-foreground">For: {summary.targetAudience as string}</p>}
        {Array.isArray(summary.differentiators) && summary.differentiators.length > 0 && (
          <div className="flex flex-wrap gap-2">{(summary.differentiators as string[]).map((d) => <span key={d} className="text-xs bg-muted/30 px-2.5 py-1 rounded-lg border border-border/30">{d}</span>)}</div>
        )}
      </div>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Competitors ({state.competitors.length})</h4>
          <button onClick={() => setShowAdd((v) => !v)} className={cn(pillButton, 'bg-foreground text-background')}><Plus className="w-4 h-4" />Add competitor</button>
        </div>

        {showAdd && (
          <div className="glass-panel p-5 rounded-2xl">
            <CompetitorForm submitLabel="Add competitor" busy={busy === 'create'} onCancel={() => setShowAdd(false)}
              onSubmit={async (v) => { if (await run('create', () => CompetitorService.create(pid, v), `${v.name} added`)) setShowAdd(false); }} />
          </div>
        )}

        {state.competitors.length === 0 && !showAdd && (
          <div className="border-2 border-dashed border-border/50 rounded-3xl p-10 text-center space-y-2">
            <Swords className="w-10 h-10 text-muted-foreground/50 mx-auto" />
            <p className="font-medium text-foreground">No competitors yet</p>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Use <strong>Find candidates</strong> to pick up competitors named in your product sources, or add the ones you know.
              Then add evidence: their website, a PDF, or what you have seen them post.
            </p>
          </div>
        )}

        {state.competitors.map((c) => {
          const open = expanded === c.id;
          const v = VERIFICATION[c.verification];
          return (
            <div key={c.id} className="glass-panel rounded-2xl overflow-hidden">
              <div className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <button onClick={() => setExpanded(open ? null : c.id)} className="text-left flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-foreground">{c.name}</span>
                    <span className={cn('text-[10px] px-2 py-0.5 rounded-full border', v.className)}>{v.label}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full border border-border/50 text-muted-foreground">{ANALYSIS_STATUS[c.analysisStatus]}</span>
                    <span className="text-xs text-muted-foreground">{c.evidence.filter((e) => e.status === 'completed').length} evidence</span>
                  </div>
                  {c.websiteUrl && <p className="text-xs text-muted-foreground truncate">{c.websiteUrl}</p>}
                  {c.suggestionReason && c.verification === 'unverified' && <p className="text-xs text-amber-500">{c.suggestionReason}</p>}
                </button>
                <div className="flex items-center gap-2 shrink-0">
                  <button onClick={() => run(`analyze-${c.id}`, () => CompetitorService.analyze(pid, c.id), `${c.name} analyzed`).then((ok) => ok && setExpanded(c.id))}
                    disabled={!!busy} className={cn(pillButton, 'bg-primary text-primary-foreground')}>
                    {busy === `analyze-${c.id}` ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}Analyze
                  </button>
                  <button onClick={() => { setEditing(c.id); setExpanded(c.id); }} disabled={!!busy} className={cn(pillButton, 'bg-muted text-foreground px-3')} aria-label="Edit"><Edit3 className="w-4 h-4" /></button>
                  <button onClick={() => { if (confirm(`Remove ${c.name} and its evidence?`)) run(`delete-${c.id}`, () => CompetitorService.remove(pid, c.id), `${c.name} removed`); }}
                    disabled={!!busy} className={cn(pillButton, 'bg-muted text-foreground px-3')} aria-label="Remove"><Trash2 className="w-4 h-4" /></button>
                  <button onClick={() => setExpanded(open ? null : c.id)} className="text-muted-foreground" aria-label="Expand">{open ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}</button>
                </div>
              </div>

              {open && (
                <div className="px-5 pb-6 space-y-6 border-t border-border/50 pt-5">
                  {editing === c.id && (
                    <CompetitorForm initial={{ name: c.name, websiteUrl: c.websiteUrl || '', description: c.description || '', notes: c.notes || '' }}
                      submitLabel="Save" busy={busy === `edit-${c.id}`} onCancel={() => setEditing(null)}
                      onSubmit={async (vals) => { if (await run(`edit-${c.id}`, () => CompetitorService.update(pid, c.id, vals), 'Competitor saved')) setEditing(null); }} />
                  )}
                  {editing !== c.id && (c.description || c.notes) && (
                    <div className="text-sm space-y-1">
                      {c.description && <p><span className="font-mono text-xs text-muted-foreground mr-2">D</span>{c.description}</p>}
                      {c.notes && <p><span className="font-mono text-xs text-muted-foreground mr-2">N</span>{c.notes}</p>}
                    </div>
                  )}

                  <div className="space-y-3">
                    <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Evidence</h5>
                    {c.evidence.length === 0 && <p className="text-sm text-muted-foreground">No evidence yet.</p>}
                    {c.evidence.map((e) => (
                      <div key={e.id} className="flex items-start justify-between gap-3 text-sm bg-muted/20 rounded-xl p-3 border border-border/30">
                        <div className="min-w-0">
                          <p className="font-medium text-foreground flex items-center gap-2">
                            {e.evidenceType === 'url' ? <ExternalLink className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
                            <span className="truncate">{e.title}</span>
                            <span className={cn('text-[10px] px-1.5 py-0.5 rounded', e.status === 'completed' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500')}>{e.status.replace('_', ' ')}</span>
                          </p>
                          {e.error ? <p className="text-xs text-amber-500">{e.error}</p> : e.excerpt && <p className="text-xs text-muted-foreground line-clamp-2">{e.excerpt}</p>}
                        </div>
                        <button onClick={() => run(`ev-${e.id}`, () => CompetitorService.removeEvidence(pid, c.id, e.id), 'Evidence removed')} disabled={!!busy} className="text-muted-foreground hover:text-foreground" aria-label="Remove evidence">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                    <EvidenceForm busy={busy === `add-ev-${c.id}`} onAdd={(type, content, file) => run(`add-ev-${c.id}`, async () => {
                      const res = await CompetitorService.addEvidence(pid, c.id, type, content, file);
                      if (res.status !== 'completed' && res.error) toast.warning(res.error);
                    }, 'Evidence added')} />
                  </div>

                  {c.analysisError && <p className="text-sm text-amber-500">{c.analysisError}</p>}
                  {c.analysis && (
                    <div className="space-y-3">
                      <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Analysis{c.lastAnalyzedAt && ` · ${new Date(c.lastAnalyzedAt).toLocaleString()}`}
                      </h5>
                      <AnalysisView analysis={c.analysis} />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {state.comparison ? (
        <ComparisonView comparison={state.comparison} outdated={state.comparisonOutdated} />
      ) : analyzedCount > 0 && (
        <p className="text-sm text-muted-foreground text-center">Analyzed competitors are ready — use <strong>Compare with {state.productName}</strong> to compare them with our product.</p>
      )}
    </div>
  );
}
