"use client"

import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { TopicAngle } from '@/types/workflow';
import { TopicAngleService } from '@/lib/services/topic-angle.service';
import { ProjectService } from '@/lib/project-service';
import { Project, WorkflowStage } from '@/types/project';
import { Target, Check, ArrowRight, Loader2, Lightbulb, Lock } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

export function TopicAngleStage({ project, activeStage, onComplete }: Props) {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [angles, setAngles] = useState<TopicAngle[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Prerequisites
  const contentStage = project.stages.find(s => s.type === 'content-selection');
  const platformStage = project.stages.find(s => s.type === 'platform-strategy');
  
  const opportunityId = contentStage?.data?.selectedId;
  const platformIds = platformStage?.data?.selectedIds || [];
  
  const isLocked = !opportunityId || platformIds.length === 0;

  useEffect(() => {
    if (activeStage.data?.angles) {
      setAngles(activeStage.data.angles);
      if (activeStage.data?.selectedId) {
        setSelectedId(activeStage.data.selectedId);
      }
    }
  }, [activeStage]);

  const handleAnalyze = async () => {
    if (isLocked) return;
    
    setIsAnalyzing(true);
    try {
      const results = await TopicAngleService.generateTopicAngles(project.id, opportunityId, platformIds);
      setAngles(results);

      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, angles: results }
      });
    } catch (e) {
      console.error(e);
      toast.error(`Topic & angle generation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSelect = async (id: string) => {
    setSelectedId(id);
    await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
      data: { ...activeStage.data, angles, selectedId: id }
    });
  };

  const handleConfirm = async () => {
    if (selectedId && !isApproving) {
      setIsApproving(true);
      try {
        await onComplete();
      } finally {
        setIsApproving(false);
      }
    }
  };

  if (isLocked) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2">
          <Lock className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-sm">
          You must complete the Content Selection and Platform Strategy stages before generating topic angles.
        </p>
      </div>
    );
  }

  if (angles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <Target className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Brainstorm Angles</h3>
          <p className="text-muted-foreground text-sm mb-8">
            The AI will generate multiple unique directions, hooks, and promises based on your selected content and target platforms.
          </p>
          <button 
            onClick={handleAnalyze}
            disabled={isAnalyzing}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAnalyzing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Generating Angles...</span>
              </>
            ) : (
              <>
                <Lightbulb className="w-5 h-5" />
                <span>Generate Angles</span>
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
          <h3 className="text-xl font-bold text-foreground">Select a Topic Angle</h3>
          <p className="text-sm text-muted-foreground">Choose the direction that best fits your goals.</p>
        </div>
        
        {selectedId && activeStage.status !== 'Completed' && (
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
                <span>Confirm Angle</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {angles.map((angle) => {
          const isSelected = selectedId === angle.id;
          return (
            <div 
              key={angle.id}
              onClick={() => activeStage.status !== 'Completed' && handleSelect(angle.id)}
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

              <div className="pr-10 mb-4">
                <span className="inline-block px-2 py-0.5 rounded-full bg-muted text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  {angle.angle}
                </span>
                <h4 className="text-lg font-bold text-foreground leading-tight mb-2">"{angle.title}"</h4>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  <span className="font-semibold text-foreground/80">Hook:</span> {angle.hook}
                </p>
              </div>

              <div className="mt-auto space-y-4 pt-4 border-t border-border/50">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-primary mb-1 block">Primary Target Persona</span>
                    <span className="text-xs text-foreground/90">{angle.targetAudience}</span>
                  </div>
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-primary mb-1 block">Core Promise</span>
                    <span className="text-xs text-foreground/90">{angle.corePromise}</span>
                  </div>
                  <div className="sm:col-span-2">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-primary mb-1 block">Differentiation</span>
                    <span className="text-xs text-foreground/90">{angle.differentiation}</span>
                  </div>
                </div>

                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 block">Supporting Points</span>
                  <ul className="space-y-1.5">
                    {angle.supportingPoints.map((point, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary/50 mt-1 shrink-0" />
                        <span>{point}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
