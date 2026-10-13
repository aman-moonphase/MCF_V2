"use client";

import React, { useState } from 'react';
import { toast } from 'sonner';
import {
  GeneratedDraft,
  GenerationService,
  GenerationState,
} from '@/lib/services/generation.service';
import {
  AlertCircle,
  Eye,
  ImageIcon,
  Layers,
  Loader2,
  Lock,
  Palette,
  RefreshCw,
  Save,
  Sparkles,
  ThumbsUp,
  MessageSquare,
  Repeat2,
  Send,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  projectId: string;
  draft: GeneratedDraft;
  approved?: boolean;
  readOnly?: boolean;
  productName?: string;
  onStateChange?: (state: GenerationState) => void;
}

const pill =
  'inline-flex items-center gap-2 h-9 px-4 rounded-full text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed';
const field =
  'w-full text-xs bg-background border border-border/50 rounded-xl p-2.5 focus:outline-none focus:ring-1 focus:ring-primary';
const label = 'text-[11px] font-semibold uppercase tracking-wider text-muted-foreground';

const STYLES = [
  { id: 'professional', label: 'Professional (Slate / Sky)' },
  { id: 'minimalist', label: 'Minimalist (Monochrome)' },
  { id: 'bold', label: 'Bold (Deep Violet / Rose)' },
  { id: 'editorial', label: 'Editorial (Teal / Emerald)' },
];

const RATIOS = [
  { id: '16:9', label: '16:9 Landscape' },
  { id: '1:1', label: '1:1 Square' },
];

const PROVIDERS = [
  { id: 'demo', label: 'Demo Mode (default)' },
  { id: 'pollinations_legacy', label: 'Pollinations Legacy (No-Key, Best Effort)' },
  { id: 'pollinations', label: 'Pollinations AI (authenticated)' },
];

export function CreativeImagePreview({
  projectId,
  draft,
  approved = false,
  readOnly = false,
  productName,
  onStateChange,
}: Props) {
  const image = draft.image;
  const [busy, setBusy] = useState<'generate' | 'save' | 'delete' | null>(null);
  const [customPrompt, setCustomPrompt] = useState<string | null>(null);
  const [customAltText, setCustomAltText] = useState<string | null>(null);
  const [customStyle, setCustomStyle] = useState<string | null>(null);
  const [customAspectRatio, setCustomAspectRatio] = useState<string | null>(null);
  const [customProvider, setCustomProvider] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);

  const prompt = customPrompt !== null ? customPrompt : (image?.prompt || '');
  const altText = customAltText !== null ? customAltText : (image?.altText || '');
  const style = customStyle !== null ? customStyle : (image?.style || 'professional');
  const aspectRatio = customAspectRatio !== null ? customAspectRatio : (image?.aspectRatio || '16:9');
  const provider = customProvider !== null ? customProvider : (image?.provider || 'demo');

  const hasDirtyMetadata =
    Boolean(image &&
      ((customPrompt !== null && customPrompt !== image.prompt) ||
        (customAltText !== null && customAltText !== image.altText) ||
        (customStyle !== null && customStyle !== image.style) ||
        (customAspectRatio !== null && customAspectRatio !== image.aspectRatio)));

  const handleGenerate = async () => {
    setBusy('generate');
    try {
      // Send customPrompt only if explicitly provided by user.
      // When null or blank, backend auto-crafts a pristine, text-free background prompt.
      const activePrompt = (customPrompt !== null && customPrompt.trim()) ? customPrompt.trim() : null;
      const activeAlt = (customAltText !== null && customAltText.trim()) ? customAltText.trim() : null;

      const next = await GenerationService.generateImage(projectId, {
        prompt: activePrompt,
        aspectRatio,
        style,
        altText: activeAlt,
        provider,
      });
      setCustomPrompt(null);
      setCustomAltText(null);
      setCustomStyle(null);
      setCustomAspectRatio(null);
      setCustomProvider(null);
      onStateChange?.(next);
      toast.success(image ? 'Creative image regenerated.' : 'Creative image generated.');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Image generation failed: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSaveMetadata = async () => {
    if (!image) return;
    setBusy('save');
    try {
      const next = await GenerationService.updateImage(projectId, {
        prompt: prompt.trim() || null,
        altText: altText.trim() || null,
        style,
        aspectRatio,
      });
      setCustomPrompt(null);
      setCustomAltText(null);
      setCustomStyle(null);
      setCustomAspectRatio(null);
      onStateChange?.(next);
      toast.success('Image prompt and accessibility metadata saved.');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Failed to save image metadata: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    setBusy('delete');
    try {
      const next = await GenerationService.deleteImage(projectId);
      setCustomPrompt(null);
      setCustomAltText(null);
      setCustomStyle(null);
      setCustomAspectRatio(null);
      onStateChange?.(next);
      toast.success('Creative image removed.');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Failed to remove image: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const brand = productName || 'Product';
  const post = draft.content;

  return (
    <div className="space-y-4">
      {/* Visual Header / Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-primary" />
          <h4 className="text-sm font-semibold tracking-wide uppercase text-foreground">
            Creative Asset &amp; Social Feed Preview
          </h4>
          {image && (
            <span
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-medium border',
                image.versionMatchesPost
                  ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-500 border-amber-500/20'
              )}
            >
              {image.versionMatchesPost
                ? `Asset v${image.contentVersion} · Current`
                : `Asset v${image.contentVersion} · Post is v${draft.version}`}
            </span>
          )}
        </div>

        {approved ? (
          <span className="px-2.5 py-1 rounded-full text-xs font-medium border bg-muted/60 text-muted-foreground flex items-center gap-1.5">
            <Lock className="w-3 h-3" />
            Approved Post · Asset Locked
          </span>
        ) : !readOnly && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowConfig(!showConfig)}
              className={cn(pill, 'bg-muted text-foreground hover:bg-muted/80')}
            >
              <Palette className="w-3.5 h-3.5" />
              {showConfig ? 'Hide Controls' : 'Custom Prompt & Style'}
            </button>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={!!busy}
              className={cn(
                pill,
                image
                  ? 'bg-muted text-foreground hover:bg-muted/80'
                  : 'bg-primary text-primary-foreground shadow-md'
              )}
            >
              {busy === 'generate' ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Generating Asset…
                </>
              ) : image ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5" />
                  Regenerate Image
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" />
                  Generate Creative Image
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* Version mismatch notice */}
      {image && !image.versionMatchesPost && !readOnly && !approved && (
        <div className="flex items-center gap-2 text-xs text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <p>
            This creative image was generated for post version {image.contentVersion}. The post was
            subsequently updated to version {draft.version}. You can keep this image or click{' '}
            <strong>Regenerate Image</strong> to update it for version {draft.version}.
          </p>
        </div>
      )}

      {/* Optional Customization Panel */}
      {showConfig && !readOnly && !approved && (
        <div className="rounded-2xl border border-border/50 bg-muted/20 p-4 space-y-3 animate-in fade-in duration-300">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className={label}>AI Image Provider</label>
              <select
                value={provider}
                onChange={(e) => setCustomProvider(e.target.value)}
                disabled={!!busy}
                className={field}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              {provider === 'pollinations_legacy' && (
                <p className="text-[10px] text-amber-500/90 leading-tight pt-0.5">
                  Best-effort unauthenticated community endpoint (image.pollinations.ai). No SLA, uptime, or zero-cost guarantee.
                </p>
              )}
            </div>
            <div className="space-y-1">
              <label className={label}>Visual Style</label>
              <select
                value={style}
                onChange={(e) => setCustomStyle(e.target.value)}
                disabled={!!busy}
                className={field}
              >
                {STYLES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className={label}>Aspect Ratio</label>
              <select
                value={aspectRatio}
                onChange={(e) => setCustomAspectRatio(e.target.value)}
                disabled={!!busy}
                className={field}
              >
                {RATIOS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className={label}>Creative Prompt (optional override)</label>
              {customPrompt !== null && (
                <button
                  type="button"
                  onClick={() => setCustomPrompt(null)}
                  className="text-[11px] text-primary hover:underline cursor-pointer"
                >
                  Reset to Auto-Crafted Prompt
                </button>
              )}
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              rows={2}
              disabled={!!busy}
              placeholder="Leave empty or reset to auto-craft a pristine text-free scene visual"
              className={field}
            />
            <p className="text-[10px] text-muted-foreground">
              {customPrompt !== null && customPrompt.trim()
                ? "Custom prompt override active. Will be used on next generation."
                : "Automated mode active: Regenerating crafts a fresh, text-free background prompt without branding or copy."}
            </p>
          </div>

          <div className="space-y-1">
            <label className={label}>Alt Text (Accessibility)</label>
            <input
              type="text"
              value={altText}
              onChange={(e) => setCustomAltText(e.target.value)}
              disabled={!!busy}
              placeholder="e.g. Promotional graphic for FocusFlow featuring an organized lesson schedule"
              className={field}
            />
          </div>

          {image && (
            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-2">
                {hasDirtyMetadata && (
                  <button
                    type="button"
                    onClick={handleSaveMetadata}
                    disabled={!!busy}
                    className={cn(pill, 'bg-primary text-primary-foreground')}
                  >
                    {busy === 'save' ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5" />
                    )}
                    Save Metadata
                  </button>
                )}
                <span className="text-[11px] text-muted-foreground">
                  Provider: {image.provider} ({image.isDemo ? 'Demo Mode' : 'Real'})
                </span>
              </div>

              <button
                type="button"
                onClick={handleDelete}
                disabled={!!busy}
                className={cn(pill, 'bg-destructive/10 text-destructive hover:bg-destructive/20')}
              >
                {busy === 'delete' ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Trash2 className="w-3.5 h-3.5" />
                )}
                Remove Asset
              </button>
            </div>
          )}
        </div>
      )}

      {/* Authentic LinkedIn Feed Mockup Preview Card */}
      <div className="rounded-2xl border border-border/60 bg-card overflow-hidden shadow-sm transition-all hover:border-border">
        {/* LinkedIn Author Header */}
        <div className="p-4 flex items-center justify-between border-b border-border/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-primary to-sky-400 flex items-center justify-center text-primary-foreground font-bold text-sm shadow-inner">
              {brand.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground hover:underline cursor-pointer">
                  {brand}
                </span>
                <span className="text-xs text-muted-foreground">· 1st</span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-tight">
                {brand} · {draft.content.pillar}
              </p>
              <p className="text-[10px] text-muted-foreground/80 mt-0.5">Now · Edited · 🌐</p>
            </div>
          </div>

          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <span className="px-2 py-0.5 rounded bg-muted/60 text-[10px] font-mono">LinkedIn</span>
            {approved && (
              <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-500 text-[10px] font-semibold">
                Approved
              </span>
            )}
          </div>
        </div>

        {/* Post Text Content */}
        <div className="p-4 space-y-3 text-sm text-foreground/90 whitespace-pre-wrap leading-relaxed">
          <p className="font-semibold text-foreground">{post.hook}</p>
          <p>{post.body}</p>
          <p className="text-primary font-medium">{post.cta}</p>
          {post.hashtags && post.hashtags.length > 0 && (
            <p className="text-sky-500 font-medium">{post.hashtags.join(' ')}</p>
          )}
        </div>

        {/* Creative Image Asset Display */}
        {image ? (
          <div className="relative border-t border-border/40 bg-muted/10 group">
            <div
              className={cn(
                'relative w-full flex items-center justify-center overflow-hidden bg-black/5 dark:bg-black/30',
                image.aspectRatio === '1:1' ? 'aspect-square max-w-[540px] mx-auto' : 'aspect-video'
              )}
              style={{
                aspectRatio: image.aspectRatio === '1:1' ? '1 / 1' : '16 / 9',
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={image.imageUrl}
                alt={image.altText || post.hook}
                className={cn(
                  'w-full h-full select-none transition-transform duration-500 group-hover:scale-[1.01]',
                  image.isDemo ? 'object-contain' : 'object-cover'
                )}
              />

              {/* Raw Visual Inspection Mode Indicator */}
              {!image.isDemo && !showOverlay && (
                <div className="absolute top-3 right-3 px-2.5 py-1 rounded-full bg-black/75 backdrop-blur-md text-[11px] font-medium text-amber-300 border border-amber-400/30 flex items-center gap-1.5 shadow-sm pointer-events-none select-none">
                  <Eye className="w-3.5 h-3.5 text-amber-400" />
                  <span>Raw Source Visual · Overlay Hidden</span>
                </div>
              )}

              {/* Exact StudyNest Branding & Headline Overlay for AI-Generated Images */}
              {!image.isDemo && showOverlay && (
                <div className="absolute inset-0 flex flex-col justify-between p-6 sm:p-8 bg-gradient-to-t from-black/85 via-black/40 to-black/25 pointer-events-none select-none text-white">
                  {/* Brand & Pillar Pill */}
                  <div className="flex items-center justify-between">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-black/55 backdrop-blur-md border border-white/20 text-xs font-semibold shadow-sm">
                      <span className="text-sky-300 uppercase text-[11px] font-bold tracking-wider">
                        {draft.content.pillar || 'Insight'}
                      </span>
                      <span className="text-white/40">·</span>
                      <span className="text-white font-medium">{brand}</span>
                    </div>
                    <span className="text-[10px] uppercase font-mono tracking-widest text-white/70 bg-black/45 backdrop-blur-md px-2 py-0.5 rounded border border-white/10">
                      {image.aspectRatio} · {image.style}
                    </span>
                  </div>

                  {/* Headline / Hook & Accent Bar */}
                  <div className="space-y-3 max-w-xl">
                    <h3
                      className={cn(
                        'font-extrabold tracking-tight text-white drop-shadow-md leading-tight',
                        image.aspectRatio === '1:1'
                          ? 'text-xl sm:text-2xl lg:text-3xl'
                          : 'text-lg sm:text-2xl lg:text-3xl'
                      )}
                    >
                      {post.hook}
                    </h3>
                    <div className="w-16 h-1 rounded-full bg-gradient-to-r from-sky-400 to-indigo-400" />
                    <p className="text-[11px] sm:text-xs text-white/80 font-medium tracking-wide">
                      MCF Creative Asset · {brand} LinkedIn Social Post
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Visual Metadata Overlay Footer */}
            <div className="p-2.5 px-4 bg-background/90 backdrop-blur-md border-t border-border/40 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span className="truncate max-w-[45%]" title={`Alt Text: ${image.altText}\nPrompt: ${image.prompt}`}>
                <strong>Alt:</strong> {image.altText}
              </span>
              <div className="flex items-center gap-2">
                {!image.isDemo && (
                  <button
                    type="button"
                    onClick={() => setShowOverlay(!showOverlay)}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer border',
                      showOverlay
                        ? 'bg-primary/10 text-primary border-primary/20 hover:bg-primary/20'
                        : 'bg-amber-500/10 text-amber-500 border-amber-500/20 hover:bg-amber-500/20'
                    )}
                    title={showOverlay ? 'Switch to Raw Source Visual' : 'Switch to Branded Typography Composition'}
                  >
                    <Layers className="w-3 h-3" />
                    {showOverlay ? 'Branded Overlay Active' : 'Raw Visual Mode'}
                  </button>
                )}
                <span className="shrink-0 text-[10px] font-mono uppercase bg-muted px-2 py-0.5 rounded" title={`Prompt: ${image.prompt}`}>
                  {image.provider} · {image.style} · {image.aspectRatio}
                </span>
              </div>
            </div>
          </div>
        ) : approved ? (
          <div className="p-4 border-t border-border/30 bg-muted/5 text-center text-xs text-muted-foreground">
            No creative image was attached to this approved post version.
          </div>
        ) : (
          !readOnly && (
            <div className="p-6 border-t border-dashed border-border/60 bg-muted/5 flex flex-col items-center justify-center text-center space-y-2">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-1">
                <ImageIcon className="w-5 h-5" />
              </div>
              <p className="text-xs font-semibold text-foreground">
                No visual creative asset attached yet
              </p>
              <p className="text-[11px] text-muted-foreground max-w-sm">
                Adding a branded social image increases LinkedIn post engagement. Generate a clean,
                grounded graphic tailored to this post.
              </p>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!!busy}
                className={cn(pill, 'bg-primary text-primary-foreground shadow-sm mt-2')}
              >
                {busy === 'generate' ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Generating Asset…
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    Generate Creative Visual
                  </>
                )}
              </button>
            </div>
          )
        )}

        {/* Mock LinkedIn Interaction Bar */}
        <div className="p-2 px-4 border-t border-border/40 flex items-center justify-between text-muted-foreground text-xs select-none">
          <div className="flex items-center gap-5">
            <span className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors cursor-pointer">
              <ThumbsUp className="w-3.5 h-3.5" /> Like
            </span>
            <span className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors cursor-pointer">
              <MessageSquare className="w-3.5 h-3.5" /> Comment
            </span>
            <span className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors cursor-pointer">
              <Repeat2 className="w-3.5 h-3.5" /> Repost
            </span>
            <span className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors cursor-pointer">
              <Send className="w-3.5 h-3.5" /> Send
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
