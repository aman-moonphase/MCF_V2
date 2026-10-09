"use client"

import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { ContentStrategy } from '@/types/workflow';
import { ContentStrategyService } from '@/lib/services/content-strategy.service';
import { ProjectService } from '@/lib/project-service';
import { Project, WorkflowStage } from '@/types/project';
import { Network, Check, ArrowRight, Loader2, Save, Lock, Edit3 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

export function ContentStrategyStage({ project, activeStage, onComplete }: Props) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [strategy, setStrategy] = useState<ContentStrategy | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedStrategy, setEditedStrategy] = useState<ContentStrategy | null>(null);

  // Prerequisites
  const contentStage = project.stages.find(s => s.type === 'content-selection');
  const platformStage = project.stages.find(s => s.type === 'platform-strategy');
  const topicStage = project.stages.find(s => s.type === 'topic-angle');
  
  const opportunityId = contentStage?.data?.selectedId;
  const platformIds = platformStage?.data?.selectedIds || [];
  const angleId = topicStage?.data?.selectedId;
  
  const isLocked = !opportunityId || platformIds.length === 0 || !angleId;

  useEffect(() => {
    if (activeStage.data?.strategy) {
      setStrategy(activeStage.data.strategy);
      setEditedStrategy(activeStage.data.strategy);
    }
  }, [activeStage]);

  const handleGenerate = async () => {
    if (isLocked) return;
    
    setIsGenerating(true);
    try {
      const result = await ContentStrategyService.generateStrategy(project.id, opportunityId, platformIds, angleId);
      setStrategy(result);
      setEditedStrategy(result);
      
      // Auto-save the initial generation
      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, strategy: result }
      });
    } catch (e) {
      console.error(e);
      toast.error(`Content strategy generation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSaveAndContinue = async () => {
    if (!editedStrategy || isApproving) return;
    
    setIsApproving(true);
    try {
      // Save the edited strategy
      const saved = await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, strategy: editedStrategy }
      });
      if (!saved) return;
      toast.success('Content strategy saved');
      
      setIsEditing(false);
      setStrategy(editedStrategy);
      await onComplete();
    } finally {
      setIsApproving(false);
    }
  };

  const handleFieldChange = (field: keyof ContentStrategy, value: any) => {
    if (editedStrategy) {
      setEditedStrategy({ ...editedStrategy, [field]: value });
    }
  };

  const handleArrayFieldChange = (field: keyof ContentStrategy, index: number, value: string) => {
    if (editedStrategy) {
      const currentArray = [...(editedStrategy[field] as string[])];
      currentArray[index] = value;
      setEditedStrategy({ ...editedStrategy, [field]: currentArray });
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
          You must complete the Topic & Angle stage before generating a content strategy.
        </p>
      </div>
    );
  }

  if (!strategy || !editedStrategy) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <Network className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Build Content Strategy</h3>
          <p className="text-muted-foreground text-sm mb-8">
            The AI will compile your content, platforms, and chosen angle into a cohesive blueprint.
          </p>
          <button 
            onClick={handleGenerate}
            disabled={isGenerating}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Compiling Blueprint...</span>
              </>
            ) : (
              <>
                <Network className="w-5 h-5" />
                <span>Generate Strategy</span>
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  const isReadOnly = activeStage.status === 'Completed' && !isEditing;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <h3 className="text-xl font-bold text-foreground">Content Blueprint</h3>
          <p className="text-sm text-muted-foreground">Review and edit the AI-generated strategy before confirming.</p>
        </div>
        
        <div className="flex items-center gap-3 shrink-0">
          {isReadOnly ? (
            <button 
              onClick={() => setIsEditing(true)}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 transition-all shadow-sm"
            >
              <Edit3 className="w-4 h-4" />
              <span>Edit Strategy</span>
            </button>
          ) : (
            <button 
              onClick={handleSaveAndContinue}
              disabled={isApproving}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isApproving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  <span>Save & Continue</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-8">
        
        {/* Core Strategy */}
        <div className="space-y-6">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Core Strategy</h4>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Objective</label>
              {isReadOnly ? (
                <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{strategy.objective}</p>
              ) : (
                <textarea 
                  value={editedStrategy.objective}
                  onChange={(e) => handleFieldChange('objective', e.target.value)}
                  className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                />
              )}
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Target Audience</label>
              {isReadOnly ? (
                <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{strategy.targetAudience}</p>
              ) : (
                <textarea 
                  value={editedStrategy.targetAudience}
                  onChange={(e) => handleFieldChange('targetAudience', e.target.value)}
                  className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                />
              )}
            </div>
          </div>
          
          <div className="grid grid-cols-1 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Editorial Tone & Delivery</label>
              {isReadOnly ? (
                <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{strategy.tone}</p>
              ) : (
                <textarea 
                  value={editedStrategy.tone}
                  onChange={(e) => handleFieldChange('tone', e.target.value)}
                  className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[50px]"
                />
              )}
            </div>
          </div>
          
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Core Message</label>
            {isReadOnly ? (
              <p className="text-sm font-medium text-foreground bg-primary/5 p-4 rounded-xl border border-primary/20">{strategy.coreMessage}</p>
            ) : (
              <textarea 
                value={editedStrategy.coreMessage}
                onChange={(e) => handleFieldChange('coreMessage', e.target.value)}
                className="w-full text-sm font-medium bg-primary/5 border border-primary/20 rounded-xl p-4 focus:outline-none focus:ring-1 focus:ring-primary min-h-[100px]"
              />
            )}
          </div>
        </div>

        {/* Messaging & Hooks */}
        <div className="space-y-6 pt-6 border-t border-border/50">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary">Messaging & Hooks</h4>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Hook Strategy</label>
              {isReadOnly ? (
                <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{strategy.hookStrategy}</p>
              ) : (
                <textarea 
                  value={editedStrategy.hookStrategy}
                  onChange={(e) => handleFieldChange('hookStrategy', e.target.value)}
                  className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                />
              )}
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Call to Action (CTA)</label>
              {isReadOnly ? (
                <p className="text-sm text-foreground/90 bg-muted/30 p-3 rounded-xl border border-border/30">{strategy.callToAction}</p>
              ) : (
                <textarea 
                  value={editedStrategy.callToAction}
                  onChange={(e) => handleFieldChange('callToAction', e.target.value)}
                  className="w-full text-sm bg-background border border-border/50 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                />
              )}
            </div>
          </div>
        </div>

        {/* Talking Points */}
        <div className="space-y-4 pt-6 border-t border-border/50">
          <h4 className="text-sm font-semibold tracking-widest uppercase text-primary mb-4">Key Talking Points</h4>
          <div className="space-y-3">
            {editedStrategy.keyTalkingPoints.map((point, index) => (
              <div key={index} className="flex gap-3">
                <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0 text-xs font-bold mt-0.5">
                  {index + 1}
                </div>
                {isReadOnly ? (
                  <p className="text-sm text-foreground/90 py-1">{point}</p>
                ) : (
                  <input 
                    type="text"
                    value={point}
                    onChange={(e) => handleArrayFieldChange('keyTalkingPoints', index, e.target.value)}
                    className="flex-1 text-sm bg-background border border-border/50 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
