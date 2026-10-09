"use client"

import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Script, ScriptSection } from '@/types/workflow';
import { ScriptService } from '@/lib/services/script.service';
import { ProjectService } from '@/lib/project-service';
import { Project, WorkflowStage } from '@/types/project';
import { FileText, Check, Loader2, Save, Lock, Edit3, Plus, Trash2, ArrowUp, ArrowDown, AlertTriangle, AlertCircle, RefreshCw, PartyPopper } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  project: Project;
  activeStage: WorkflowStage;
  onComplete: () => void;
}

export function ScriptStage({ project, activeStage, onComplete }: Props) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [script, setScript] = useState<Script | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedScript, setEditedScript] = useState<Script | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Prerequisites — storyboard must be Approved
  const storyboardStage = project.stages.find(s => s.type === 'storyboard');
  const platformStage = project.stages.find(s => s.type === 'platform-strategy');

  const storyboard = storyboardStage?.data?.storyboard;
  
  // Platform and format can be read directly from the generated script,
  // or fall back to the selected platform strategy if script is missing.
  const selectedPlatformIds = platformStage?.data?.selectedIds || [];
  const recommendations = platformStage?.data?.recommendations || [];
  const selectedPlatform = recommendations.find((p: any) => selectedPlatformIds.includes(p.id)) || recommendations[0];

  const isStoryboardApproved = storyboard?.status === 'Approved';
  const isLocked = !isStoryboardApproved || !storyboard;

  useEffect(() => {
    if (activeStage.data?.script) {
      setScript(activeStage.data.script);
      setEditedScript(activeStage.data.script);
    }
  }, [activeStage]);

  const handleGenerate = async () => {
    if (isLocked) return;

    setIsGenerating(true);
    setError(null);
    try {
      // Backend reads all prerequisite context from PostgreSQL automatically
      const result = await ScriptService.generateScript(project.id);
      setScript(result);
      setEditedScript(result);

      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, script: result }
      });
    } catch (e: any) {
      setError(e.message || 'AI script generation failed. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const validateScript = (sc: Script): string | null => {
    if (!sc.title.trim()) return "Script must have a title.";
    if (!sc.hook.trim()) return "Script hook cannot be empty.";
    if (sc.sections.length === 0) return "Script must have at least one section.";
    
    for (const section of sc.sections) {
      if (!section.narration.trim() && !section.visualNotes.trim()) {
        return `Section ${section.order} must have either narration or visual notes.`;
      }
    }
    
    if (!sc.conclusion.trim()) return "Script conclusion cannot be empty.";
    
    return null;
  };

  const handleSaveDraft = async () => {
    if (!editedScript) return;
    
    // Update order numbers sequentially
    const updatedSections = editedScript.sections.map((s, index) => ({ ...s, order: index + 1 }));
    const finalScript = { ...editedScript, sections: updatedSections, status: 'Needs Review' as const };
    
    const saved = await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
      data: { ...activeStage.data, script: finalScript }
    });
    if (!saved) return;
    toast.success('Script draft saved');
    
    setIsEditing(false);
    setScript(finalScript);
    setEditedScript(finalScript);
    setValidationError(null);
  };

  const handleApprove = async () => {
    if (!script || isApproving) return;

    setIsApproving(true);
    try {
      const error = validateScript(script);
      if (error) {
        setValidationError(error);
        return;
      }

      const finalScript = { ...script, status: 'Approved' as const };
      
      // Update stage data
      await ProjectService.updateWorkflowStage(project.id, activeStage.id, {
        data: { ...activeStage.data, script: finalScript }
      });
      
      // Mark Project as completed
      await ProjectService.updateProjectStatus(project.id, 'Completed');
      
      setScript(finalScript);
      setEditedScript(finalScript);
      setValidationError(null);
      await onComplete(); // This marks the final stage as Complete
    } finally {
      setIsApproving(false);
    }
  };

  const handleScriptChange = (field: keyof Script, value: any) => {
    if (!editedScript) return;
    setEditedScript({ ...editedScript, [field]: value });
  };

  const handleSectionChange = (sectionId: string, field: keyof ScriptSection, value: string) => {
    if (!editedScript) return;
    
    const newSections = editedScript.sections.map(s => 
      s.id === sectionId ? { ...s, [field]: value } : s
    );
    
    setEditedScript({ ...editedScript, sections: newSections });
  };

  const handleAddSection = () => {
    if (!editedScript) return;
    
    const newSection: ScriptSection = {
      id: Math.random().toString(36).substring(2, 9),
      order: editedScript.sections.length + 1,
      title: 'New Section',
      narration: '',
      visualNotes: '',
      onScreenText: '',
      estimatedDuration: ''
    };
    
    setEditedScript({ 
      ...editedScript, 
      sections: [...editedScript.sections, newSection] 
    });
  };

  const handleDeleteSection = (sectionId: string) => {
    if (!editedScript) return;
    const newSections = editedScript.sections.filter(s => s.id !== sectionId);
    setEditedScript({ ...editedScript, sections: newSections });
  };

  const handleMoveSection = (index: number, direction: 'up' | 'down') => {
    if (!editedScript) return;
    const newSections = [...editedScript.sections];
    
    if (direction === 'up' && index > 0) {
      [newSections[index - 1], newSections[index]] = [newSections[index], newSections[index - 1]];
    } else if (direction === 'down' && index < newSections.length - 1) {
      [newSections[index], newSections[index + 1]] = [newSections[index + 1], newSections[index]];
    }
    
    setEditedScript({ ...editedScript, sections: newSections });
  };

  if (isLocked) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-2">
          <Lock className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-xl font-semibold">Stage Locked</h3>
        <p className="text-muted-foreground max-w-sm">
          Complete and approve the Storyboard stage before generating the final script.
        </p>
      </div>
    );
  }

  // If approved and the overall project is marked Completed, show the final celebration state
  if (script?.status === 'Approved' && project.status === 'Completed' && !isEditing) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[60vh] space-y-6 text-center animate-in fade-in zoom-in duration-700">
        <div className="w-24 h-24 rounded-full bg-green-500/10 flex items-center justify-center mb-2 text-green-500 relative">
          <PartyPopper className="w-12 h-12" />
          <div className="absolute top-0 right-0 w-6 h-6 rounded-full bg-green-500 flex items-center justify-center">
            <Check className="w-4 h-4 text-white" />
          </div>
        </div>
        <div className="max-w-md space-y-4">
          <h3 className="text-3xl font-bold text-foreground">Content Package Ready</h3>
          <p className="text-muted-foreground">
            The creative workflow is complete. Your final script has been approved and your project is finalized.
          </p>
          
          <div className="bg-card border border-border/50 rounded-2xl p-6 text-left space-y-4 shadow-sm mt-8">
            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-4">Project Summary</h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center pb-3 border-b border-border/30">
                <span className="text-muted-foreground text-sm">Platform</span>
                <span className="font-medium">{script?.platform || selectedPlatform?.platform || 'Unknown'}</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-border/30">
                <span className="text-muted-foreground text-sm">Format</span>
                <span className="font-medium">{script?.format || selectedPlatform?.recommendedFormat || 'Unknown'}</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-border/30">
                <span className="text-muted-foreground text-sm">Storyboard Scenes</span>
                <span className="font-medium">{storyboard?.scenes.length} Scenes</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground text-sm">Script Status</span>
                <span className="font-medium text-green-500 flex items-center gap-1">
                  <Check className="w-3 h-3" /> Approved
                </span>
              </div>
            </div>
          </div>
          
          <div className="pt-6">
            <button 
              onClick={() => setIsEditing(true)}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors underline underline-offset-4"
            >
              Review Script Content
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!script || !editedScript) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[50vh] space-y-6 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-2 text-primary">
          <FileText className="w-8 h-8" />
        </div>
        <div className="max-w-md">
          <h3 className="text-2xl font-bold text-foreground mb-2">Generate Final Script</h3>
          <p className="text-muted-foreground text-sm mb-8">
            The AI will expand your approved storyboard into a polished, platform-adapted script — one section per scene.
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
            id="btn-generate-script"
            onClick={handleGenerate}
            disabled={isGenerating}
            className="inline-flex items-center justify-center gap-2 h-12 px-8 rounded-full bg-foreground text-background font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>AI is writing your script...</span>
              </>
            ) : error ? (
              <>
                <RefreshCw className="w-5 h-5" />
                <span>Retry Generation</span>
              </>
            ) : (
              <>
                <FileText className="w-5 h-5" />
                <span>Generate Script</span>
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  const isApproved = script.status === 'Approved' && activeStage.status === 'Completed';
  const showEditMode = isEditing && !isApproved;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 sticky top-0 bg-background/80 backdrop-blur-md py-4 z-20 border-b border-border/50">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h3 className="text-xl font-bold text-foreground">Final Script</h3>
            <span className={cn(
              "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
              isApproved ? "bg-green-500/10 text-green-500" : "bg-primary/10 text-primary"
            )}>
              {isApproved ? 'Approved' : script.status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">Review and approve the final content package.</p>
        </div>
        
        <div className="flex items-center gap-3 shrink-0">
          {!isApproved && !showEditMode && (
            <>
              <button 
                onClick={() => setIsEditing(true)}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 transition-all shadow-sm"
              >
                <Edit3 className="w-4 h-4" />
                <span>Edit Script</span>
              </button>
              <button 
                onClick={handleApprove}
                disabled={isApproving}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-green-500 text-white font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isApproving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Completing...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    <span>Approve & Complete Project</span>
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
          {isApproved && isEditing && (
            <button 
              onClick={() => setIsEditing(false)}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-muted text-foreground font-medium hover:bg-muted/80 transition-all shadow-sm"
            >
              <span>Back to Summary</span>
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

      {/* Script Header Meta */}
      <div className="glass-panel p-6 rounded-2xl border border-border/50 shadow-sm space-y-6">
        <div className="space-y-1.5">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Script Title</label>
          {showEditMode ? (
            <input 
              type="text"
              value={editedScript.title}
              onChange={(e) => handleScriptChange('title', e.target.value)}
              className="w-full text-xl font-bold bg-background border border-border/50 rounded-lg px-4 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          ) : (
            <h2 className="text-2xl font-bold text-foreground">{script.title}</h2>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4 pt-4 border-t border-border/50">
          <div className="space-y-1.5">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Target Platform</label>
            <p className="text-sm font-medium">{script.platform}</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Format</label>
            <p className="text-sm font-medium">{script.format}</p>
          </div>
        </div>

        <div className="space-y-1.5 pt-4 border-t border-border/50">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-primary" /> Hook
          </label>
          {showEditMode ? (
            <textarea 
              value={editedScript.hook}
              onChange={(e) => handleScriptChange('hook', e.target.value)}
              className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
            />
          ) : (
            <p className="text-lg font-medium text-foreground">{script.hook}</p>
          )}
        </div>
      </div>

      {/* Script Sections */}
      <div className="space-y-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground px-2">Body Sections</h3>
        
        {(showEditMode ? editedScript.sections : script.sections).map((section, index) => (
          <div key={section.id} className="bg-card p-6 rounded-2xl border border-border/50 shadow-sm relative group">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="flex items-center gap-4">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-widest w-24">
                  Sec {String(index + 1).padStart(2, '0')}
                </span>
                {showEditMode ? (
                  <input 
                    type="text"
                    value={section.title}
                    onChange={(e) => handleSectionChange(section.id, 'title', e.target.value)}
                    placeholder="Section Title"
                    className="text-base font-bold bg-background border border-border/50 rounded-md px-3 py-1 focus:outline-none focus:ring-1 focus:ring-primary w-full max-w-sm"
                  />
                ) : (
                  <h4 className="text-base font-bold text-foreground">{section.title}</h4>
                )}
              </div>

              {showEditMode && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => handleMoveSection(index, 'up')} disabled={index === 0} className="p-1.5 rounded hover:bg-muted text-muted-foreground disabled:opacity-30">
                    <ArrowUp className="w-4 h-4" />
                  </button>
                  <button onClick={() => handleMoveSection(index, 'down')} disabled={index === editedScript.sections.length - 1} className="p-1.5 rounded hover:bg-muted text-muted-foreground disabled:opacity-30">
                    <ArrowDown className="w-4 h-4" />
                  </button>
                  <div className="w-px h-4 bg-border mx-1" />
                  <button onClick={() => handleDeleteSection(section.id)} className="p-1.5 rounded hover:bg-destructive/10 text-destructive">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pl-28">
              <div className="space-y-1.5">
                <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Narration / Copy</label>
                {showEditMode ? (
                  <textarea 
                    value={section.narration}
                    onChange={(e) => handleSectionChange(section.id, 'narration', e.target.value)}
                    className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[100px]"
                  />
                ) : (
                  <p className="text-sm text-foreground leading-relaxed bg-muted/20 p-4 rounded-xl">{section.narration}</p>
                )}
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Visuals / B-Roll</label>
                  {showEditMode ? (
                    <textarea 
                      value={section.visualNotes}
                      onChange={(e) => handleSectionChange(section.id, 'visualNotes', e.target.value)}
                      className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[60px]"
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground italic border-l-2 border-primary/30 pl-3 py-1">{section.visualNotes || 'No specific visual notes'}</p>
                  )}
                </div>
                
                <div className="flex gap-4">
                  <div className="space-y-1.5 flex-1">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">On-Screen Text</label>
                    {showEditMode ? (
                      <input 
                        type="text"
                        value={section.onScreenText}
                        onChange={(e) => handleSectionChange(section.id, 'onScreenText', e.target.value)}
                        className="w-full text-xs bg-background border border-border/50 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <p className="text-xs font-semibold">{section.onScreenText || 'N/A'}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Duration</label>
                    {showEditMode ? (
                      <input 
                        type="text"
                        value={section.estimatedDuration}
                        onChange={(e) => handleSectionChange(section.id, 'estimatedDuration', e.target.value)}
                        className="w-24 text-xs bg-background border border-border/50 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <p className="text-xs text-muted-foreground">{section.estimatedDuration || 'N/A'}</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}

        {showEditMode && (
          <button 
            onClick={handleAddSection}
            className="w-full py-6 rounded-2xl border-2 border-dashed border-border/50 hover:border-primary/50 hover:bg-primary/5 text-muted-foreground hover:text-primary transition-all flex flex-col items-center justify-center gap-2"
          >
            <Plus className="w-6 h-6" />
            <span className="font-medium">Add New Section</span>
          </button>
        )}
      </div>

      {/* Script Footer / Outro */}
      <div className="glass-panel p-6 rounded-2xl border border-border/50 shadow-sm space-y-6">
        <div className="space-y-1.5">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Conclusion</label>
          {showEditMode ? (
            <textarea 
              value={editedScript.conclusion}
              onChange={(e) => handleScriptChange('conclusion', e.target.value)}
              className="w-full text-sm bg-background border border-border/50 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-primary min-h-[80px]"
            />
          ) : (
            <p className="text-sm text-foreground">{script.conclusion}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-primary" /> Call to Action
          </label>
          {showEditMode ? (
            <input 
              type="text"
              value={editedScript.callToAction}
              onChange={(e) => handleScriptChange('callToAction', e.target.value)}
              className="w-full text-sm font-bold bg-background border border-border/50 rounded-lg px-4 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          ) : (
            <p className="text-base font-bold text-foreground">{script.callToAction}</p>
          )}
        </div>
      </div>

    </div>
  );
}
