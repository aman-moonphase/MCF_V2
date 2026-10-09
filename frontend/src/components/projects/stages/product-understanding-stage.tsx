"use client"

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Project, WorkflowStage } from '@/types/project';
import { Product, ProductProfile, ProductService } from '@/lib/services/product.service';
import { BrainCircuit, CheckCircle2, Edit3, FileText, HelpCircle, Loader2, RefreshCw, Save, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => Promise<void> | void;
}

type FieldKey = Exclude<keyof ProductProfile, 'sourceReferences' | 'missingFields' | 'confidence'>;

// Profile layout. Backend field names are snake_case; profile keys arrive camelCased.
const SECTIONS: { title: string; fields: { key: FieldKey; label: string; list?: boolean }[] }[] = [
  {
    title: 'What it is',
    fields: [
      { key: 'name', label: 'Product name' },
      { key: 'description', label: 'Description' },
      { key: 'category', label: 'Category' },
      { key: 'valueProposition', label: 'Value proposition' },
      { key: 'positioning', label: 'Positioning' },
    ],
  },
  {
    title: 'Who it is for',
    fields: [
      { key: 'targetAudience', label: 'Target audience' },
      { key: 'primaryUsers', label: 'Primary users', list: true },
      { key: 'problemSolved', label: 'Problem it solves' },
      { key: 'useCases', label: 'Use cases', list: true },
    ],
  },
  {
    title: 'What it offers',
    fields: [
      { key: 'keyFeatures', label: 'Key features', list: true },
      { key: 'keyBenefits', label: 'Key benefits', list: true },
      { key: 'differentiators', label: 'Differentiators', list: true },
    ],
  },
  {
    title: 'Market',
    fields: [
      { key: 'marketGeography', label: 'Market / geography' },
      { key: 'businessModel', label: 'Business model / pricing' },
      { key: 'knownCompetitors', label: 'Known competitors (named in sources)', list: true },
      { key: 'websiteUrl', label: 'Website' },
      { key: 'constraints', label: 'Constraints', list: true },
    ],
  },
];

const ALL_FIELDS = SECTIONS.flatMap((s) => s.fields);
const toSnake = (key: string) => key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
const labelFor = (snakeField: string) => ALL_FIELDS.find((f) => toSnake(f.key) === snakeField)?.label || snakeField;

const STATUS: Record<string, { label: string; className: string }> = {
  needs_clarification: { label: 'Needs your input', className: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
  ready_for_review: { label: 'Ready for review', className: 'bg-primary/10 text-primary border-primary/20' },
  approved: { label: 'Approved', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
};

const LEARNING_STEPS = ['Reading your sources', 'Building the Product Profile', 'Checking what is missing'];

export function ProductUnderstandingStage({ project, activeStage, onComplete }: Props) {
  const [product, setProduct] = useState<Product | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLearning, setIsLearning] = useState(false);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isApproving, setIsApproving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    ProductService.getForProject(project.id)
      .then((p) => { if (!cancelled) setProduct(p); })
      .catch((e) => toast.error(`Could not load the Product Profile: ${e.message}`))
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [project.id]);

  useEffect(() => {
    if (!isLearning) return;
    const timer = setInterval(() => setStep((s) => Math.min(s + 1, LEARNING_STEPS.length - 1)), 900);
    return () => clearInterval(timer);
  }, [isLearning]);

  const learn = async () => {
    setIsLearning(true);
    setStep(0);
    try {
      const result = await ProductService.runUnderstanding(project.id);
      setProduct(result);
      toast.success(product ? 'Product Profile refreshed from your sources' : 'MCF has built a Product Profile');
    } catch (e) {
      toast.error(`Product Understanding failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsLearning(false);
    }
  };

  const submitAnswers = async () => {
    if (!product) return;
    const filled = Object.entries(answers).filter(([, a]) => a.trim()).map(([questionId, answer]) => ({ questionId, answer }));
    if (!filled.length) {
      toast.error('Answer at least one question first');
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await ProductService.submitAnswers(product.id, project.id, filled);
      setProduct(result);
      setAnswers({});
      toast.success('Answers added — Product Profile updated');
    } catch (e) {
      toast.error(`Could not submit answers: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const startEditing = () => {
    if (!product?.profile) return;
    const values: Record<string, string> = {};
    for (const f of ALL_FIELDS) {
      const v = product.profile[f.key];
      values[f.key] = Array.isArray(v) ? v.join('\n') : (v as string) || '';
    }
    setDraft(values);
    setIsEditing(true);
  };

  const saveEdits = async () => {
    if (!product?.profile) return;
    const changes: Record<string, unknown> = {};
    for (const f of ALL_FIELDS) {
      const current = product.profile[f.key];
      const next = f.list
        ? draft[f.key].split('\n').map((s) => s.trim()).filter(Boolean)
        : draft[f.key].trim() || null;
      if (JSON.stringify(next) !== JSON.stringify(f.list ? current || [] : current || null)) changes[f.key] = next;
    }
    if (!Object.keys(changes).length) {
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    try {
      setProduct(await ProductService.updateProfile(product.id, changes as Partial<ProductProfile>));
      setIsEditing(false);
      toast.success('Product Profile saved');
    } catch (e) {
      toast.error(`Could not save the profile: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSaving(false);
    }
  };

  const approve = async () => {
    if (!product) return;
    setIsApproving(true);
    try {
      const result = await ProductService.approve(product.id, project.id, product.profileVersion);
      setProduct(result);
      toast.success('Product Profile approved');
      if (activeStage.status !== 'Completed') await onComplete();
    } catch (e) {
      toast.error(`Could not approve: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!product?.profile) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <BrainCircuit className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Let MCF learn this product</h3>
          <p className="text-muted-foreground text-sm mb-8">
            MCF reads the sources you added, builds a structured Product Profile, and asks you only about what it
            could not find. No long onboarding form.
          </p>
          <button
            onClick={learn}
            disabled={isLearning}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLearning ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>{LEARNING_STEPS[step]}...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-5 h-5" />
                <span>Learn Product from Sources</span>
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  const profile = product.profile;
  const status = STATUS[product.understandingStatus] || STATUS.ready_for_review;
  const openQuestions = product.clarificationQuestions.filter((q) => q.status === 'open');
  const answered = product.clarificationQuestions.filter((q) => q.status === 'answered');
  const isApproved = product.understandingStatus === 'approved';
  const busy = isLearning || isSubmitting || isSaving || isApproving;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-xl font-bold text-foreground">{profile.name || product.name}</h3>
            <span className={cn('px-3 py-1 rounded-full text-xs font-medium border', status.className)}>{status.label}</span>
          </div>
          <p className="text-sm text-muted-foreground">
            What MCF learned from your sources · confidence {profile.confidence} · version {product.profileVersion}
          </p>
        </div>

        <div className="flex items-center gap-3 shrink-0 flex-wrap">
          {isEditing ? (
            <button
              onClick={saveEdits}
              disabled={busy}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium shadow-md disabled:opacity-50"
            >
              {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              <span>Save Profile</span>
            </button>
          ) : (
            <>
              <button
                onClick={learn}
                disabled={busy}
                className="inline-flex items-center gap-2 h-10 px-4 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 shadow-sm disabled:opacity-50"
              >
                {isLearning ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                <span>Re-analyze</span>
              </button>
              <button
                onClick={startEditing}
                disabled={busy}
                className="inline-flex items-center gap-2 h-10 px-4 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 shadow-sm disabled:opacity-50"
              >
                <Edit3 className="w-4 h-4" />
                <span>Edit</span>
              </button>
              {!isApproved && (
                <button
                  onClick={approve}
                  disabled={busy}
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md disabled:opacity-50"
                >
                  {isApproving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  <span>Approve Product Profile</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {openQuestions.length > 0 && !isEditing && (
        <div className="glass-panel p-6 rounded-3xl border-amber-500/20 bg-amber-500/5 space-y-5">
          <div>
            <h4 className="flex items-center gap-2 text-lg font-semibold text-foreground">
              <HelpCircle className="w-5 h-5 text-amber-500" />
              MCF needs a little more context
            </h4>
            <p className="text-sm text-muted-foreground">
              Your sources did not cover these. Answer what you can — you can also approve without answering.
            </p>
          </div>
          {openQuestions.map((q) => (
            <div key={q.id} className="space-y-2">
              <label className="text-sm font-medium text-foreground">{q.question}</label>
              <p className="text-xs text-muted-foreground">
                Why: {q.whyItMatters} · Improves: {q.fields.map(labelFor).join(', ')}
              </p>
              <textarea
                value={answers[q.id] || ''}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                placeholder="Your answer"
                className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[70px]"
              />
            </div>
          ))}
          <button
            onClick={submitAnswers}
            disabled={busy}
            className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-foreground text-background font-medium shadow-md disabled:opacity-50"
          >
            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            <span>{isSubmitting ? 'Updating profile...' : 'Submit answers'}</span>
          </button>
        </div>
      )}

      <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-8">
        {SECTIONS.map((section, index) => (
          <div key={section.title} className={cn('space-y-5', index > 0 && 'pt-6 border-t border-border/50')}>
            <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">{section.title}</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {section.fields.map((f) => {
                const value = profile[f.key];
                const items = Array.isArray(value) ? value : [];
                const missing = f.list ? items.length === 0 : !value;
                const edited = product.editedFields.includes(toSnake(f.key));
                return (
                  <div key={f.key} className={cn('space-y-2', (f.list || f.key === 'description') && 'md:col-span-2')}>
                    <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {f.label}
                      {edited && <span className="ml-2 normal-case tracking-normal text-primary">· edited by you</span>}
                    </label>
                    {isEditing ? (
                      <textarea
                        value={draft[f.key]}
                        onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                        placeholder={f.list ? 'One item per line' : ''}
                        className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[60px]"
                      />
                    ) : missing ? (
                      <p className="text-sm text-muted-foreground italic bg-muted/20 p-3 rounded-xl border border-dashed border-border/50">
                        Not found in your sources
                      </p>
                    ) : f.list ? (
                      <div className="flex flex-wrap gap-2">
                        {items.map((item) => (
                          <span key={item} className="text-sm bg-muted/30 px-3 py-1.5 rounded-lg border border-border/30">{item}</span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{value as string}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel p-6 rounded-3xl space-y-3">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Learned from</h4>
          {profile.sourceReferences.length ? (
            profile.sourceReferences.map((s) => (
              <div key={s.sourceId} className="flex items-center gap-2 text-sm text-foreground/90">
                <FileText className="w-4 h-4 text-muted-foreground" />
                <span>{s.name}</span>
                <span className="text-xs text-muted-foreground">({s.sourceType})</span>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">Project description</p>
          )}
        </div>
        <div className="glass-panel p-6 rounded-3xl space-y-3">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Still unknown</h4>
          {profile.missingFields.length ? (
            <div className="flex flex-wrap gap-2">
              {profile.missingFields.map((f) => (
                <span key={f} className="text-xs px-2.5 py-1 rounded-full bg-muted text-muted-foreground border border-border/50">{labelFor(f)}</span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing — the profile is complete.</p>
          )}
        </div>
      </div>

      {answered.length > 0 && (
        <div className="glass-panel p-6 rounded-3xl space-y-4">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Your answers</h4>
          {answered.map((q) => (
            <div key={q.id} className="text-sm">
              <p className="font-medium text-foreground">{q.question}</p>
              <p className="text-muted-foreground">{q.answer}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
