"use client"

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { ProductService } from '@/lib/services/product.service';
import { Grounding, PromotionStrategy, StrategyService, StrategyState } from '@/lib/services/strategy.service';
import { AlertTriangle, CheckCircle2, Compass, Edit3, Loader2, Lock, RefreshCw, Save } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
}

const CONTENT_TYPES = ['Video', 'Image', 'Carousel', 'Article', 'Newsletter', 'Social Post'];

const BASIS: Record<Grounding['basis'], { label: string; className: string }> = {
  competitor_observed: { label: 'Observed competitor pattern', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
  evidence_inferred: { label: 'Inferred from competitor evidence', className: 'bg-sky-500/10 text-sky-500 border-sky-500/20' },
  product_profile: { label: 'From Product Profile', className: 'bg-primary/10 text-primary border-primary/20' },
  hypothesis: { label: 'Hypothesis to test', className: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
};

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pill = 'inline-flex items-center gap-2 h-10 px-5 rounded-full text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed';
const field = 'w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary';
const label = 'text-xs font-semibold uppercase tracking-wider text-muted-foreground';

type Path = (string | number)[];

type Container = Record<string | number, unknown>;

function setIn<T>(obj: T, path: Path, value: unknown): T {
  const copy = (Array.isArray(obj) ? [...obj] : { ...(obj as object) }) as unknown as Container;
  const [head, ...rest] = path;
  copy[head] = rest.length ? setIn(copy[head], rest, value) : value;
  return copy as unknown as T;
}

function GroundingBadge({ g }: { g: Grounding }) {
  const b = BASIS[g.basis];
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={cn('text-[10px] px-2 py-0.5 rounded-full border font-medium', b.className)}>{b.label}</span>
      <span className="text-[10px] text-muted-foreground">confidence {g.confidence}</span>
      {g.refs.map((r) => (
        <span key={r} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/50">{r}</span>
      ))}
    </span>
  );
}

function Text({ value, editing, onChange, rows = 2 }: { value: string; editing: boolean; onChange: (v: string) => void; rows?: number }) {
  return editing
    ? <textarea value={value} rows={rows} onChange={(e) => onChange(e.target.value)} className={field} />
    : <p className="text-sm text-foreground/90">{value || <span className="italic text-muted-foreground">—</span>}</p>;
}

function Lines({ value, editing, onChange }: { value: string[]; editing: boolean; onChange: (v: string[]) => void }) {
  if (editing) {
    return <textarea value={value.join('\n')} rows={Math.max(2, value.length)} placeholder="One per line"
      onChange={(e) => onChange(e.target.value.split('\n'))} className={field} />;
  }
  if (!value.length) return <p className="text-sm italic text-muted-foreground">None</p>;
  return <div className="flex flex-wrap gap-2">{value.map((v) => <span key={v} className="text-sm bg-muted/30 px-3 py-1 rounded-lg border border-border/30">{v}</span>)}</div>;
}

function Section({ title, grounding, children }: { title: string; grounding?: Grounding; children: React.ReactNode }) {
  return (
    <div className="glass-panel p-6 rounded-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">{title}</h4>
        {grounding && <GroundingBadge g={grounding} />}
      </div>
      {children}
    </div>
  );
}

export function PromotionStrategyStage({ project, activeStage, onComplete }: Props) {
  const [productId, setProductId] = useState<string | null>(null);
  const [state, setState] = useState<StrategyState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState<'generate' | 'save' | 'approve' | null>(null);
  const [draft, setDraft] = useState<PromotionStrategy | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const product = await ProductService.getForProject(project.id);
        if (cancelled || !product) return;
        setProductId(product.id);
        const s = await StrategyService.get(product.id);
        if (!cancelled) setState(s);
      } catch (e) {
        toast.error(`Could not load the Promotion Strategy: ${errorMessage(e)}`);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.id]);

  const act = async (kind: 'generate' | 'save' | 'approve', fn: () => Promise<StrategyState>, success: string) => {
    setBusy(kind);
    try {
      const next = await fn();
      setState(next);
      toast.success(success);
      return next;
    } catch (e) {
      toast.error(errorMessage(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-[40vh]"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  if (!productId || !state || (!state.prerequisitesMet && state.status === 'not_generated')) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2"><Lock className="w-8 h-8 text-muted-foreground/50" /></div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-sm">{state?.prerequisiteProblem || 'Approve the Product Profile and Competitor Analysis first.'}</p>
      </div>
    );
  }

  const pid = productId;
  const generate = () => act('generate', () => StrategyService.generate(pid), 'Promotion Strategy generated');

  if (state.status === 'not_generated' || !state.strategy) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary"><Compass className="w-8 h-8" /></div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Build the Promotion Strategy</h3>
          <p className="text-muted-foreground text-sm mb-4">
            A product-level plan from your approved Product Profile and Competitor Analysis: audience, positioning, pillars,
            channels, the ONE content type to start with, cadence, roadmap and measurement.
          </p>
          {state.limitedEvidence && (
            <p className="text-xs text-amber-500 mb-4">Competitor Analysis was approved with limited evidence — competitor-based ideas will be marked as hypotheses.</p>
          )}
          <button onClick={generate} disabled={!!busy} className={cn(pill, 'h-12 px-8 w-full justify-center bg-foreground text-background font-semibold')}>
            {busy === 'generate' ? <><Loader2 className="w-5 h-5 animate-spin" />Building strategy...</> : <><Compass className="w-5 h-5" />Generate Strategy</>}
          </button>
        </div>
      </div>
    );
  }

  const editing = draft !== null;
  const s = (draft || state.strategy) as PromotionStrategy;
  const set = (path: Path) => (value: unknown) => setDraft((d) => (d ? setIn(d, path, value) : d));
  const approved = state.status === 'approved';

  const save = async () => {
    if (!draft || !state.strategy) return;
    const original = state.strategy as unknown as Record<string, unknown>;
    const edited = draft as unknown as Record<string, unknown>;
    const clean = (v: unknown): unknown => Array.isArray(v) ? v.map(clean).filter((x) => x !== '') : (v && typeof v === 'object')
      ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, typeof x === 'string' ? x.trim() : clean(x)])) : v;
    const changed = Object.fromEntries(Object.keys(edited)
      .filter((k) => k !== 'limitations' && JSON.stringify(edited[k]) !== JSON.stringify(original[k]))
      .map((k) => [k, clean(edited[k])]));
    if (!Object.keys(changed).length) { setDraft(null); return; }
    const next = await act('save', () => StrategyService.update(pid, changed as Partial<PromotionStrategy>), 'Strategy saved — approve it again to continue');
    if (next) setDraft(null);
  };

  const approve = async () => {
    const next = await act('approve', () => StrategyService.approve(pid, project.id, state.version || 0), 'Promotion Strategy approved');
    if (next && activeStage.status !== 'Completed') await onComplete();
  };

  const cd = s.contentDirection;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">Promotion Strategy · {state.productName}</h3>
            <span className={cn('px-3 py-1 rounded-full text-xs font-medium border',
              approved ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : 'bg-amber-500/10 text-amber-500 border-amber-500/20')}>
              {approved ? 'Approved' : 'Draft — review and approve'}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            Version {state.version}
            {state.basis?.competitors?.length ? ` · uses competitor analysis of ${state.basis.competitors.join(', ')}` : ' · no analysed competitors'}
            {state.provider === 'demo' && ' · Demo mode: built from your profile and evidence only'}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap shrink-0">
          {editing ? (
            <>
              <button onClick={save} disabled={!!busy} className={cn(pill, 'bg-primary text-primary-foreground')}>
                {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}Save Strategy
              </button>
              <button onClick={() => setDraft(null)} className={cn(pill, 'bg-muted text-foreground')}>Cancel</button>
            </>
          ) : (
            <>
              <button onClick={generate} disabled={!!busy || !state.prerequisitesMet} className={cn(pill, 'bg-muted text-foreground')}>
                {busy === 'generate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}Regenerate
              </button>
              <button onClick={() => setDraft(JSON.parse(JSON.stringify(state.strategy)))} disabled={!!busy} className={cn(pill, 'bg-muted text-foreground')}>
                <Edit3 className="w-4 h-4" />Edit
              </button>
              {!approved && (
                <button onClick={approve} disabled={!!busy || state.stale || !state.prerequisitesMet} className={cn(pill, 'bg-primary text-primary-foreground shadow-md')}>
                  {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}Approve Strategy
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {(state.stale || !state.prerequisitesMet) && (
        <div className="flex items-start gap-2 text-sm text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <p>{!state.prerequisitesMet ? state.prerequisiteProblem : 'The Product Profile or Competitor Analysis changed after this strategy was generated. Regenerate it before approving.'}</p>
        </div>
      )}

      <Section title="Executive summary" grounding={s.executiveSummary.grounding}>
        <div className="space-y-3">
          <div><p className={label}>Positioning</p><Text value={s.executiveSummary.positioning} editing={editing} onChange={set(['executiveSummary', 'positioning'])} /></div>
          <div><p className={label}>Main promotion opportunity</p><Text value={s.executiveSummary.mainOpportunity} editing={editing} onChange={set(['executiveSummary', 'mainOpportunity'])} /></div>
          <div><p className={label}>Primary recommendation</p><Text value={s.executiveSummary.primaryRecommendation} editing={editing} onChange={set(['executiveSummary', 'primaryRecommendation'])} /></div>
        </div>
      </Section>

      <Section title="Audience & positioning" grounding={s.audience.grounding}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div><p className={label}>Primary audience</p><Text value={s.audience.primaryAudience} editing={editing} onChange={set(['audience', 'primaryAudience'])} /></div>
          <div><p className={label}>Value proposition</p><Text value={s.audience.valueProposition} editing={editing} onChange={set(['audience', 'valueProposition'])} /></div>
          <div><p className={label}>Problems & needs</p><Lines value={s.audience.problemsAndNeeds} editing={editing} onChange={set(['audience', 'problemsAndNeeds'])} /></div>
          <div><p className={label}>Differentiators</p><Lines value={s.audience.differentiators} editing={editing} onChange={set(['audience', 'differentiators'])} /></div>
          <div className="md:col-span-2"><p className={label}>Messaging direction</p><Text value={s.audience.messagingDirection} editing={editing} onChange={set(['audience', 'messagingDirection'])} /></div>
        </div>
      </Section>

      <Section title="Content pillars">
        <div className="space-y-4">
          {s.contentPillars.map((p, i) => (
            <div key={i} className="rounded-2xl border border-border/50 p-4 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                {editing ? <input value={p.name} onChange={(e) => set(['contentPillars', i, 'name'])(e.target.value)} className={cn(field, 'font-semibold')} />
                  : <p className="font-semibold text-foreground">{p.name}</p>}
                {!editing && <GroundingBadge g={p.grounding} />}
              </div>
              <Text value={p.purpose} editing={editing} onChange={set(['contentPillars', i, 'purpose'])} />
              <p className="text-xs text-muted-foreground">Relation to product: {editing ? '' : p.relationToProduct}</p>
              {editing && <Text value={p.relationToProduct} editing onChange={set(['contentPillars', i, 'relationToProduct'])} />}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Channel priorities">
        <div className="space-y-3">
          {s.channels.map((c, i) => (
            <div key={i} className="rounded-2xl border border-border/50 p-4 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-foreground">
                  {c.channel}
                  <span className={cn('ml-2 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border',
                    c.priority === 'primary' ? 'bg-primary/10 text-primary border-primary/20' : 'bg-muted text-muted-foreground border-border/50')}>{c.priority}</span>
                </p>
                {!editing && <GroundingBadge g={c.grounding} />}
              </div>
              <Text value={c.rationale} editing={editing} onChange={set(['channels', i, 'rationale'])} />
              {c.formats.length > 0 && !editing && <p className="text-xs text-muted-foreground">Formats: {c.formats.join(', ')}</p>}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Recommended content type" grounding={cd.grounding}>
        <div className="space-y-3">
          {editing ? (
            <select value={cd.primaryContentType} onChange={(e) => {
              set(['contentDirection', 'primaryContentType'])(e.target.value);
              set(['contentDirection', 'alternatives'])(cd.alternatives.filter((a) => a !== e.target.value));
            }} className={field}>
              {CONTENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          ) : (
            <p className="text-2xl font-bold text-foreground">{cd.primaryContentType}
              <span className="ml-3 text-xs font-medium text-primary align-middle">The ONE content type for the MVP</span></p>
          )}
          <Text value={cd.reason} editing={editing} onChange={set(['contentDirection', 'reason'])} />
          <p className="text-xs text-muted-foreground">Alternatives for later (not used by the MVP): {cd.alternatives.join(', ') || 'none'}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div><p className={label}>Subject areas</p><Lines value={cd.subjectAreas} editing={editing} onChange={set(['contentDirection', 'subjectAreas'])} /></div>
            <div><p className={label}>Messaging angles</p><Lines value={cd.messagingAngles} editing={editing} onChange={set(['contentDirection', 'messagingAngles'])} /></div>
          </div>
        </div>
      </Section>

      <Section title="Publishing cadence" grounding={s.cadence.grounding}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div><p className={label}>Frequency</p><Text value={s.cadence.frequency} editing={editing} onChange={set(['cadence', 'frequency'])} rows={1} /></div>
          <div><p className={label}>Planning horizon</p><Text value={s.cadence.planningHorizon} editing={editing} onChange={set(['cadence', 'planningHorizon'])} rows={1} /></div>
          <div className="md:col-span-2"><p className={label}>Rationale</p><Text value={s.cadence.rationale} editing={editing} onChange={set(['cadence', 'rationale'])} /></div>
        </div>
        {s.cadence.isHypothesis && <p className="text-xs text-amber-500">Recommendation to test — not proven by performance data.</p>}
      </Section>

      <Section title="Initial roadmap">
        <div className="space-y-3">
          {s.roadmap.map((r, i) => (
            <div key={i} className="rounded-2xl border border-border/50 p-4 grid grid-cols-1 md:grid-cols-[110px_1fr] gap-3">
              <div>
                <p className="font-semibold text-foreground">{r.timing}</p>
                <p className="text-xs text-muted-foreground">{r.channel} · {r.format}</p>
              </div>
              <div className="space-y-1.5">
                {editing ? <input value={r.topic} onChange={(e) => set(['roadmap', i, 'topic'])(e.target.value)} className={cn(field, 'font-medium')} />
                  : <p className="font-medium text-foreground">{r.topic}</p>}
                <Text value={r.objective} editing={editing} onChange={set(['roadmap', i, 'objective'])} rows={1} />
                <p className="text-xs text-muted-foreground">Audience: {r.audience}</p>
                <p className="text-xs text-muted-foreground">How to evaluate: {editing ? '' : r.successEvaluation}</p>
                {editing && <Text value={r.successEvaluation} editing onChange={set(['roadmap', i, 'successEvaluation'])} rows={1} />}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Measurement plan">
        <div className="space-y-3">
          {s.measurement.map((m, i) => (
            <div key={i} className="space-y-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-foreground">{m.indicator}</p>
                {!editing && <GroundingBadge g={m.grounding} />}
              </div>
              <Text value={m.whatToMeasure} editing={editing} onChange={set(['measurement', i, 'whatToMeasure'])} rows={1} />
              <p className="text-xs text-muted-foreground">{m.why}</p>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">No targets are set: there is no measured performance data yet.</p>
        </div>
      </Section>

      <div className="glass-panel p-6 rounded-3xl space-y-2 border-amber-500/20">
        <h4 className="text-sm font-semibold tracking-widest uppercase text-amber-500">Evidence, assumptions & limitations</h4>
        {s.limitations.map((l) => <p key={l} className="text-sm text-muted-foreground">{l}</p>)}
      </div>
    </div>
  );
}
