"use client"

import React, { useState, useEffect } from 'react';
import { Project, WorkflowStage } from '@/types/project';
import { Bot, RefreshCw, CheckCircle2, ChevronRight, FileType, Check, AlertCircle } from 'lucide-react';
import { ContentTypeService } from '@/lib/services/content-type.service';
import { ProjectService } from '@/lib/project-service';

interface ContentTypeStageProps {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

// The one format the product workflow can generate in this version (backend: app/ai/platform_policy.py).
const MVP_CONTENT_TYPE = 'Social Post';

export function ContentTypeStage({ project, activeStage, onComplete }: ContentTypeStageProps) {
  // Product-workflow projects take the content type from the approved Promotion Strategy (no source analysis).
  const productWorkflow = project.stages?.some((s) => s.type === 'product-understanding') ?? false;
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [data, setData] = useState<any>(activeStage.data || null);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    if (activeStage.data && Object.keys(activeStage.data).length > 0) {
      setData(activeStage.data);
    }
  }, [activeStage.data]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    setError(null);
    try {
      const response = await ContentTypeService.generate(project.id);
      setData(response);
      
      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        status: 'Needs Review',
        data: response
      });
    } catch (e: any) {
      setError(e.message || 'Failed to generate content type');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async (type: string) => {
    if (isApproving) return;
    setIsApproving(true);
    setError(null);
    try {
      const updated = await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        status: 'Completed',
        data: { ...data, approved_type: type }
      });
      if (!updated) return;  // the save failed (e.g. strategy not approved); the error was already shown

      const saved = updated.stages.find((s) => s.id === activeStage.id);
      setData(saved?.data || { ...data, approved_type: type });
      await onComplete();
    } catch (e: any) {
      setError(e.message || 'Failed to approve content type');
    } finally {
      setIsApproving(false);
    }
  };

  const hasData = data && data.recommendation;

  if (isGenerating) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[40vh] space-y-6">
        <div className="relative">
          <div className="absolute inset-0 bg-primary/20 rounded-full blur-xl animate-pulse" />
          <div className="relative bg-background p-4 rounded-full border border-border shadow-2xl">
            <RefreshCw className="w-8 h-8 text-primary animate-spin" />
          </div>
        </div>
        <div className="text-center space-y-2">
          <h3 className="text-xl font-semibold text-foreground">{productWorkflow ? 'Loading your Promotion Strategy' : 'Analyzing Source Material'}</h3>
          <p className="text-muted-foreground">{productWorkflow ? 'Reading the content type from your approved strategy...' : 'Determining the best content type for your project...'}</p>
        </div>
      </div>
    );
  }

  if (!hasData) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[40vh] space-y-8">
        <div className="text-center space-y-4 max-w-md">
          <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-6">
            <FileType className="w-8 h-8" />
          </div>
          <h3 className="text-2xl font-bold text-foreground tracking-tight">{productWorkflow ? 'Confirm Content Type' : 'Determine Content Type'}</h3>
          <p className="text-muted-foreground text-sm leading-relaxed">
            {productWorkflow
              ? 'Load the content type from your approved Promotion Strategy. This version generates one format: a LinkedIn Social Post.'
              : 'Let AI analyze your source material to recommend the best content format (e.g., Video, Carousel, Article) before generating content.'}
          </p>
        </div>
        
        {error && (
          <div className="flex items-center gap-2 text-destructive bg-destructive/10 px-4 py-3 rounded-lg text-sm w-full max-w-md">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        <button
          onClick={handleGenerate}
          className="inline-flex items-center gap-2 px-8 py-3.5 rounded-full bg-primary text-primary-foreground font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-xl shadow-primary/25"
        >
          <Bot className="w-5 h-5" />
          <span>{productWorkflow ? 'Load from Promotion Strategy' : 'Analyze Source Material'}</span>
        </button>
      </div>
    );
  }

  const rec = data.recommendation;
  const recommendedType = rec.recommendedType || rec.recommended_type;
  const alternatives = rec.alternatives || [];
  const sourceSignals = rec.sourceSignals || rec.source_signals || [];
  const approvedType = data.approved_type || data.approvedType;
  const fromStrategy = Boolean(data.fromStrategy || data.from_strategy);
  const overridesStrategy = Boolean(data.overridesStrategy || data.overrides_strategy);
  // Product-workflow projects: only some types can go through Generate Content in this version.
  const generationSupported = data.generationSupported ?? data.generation_supported;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-2xl font-bold text-foreground">Recommended Format</h3>
          <p className="text-muted-foreground mt-1">
            {fromStrategy
              ? `From your approved Promotion Strategy · this version generates LinkedIn ${MVP_CONTENT_TYPE}s only`
              : 'Based on the source material'}
          </p>
        </div>
        
        <button
          onClick={handleGenerate}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground text-sm font-medium transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          {fromStrategy ? 'Reload from strategy' : 'Regenerate'}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-destructive bg-destructive/10 px-4 py-3 rounded-lg text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <div className="grid gap-6">
        <div 
          className={`glass-panel p-6 rounded-2xl border-2 transition-all cursor-pointer hover:border-primary/50 relative overflow-hidden group ${
            approvedType === recommendedType ? 'border-primary bg-primary/5' : 'border-border'
          } ${isApproving ? 'opacity-50 pointer-events-none' : ''}`}
          onClick={() => handleApprove(recommendedType)}
        >
          <div className="absolute right-6 top-6 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="px-4 py-1.5 rounded-full bg-primary text-primary-foreground text-xs font-semibold">
              Select
            </div>
          </div>
          
          {approvedType === recommendedType && (
            <div className="absolute right-6 top-6">
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary text-primary-foreground text-xs font-semibold">
                <Check className="w-3.5 h-3.5" />
                Approved
              </div>
            </div>
          )}

          <div className="flex gap-4">
            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
              <FileType className="w-6 h-6 text-primary" />
            </div>
            <div className="space-y-3">
              <div>
                <h4 className="text-lg font-bold text-foreground group-hover:text-primary transition-colors">
                  {recommendedType}
                </h4>
                <div className="text-sm font-medium text-primary mt-1">
                  {fromStrategy ? 'Recommended by your Promotion Strategy' : 'Top Recommendation'}
                </div>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {rec.reasoning}
              </p>
              {sourceSignals && sourceSignals.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {sourceSignals.map((signal: string, i: number) => (
                    <span key={i} className="px-2.5 py-1 rounded-md bg-muted text-xs font-medium text-muted-foreground">
                      {signal}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-4 pt-4 border-t border-border/50">
          <h4 className="text-sm font-semibold text-foreground">{productWorkflow ? 'Other formats (not generated in this version)' : 'Other formats (Manual Override)'}</h4>
          {approvedType && overridesStrategy && (
            <p className="text-xs text-amber-500">
              You chose {approvedType} instead of the strategy&apos;s recommendation. All downstream content will be {approvedType}.
            </p>
          )}
          {approvedType && generationSupported === false && (
            <p className="text-xs text-amber-500">
              Generate Content currently produces LinkedIn Social Posts only. {approvedType} is saved for later, but generation stays
              blocked until you choose Social Post.
            </p>
          )}
          <div className="grid sm:grid-cols-2 gap-4">
            {["Video", "Image", "Carousel", "Article", "Newsletter", "Social Post"]
              .filter(t => t !== recommendedType)
              .map((alt: string, i: number) => {
              const unavailable = productWorkflow && alt !== MVP_CONTENT_TYPE;
              return (
              <div
                key={i}
                aria-disabled={unavailable}
                title={unavailable ? `Not generated in this version — only LinkedIn ${MVP_CONTENT_TYPE}s are` : undefined}
                className={`p-4 rounded-xl border transition-all relative overflow-hidden group ${
                  unavailable ? 'border-border bg-card opacity-50 cursor-not-allowed'
                    : `cursor-pointer hover:border-primary/50 ${approvedType === alt ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-muted/50'}`
                } ${isApproving ? 'opacity-50 pointer-events-none' : ''}`}
                onClick={() => { if (!unavailable) handleApprove(alt); }}
              >
                {approvedType === alt && (
                  <div className="absolute right-3 top-3">
                    <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                      <Check className="w-3 h-3 text-primary-foreground" />
                    </div>
                  </div>
                )}
                <h5 className={`font-semibold text-foreground transition-colors ${unavailable ? '' : 'group-hover:text-primary'}`}>
                  {alt}
                </h5>
                {unavailable && <p className="text-xs text-muted-foreground mt-1">Later — not generated in this version</p>}
              </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
