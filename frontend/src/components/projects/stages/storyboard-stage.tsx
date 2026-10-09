"use client"

import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Storyboard, StoryboardScene } from '@/types/workflow';
import { StoryboardService } from '@/lib/services/storyboard.service';
import { ProjectService } from '@/lib/project-service';
import { Project, WorkflowStage } from '@/types/project';
import { Film, Check, Loader2, Save, Lock, Edit3, Plus, Trash2, ArrowUp, ArrowDown, AlertTriangle, AlertCircle, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

export function StoryboardStage({ project, activeStage, onComplete }: Props) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [storyboard, setStoryboard] = useState<Storyboard | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedStoryboard, setEditedStoryboard] = useState<Storyboard | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Prerequisites
  const strategyStage = project.stages.find(s => s.type === 'content-strategy');
  const strategy = strategyStage?.data?.strategy;
  
  const isLocked = !strategy;

  useEffect(() => {
    if (activeStage.data?.storyboard) {
      setStoryboard(activeStage.data.storyboard);
      setEditedStoryboard(activeStage.data.storyboard);
    }
  }, [activeStage]);

  const handleGenerate = async () => {
    if (isLocked) return;

    setIsGenerating(true);
    setError(null);
    try {
      // Backend reads all prerequisite context from PostgreSQL automatically
      const result = await StoryboardService.generateStoryboard(project.id);
      setStoryboard(result);
      setEditedStoryboard(result);

      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, storyboard: result }
      });
    } catch (e: any) {
      setError(e.message || 'AI storyboard generation failed. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const validateStoryboard = (sb: Storyboard): string | null => {
    if (sb.scenes.length === 0) return "Storyboard must have at least one scene.";
    
    for (const scene of sb.scenes) {
      if (!scene.title.trim()) return `Scene ${scene.order} is missing a title.`;
      if (!scene.purpose.trim()) return `Scene ${scene.order} is missing a purpose.`;
      if (!scene.narration.trim() && !scene.visualDirection.trim()) {
        return `Scene ${scene.order} must have either narration or visual direction.`;
      }
    }
    
    // Check for duplicate orders just in case
    const orders = sb.scenes.map(s => s.order);
    if (new Set(orders).size !== orders.length) return "Invalid scene ordering detected.";
    
    return null;
  };

  const handleSaveDraft = async () => {
    if (!editedStoryboard) return;
    
    // Update order numbers sequentially
    const updatedScenes = editedStoryboard.scenes.map((s, index) => ({ ...s, order: index + 1 }));
    const finalStoryboard = { ...editedStoryboard, scenes: updatedScenes, status: 'Needs Review' as const };
    
    const saved = await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
      data: { ...activeStage.data, storyboard: finalStoryboard }
    });
    if (!saved) return;
    toast.success('Storyboard draft saved');
    
    setIsEditing(false);
    setStoryboard(finalStoryboard);
    setEditedStoryboard(finalStoryboard);
    setValidationError(null);
  };

  const handleApprove = async () => {
    if (!storyboard || isApproving) return;

    setIsApproving(true);
    try {
      const error = validateStoryboard(storyboard);
      if (error) {
        setValidationError(error);
        return;
      }

      const finalStoryboard = { ...storyboard, status: 'Approved' as const };
      
      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, storyboard: finalStoryboard }
      });
      
      setStoryboard(finalStoryboard);
      setEditedStoryboard(finalStoryboard);
      setValidationError(null);
      await onComplete(); // This unlocks the Script stage
    } finally {
      setIsApproving(false);
    }
  };

  const handleSceneChange = (sceneId: string, field: keyof StoryboardScene, value: string) => {
    if (!editedStoryboard) return;
    
    const newScenes = editedStoryboard.scenes.map(s => 
      s.id === sceneId ? { ...s, [field]: value } : s
    );
    
    setEditedStoryboard({ ...editedStoryboard, scenes: newScenes });
  };

  const handleAddScene = () => {
    if (!editedStoryboard) return;
    
    const newScene: StoryboardScene = {
      id: Math.random().toString(36).substring(2, 9),
      order: editedStoryboard.scenes.length + 1,
      title: 'New Scene',
      purpose: '',
      narration: '',
      visualDirection: '',
      onScreenText: '',
      transition: '',
      estimatedDuration: ''
    };
    
    setEditedStoryboard({ 
      ...editedStoryboard, 
      scenes: [...editedStoryboard.scenes, newScene] 
    });
  };

  const handleDeleteScene = (sceneId: string) => {
    if (!editedStoryboard) return;
    const newScenes = editedStoryboard.scenes.filter(s => s.id !== sceneId);
    setEditedStoryboard({ ...editedStoryboard, scenes: newScenes });
  };

  const handleMoveScene = (index: number, direction: 'up' | 'down') => {
    if (!editedStoryboard) return;
    const newScenes = [...editedStoryboard.scenes];
    
    if (direction === 'up' && index > 0) {
      [newScenes[index - 1], newScenes[index]] = [newScenes[index], newScenes[index - 1]];
    } else if (direction === 'down' && index < newScenes.length - 1) {
      [newScenes[index], newScenes[index + 1]] = [newScenes[index + 1], newScenes[index]];
    }
    
    setEditedStoryboard({ ...editedStoryboard, scenes: newScenes });
  };

  if (isLocked) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2">
          <Lock className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-sm">
          You must complete the Content Strategy stage before generating a storyboard.
        </p>
      </div>
    );
  }

  if (!storyboard || !editedStoryboard) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <Film className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Generate Storyboard</h3>
          <p className="text-muted-foreground text-sm mb-8">
            The AI will translate your approved content strategy, topic angle, and platform selection into a scene-by-scene narrative storyboard.
          </p>

          {error && (
            <div className="flex items-start gap-3 p-4 mb-6 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm text-left">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div className="flex-1">
                <p className="font-semibold mb-1">Generation failed</p>
                <p className="text-red-400/90">{error}</p>
              </div>
            </div>
          )}

          <button
            id="btn-generate-storyboard"
            onClick={handleGenerate}
            disabled={isGenerating}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>AI is designing your storyboard...</span>
              </>
            ) : error ? (
              <>
                <RefreshCw className="w-5 h-5" />
                <span>Retry Generation</span>
              </>
            ) : (
              <>
                <Film className="w-5 h-5" />
                <span>Generate Storyboard</span>
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  const isApproved = storyboard.status === 'Approved' && activeStage.status === 'Completed';
  const showEditMode = isEditing && !isApproved;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h3 className="text-xl font-bold text-foreground">Storyboard</h3>
            <span className={cn(
              "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
              isApproved ? "bg-green-500/10 text-green-500" : "bg-primary/10 text-primary"
            )}>
              {isApproved ? 'Approved' : storyboard.status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">Review, edit, and approve the scene sequence.</p>
        </div>
        
        <div className="flex items-center gap-3 shrink-0">
          {!isApproved && !showEditMode && (
            <>
              <button 
                onClick={() => setIsEditing(true)}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 transition-all shadow-sm"
              >
                <Edit3 className="w-4 h-4" />
                <span>Edit Scenes</span>
              </button>
              <button 
                onClick={handleApprove}
                disabled={isApproving}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isApproving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Approving...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    <span>Approve Storyboard</span>
                  </>
                )}
              </button>
            </>
          )}
          {showEditMode && (
            <button 
              onClick={handleSaveDraft}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md"
            >
              <Save className="w-4 h-4" />
              <span>Save Draft</span>
            </button>
          )}
        </div>
      </div>

      {validationError && (
        <div className="flex items-center gap-3 p-4 rounded-xl border border-destructive/50 bg-destructive/10 text-destructive text-sm font-medium">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <p>{validationError}</p>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-6">
        {(showEditMode ? editedStoryboard.scenes : storyboard.scenes).map((scene, index) => (
          <div key={scene.id} className="glass-panel p-6 rounded-2xl border border-border/50 shadow-sm relative group">
            
            <div className="flex items-start justify-between gap-4 mb-6">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold text-lg shrink-0">
                  {index + 1}
                </div>
                {showEditMode ? (
                  <input 
                    type="text"
                    value={scene.title}
                    onChange={(e) => handleSceneChange(scene.id, 'title', e.target.value)}
                    placeholder="Scene Title"
                    className="text-lg font-bold bg-background border border-border/50 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary w-full max-w-sm"
                  />
                ) : (
                  <h4 className="text-lg font-bold text-foreground">{scene.title}</h4>
                )}
              </div>

              {showEditMode && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button 
                    onClick={() => handleMoveScene(index, 'up')}
                    disabled={index === 0}
                    className="p-2 rounded-lg hover:bg-muted text-muted-foreground disabled:opacity-30"
                  >
                    <ArrowUp className="w-4 h-4" />
                  </button>
                  <button 
                    onClick={() => handleMoveScene(index, 'down')}
                    disabled={index === editedStoryboard.scenes.length - 1}
                    className="p-2 rounded-lg hover:bg-muted text-muted-foreground disabled:opacity-30"
                  >
                    <ArrowDown className="w-4 h-4" />
                  </button>
                  <div className="w-px h-4 bg-border mx-1" />
                  <button 
                    onClick={() => handleDeleteScene(scene.id)}
                    className="p-2 rounded-lg hover:bg-destructive/10 text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Purpose</label>
                  {showEditMode ? (
                    <input 
                      type="text"
                      value={scene.purpose}
                      onChange={(e) => handleSceneChange(scene.id, 'purpose', e.target.value)}
                      className="w-full text-sm bg-background border border-border/50 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  ) : (
                    <p className="text-sm text-foreground/90">{scene.purpose}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Narration</label>
                  {showEditMode ? (
                    <textarea 
                      value={scene.narration}
                      onChange={(e) => handleSceneChange(scene.id, 'narration', e.target.value)}
                      className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                    />
                  ) : (
                    <p className="text-sm font-medium text-foreground bg-muted/30 p-3 rounded-xl border border-border/30">{scene.narration}</p>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Visual Direction</label>
                  {showEditMode ? (
                    <textarea 
                      value={scene.visualDirection}
                      onChange={(e) => handleSceneChange(scene.id, 'visualDirection', e.target.value)}
                      className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
                    />
                  ) : (
                    <p className="text-sm text-foreground/80 italic">{scene.visualDirection}</p>
                  )}
                </div>
                
                <div className="grid grid-cols-3 gap-4 pt-2">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">On-Screen Text</label>
                    {showEditMode ? (
                      <input 
                        type="text"
                        value={scene.onScreenText}
                        onChange={(e) => handleSceneChange(scene.id, 'onScreenText', e.target.value)}
                        className="w-full text-xs bg-background border border-border/50 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <p className="text-xs font-semibold text-primary">{scene.onScreenText || 'None'}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Transition</label>
                    {showEditMode ? (
                      <input 
                        type="text"
                        value={scene.transition}
                        onChange={(e) => handleSceneChange(scene.id, 'transition', e.target.value)}
                        className="w-full text-xs bg-background border border-border/50 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <p className="text-xs text-foreground/80">{scene.transition || 'None'}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Duration</label>
                    {showEditMode ? (
                      <input 
                        type="text"
                        value={scene.estimatedDuration}
                        onChange={(e) => handleSceneChange(scene.id, 'estimatedDuration', e.target.value)}
                        className="w-full text-xs bg-background border border-border/50 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <p className="text-xs text-foreground/80">{scene.estimatedDuration || 'N/A'}</p>
                    )}
                  </div>
                </div>
              </div>
            </div>

          </div>
        ))}

        {showEditMode && (
          <button 
            onClick={handleAddScene}
            className="w-full py-6 rounded-2xl border-2 border-dashed border-border/50 hover:border-primary/50 hover:bg-primary/5 text-muted-foreground hover:text-primary transition-all flex flex-col items-center justify-center gap-2"
          >
            <Plus className="w-6 h-6" />
            <span className="font-medium">Add New Scene</span>
          </button>
        )}
      </div>
    </div>
  );
}
