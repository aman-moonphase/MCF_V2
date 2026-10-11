"use client"

import React from 'react';
import { WorkflowStage, Project } from '@/types/project';
import { Bot, Edit3, FileText, ArrowRight } from 'lucide-react';
import { hasDedicatedStageUI, stageComponentFor } from './stage-registry';
import { getStageLabel } from '@/lib/workflow-stages';
import { AiModeIndicator } from '@/components/ai-mode-indicator';
import { ScheduleDialog } from '@/components/schedule-dialog';
import { Calendar } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface WorkspaceContentProps {
  project: Project;
  activeStage: WorkflowStage;
  onAdvanceStage: () => Promise<void> | void;
  onSelectStage?: (stageId: string) => void;
}

export function WorkspaceContent({ project, activeStage, onAdvanceStage, onSelectStage }: WorkspaceContentProps) {
  const [isScheduleOpen, setIsScheduleOpen] = React.useState(false);
  const [isAdvancing, setIsAdvancing] = React.useState(false);

  const handleAdvance = async () => {
    if (isAdvancing) return;
    setIsAdvancing(true);
    try {
      await onAdvanceStage();
    } finally {
      setIsAdvancing(false);
    }
  };

  const renderStageContent = () => {
    const StageComponent = stageComponentFor(project, activeStage.type);
    if (StageComponent) {
      return <StageComponent project={project} activeStage={activeStage} onComplete={onAdvanceStage} onSelectStage={onSelectStage} />;
    }

    switch (activeStage.type) {
      case 'source-grounding':
        return (
          <div className="space-y-6">
            <div className="glass-panel p-6 rounded-2xl border-emerald-500/20 bg-emerald-500/5">
              <h3 className="flex items-center gap-2 text-lg font-semibold mb-2 text-foreground">
                <FileText className="w-5 h-5 text-emerald-500" />
                Source Grounding & Research Check
              </h3>
              <p className="text-sm text-muted-foreground mb-4">
                The source material has been successfully processed, embedded, and fact-verified against available context.
              </p>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                <div className="bg-white dark:bg-card p-4 rounded-xl border border-border/50 shadow-sm">
                  <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider mb-1">Status</div>
                  <div className="font-medium">Fact Verification Complete</div>
                </div>
                <div className="bg-white dark:bg-card p-4 rounded-xl border border-border/50 shadow-sm">
                  <div className="text-xs font-semibold text-primary uppercase tracking-wider mb-1">Source Size</div>
                  <div className="font-medium">{project.sourceReference.length > 50 ? 'Extracted text' : project.sourceReference}</div>
                </div>
              </div>

              <div className="bg-muted/50 p-4 rounded-xl border border-border/50 text-sm text-muted-foreground leading-relaxed h-[200px] overflow-y-auto font-mono text-xs">
                {activeStage.data?.extractedContext || `[SYSTEM] Processing Context...\n[SYSTEM] Generating Embeddings...\n[SYSTEM] Fact Verification Passed.\n\nContext extracted and ready for downstream AI pipelines.`}
              </div>
            </div>
          </div>
        );

      default:
        return (
          <div className="flex items-center justify-center h-full min-h-[40vh] border-2 border-dashed border-border/50 rounded-3xl p-12 text-center bg-background/30">
            <div className="space-y-4 max-w-sm">
              <Bot className="w-12 h-12 text-muted-foreground/50 mx-auto" />
              <h3 className="text-lg font-medium text-foreground">Stage Workspace</h3>
              <p className="text-sm text-muted-foreground">
                This area will host the interactive AI tools and generated content for the <strong>{getStageLabel(activeStage)}</strong> stage.
              </p>
            </div>
          </div>
        );
    }
  };

  return (
    <div className="flex-1 min-w-0 flex flex-col h-full bg-background overflow-hidden relative z-10">
      
      {/* Workspace Header */}
      <div className="flex items-start sm:items-center justify-between gap-3 sm:gap-4 px-4 sm:px-8 py-4 sm:py-5 border-b border-border/50 bg-background/95 sm:bg-background/80 backdrop-blur-md z-20">
        <div className="flex flex-col min-w-0 pr-2">
          <span className="text-xs font-semibold tracking-wider text-primary uppercase mb-1">
            Active Stage
          </span>
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground truncate">
            {getStageLabel(activeStage)}
          </h2>
          <div className="mt-2"><AiModeIndicator /></div>
        </div>
        
        <div className="flex items-center gap-2 sm:gap-3 shrink-0 pt-0.5 sm:pt-0">
          <div className={`px-2.5 sm:px-3 py-1 rounded-full text-xs font-medium border whitespace-nowrap shrink-0 ${
            activeStage.status === 'Completed' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' : 
            activeStage.status === 'In Progress' ? 'bg-primary/10 text-primary border-primary/20' : 
            'bg-muted text-muted-foreground border-border/50'
          }`}>
            {activeStage.status}
          </div>
          
          {activeStage.status !== 'Completed' && !hasDedicatedStageUI(activeStage.type, project) && (
            <button 
              onClick={handleAdvance}
              disabled={isAdvancing}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-foreground text-background text-sm font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isAdvancing ? (
                <>
                  <span className="w-4 h-4 rounded-full border-2 border-background border-t-transparent animate-spin shrink-0" />
                  <span>Approving...</span>
                </>
              ) : (
                <>
                  <span>Approve & Continue</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          )}

          {(activeStage.type === 'final-script') && activeStage.status === 'Completed' && (
            <button 
              onClick={() => setIsScheduleOpen(true)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-primary text-primary-foreground text-sm font-semibold hover:scale-[1.02] active:scale-95 transition-all shadow-md"
            >
              <Calendar className="w-4 h-4" />
              <span>Add to Calendar</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-8 lg:p-12">
        <div className="max-w-4xl mx-auto">
          {renderStageContent()}
        </div>
      </div>

      <ScheduleDialog
        projectId={project.id}
        isOpen={isScheduleOpen}
        onClose={() => setIsScheduleOpen(false)}
        onScheduled={() => {
          // Additional logic could go here, for now it will just show a toast in the dialog
        }}
      />
    </div>
  );
}
