"use client"

import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { PlatformRecommendation } from '@/types/workflow';
import { PlatformStrategyService } from '@/lib/services/platform-strategy.service';
import { ProjectService } from '@/lib/project-service';
import { Project, WorkflowStage } from '@/types/project';
import { Share2, Check, ArrowRight, Loader2, MessageSquare, Video, Mail, FileText, Camera } from 'lucide-react';
import { cn } from '@/lib/utils';

const LinkedinIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
  </svg>
);

const XIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z" />
  </svg>
);

const YoutubeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
  </svg>
);

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

export function PlatformStrategyStage({ project, activeStage, onComplete }: Props) {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [recommendations, setRecommendations] = useState<PlatformRecommendation[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // Find the selected content opportunity ID from the previous stage
  const prevStage = project.stages.find(s => s.type === 'content-selection');
  const opportunityId = prevStage?.data?.selectedId;

  useEffect(() => {
    if (activeStage.data?.recommendations) {
      setRecommendations(activeStage.data.recommendations);
      if (activeStage.data?.selectedIds) {
        setSelectedIds(activeStage.data.selectedIds);
      }
    }
  }, [activeStage]);

  const handleAnalyze = async () => {
    if (!opportunityId) return;
    
    setIsAnalyzing(true);
    try {
      const results = await PlatformStrategyService.analyzePlatforms(project.id, opportunityId);
      setRecommendations(results);
      
      // Auto-select recommended platforms by default
      const defaultSelected = results.filter(r => r.priority === 'Recommended').map(r => r.id);
      setSelectedIds(defaultSelected);

      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, recommendations: results, selectedIds: defaultSelected }
      });
    } catch (e) {
      console.error(e);
      toast.error(`Platform strategy generation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const toggleSelection = async (id: string) => {
    const newSelected = selectedIds.includes(id) 
      ? selectedIds.filter(i => i !== id)
      : [...selectedIds, id];
    
    setSelectedIds(newSelected);
    
    await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
      data: { ...activeStage.data, recommendations, selectedIds: newSelected }
    });
  };

  const handleConfirm = async () => {
    if (selectedIds.length > 0 && !isApproving) {
      setIsApproving(true);
      try {
        await onComplete();
      } finally {
        setIsApproving(false);
      }
    }
  };

  const getPlatformIcon = (platform: string) => {
    switch (platform) {
      case 'LinkedIn': return <LinkedinIcon className="w-5 h-5" />;
      case 'Twitter/X':
      case 'Twitter': return <XIcon className="w-4 h-4" />;
      case 'YouTube': return <YoutubeIcon className="w-5 h-5" />;
      case 'Newsletter': return <Mail className="w-5 h-5" />;
      case 'Blog': return <FileText className="w-5 h-5" />;
      case 'Instagram': return <Camera className="w-5 h-5" />;
      default: return <Share2 className="w-5 h-5" />;
    }
  };

  if (!opportunityId) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
          <Share2 className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-xl font-semibold mb-2">Stage Locked</h3>
        <p className="text-muted-foreground">You must complete the Content Selection stage first.</p>
      </div>
    );
  }

  if (recommendations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <Share2 className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Platform Strategy</h3>
          <p className="text-muted-foreground text-sm mb-8">
            Based on your selected content, the AI will recommend the best platforms and formats for maximum engagement.
          </p>
          <button 
            onClick={handleAnalyze}
            disabled={isAnalyzing}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAnalyzing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Analyzing Platforms...</span>
              </>
            ) : (
              <>
                <Share2 className="w-5 h-5" />
                <span>Generate Strategy</span>
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-xl font-bold text-foreground">Select Target Platforms</h3>
          <p className="text-sm text-muted-foreground">Choose one or more platforms to adapt this content for.</p>
        </div>
        
        {selectedIds.length > 0 && activeStage.status !== 'Completed' && (
          <button 
            onClick={handleConfirm}
            disabled={isApproving}
            className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isApproving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Confirming...</span>
              </>
            ) : (
              <>
                <span>Confirm Strategy</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {recommendations.map((rec) => {
          const isSelected = selectedIds.includes(rec.id);
          return (
            <div 
              key={rec.id}
              onClick={() => activeStage.status !== 'Completed' && toggleSelection(rec.id)}
              className={cn(
                "relative flex flex-col p-6 rounded-2xl border transition-all duration-300 text-left cursor-pointer overflow-hidden group",
                isSelected 
                  ? "bg-primary/5 border-primary/50 shadow-[0_0_15px_rgba(99,102,241,0.1)] ring-1 ring-primary/20" 
                  : "glass-panel hover:border-primary/30 hover:bg-muted/50",
                activeStage.status === 'Completed' && !isSelected && "opacity-50 grayscale"
              )}
            >
              <div className={cn(
                "absolute top-5 right-5 w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors",
                isSelected ? "bg-primary border-primary text-background" : "border-muted-foreground/30 text-transparent"
              )}>
                <Check className="w-3.5 h-3.5" />
              </div>

              <div className="flex items-center gap-3 mb-4">
                <div className={cn(
                  "p-2.5 rounded-xl",
                  isSelected ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground group-hover:text-foreground group-hover:bg-muted/80"
                )}>
                  {getPlatformIcon(rec.platform)}
                </div>
                <div>
                  <h4 className="text-lg font-bold text-foreground leading-tight">{rec.platform}</h4>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={cn(
                      "text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full",
                      rec.priority === 'Recommended' ? "bg-emerald-500/10 text-emerald-500" : "bg-muted text-muted-foreground"
                    )}>
                      {rec.priority}
                    </span>
                    <span className="text-xs text-muted-foreground font-medium">Match: {rec.suitability}%</span>
                  </div>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-sm text-foreground/90 leading-relaxed">{rec.reasoning}</p>
              </div>

              <div className="mt-auto space-y-3 pt-4 border-t border-border/50">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">Format</span>
                    <span className="text-xs text-foreground font-medium">{rec.recommendedFormat}</span>
                  </div>
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">Tone</span>
                    <span className="text-xs text-foreground font-medium">{rec.tone}</span>
                  </div>
                </div>
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">Audience</span>
                  <span className="text-xs text-foreground font-medium">{rec.audience}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
