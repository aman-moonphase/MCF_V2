"use client"

import React from 'react';
import { Project } from '@/types/project';
import { CheckCircle2, Circle, Clock, Lock, PlayCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getStageLabel } from '@/lib/workflow-stages';
import { ProductWorkflowState } from '@/lib/services/workflow-orchestration.service';

interface WorkflowSidebarProps {
  project: Project;
  onStageSelect: (stageId: string) => void;
  activeStageId?: string;
  orchestrationState?: ProductWorkflowState | null;
}

export function WorkflowSidebar({ project, onStageSelect, activeStageId, orchestrationState }: WorkflowSidebarProps) {
  
  const getStageIcon = (status: string) => {
    switch(status) {
      case 'Completed': return <CheckCircle2 className="w-5 h-5 text-emerald-500" />;
      case 'In Progress': return <PlayCircle className="w-5 h-5 text-primary animate-pulse" />;
      case 'Locked': return <Lock className="w-5 h-5 text-muted-foreground/50" />;
      case 'Needs Review': return <Clock className="w-5 h-5 text-amber-500" />;
      default: return <Circle className="w-5 h-5 text-muted-foreground/30" />;
    }
  };

  return (
    <div className="w-full lg:w-[280px] xl:w-[320px] shrink-0 border-r border-border/50 bg-background/50 backdrop-blur-xl h-full flex flex-col">
      <div className="p-6 border-b border-border/50">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold tracking-widest text-muted-foreground uppercase">Your Workflow</h2>
          {orchestrationState?.status === 'paused_at_approval_boundary' && !orchestrationState.reviewApproved && (
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-ping" title="Paused at Review Boundary" />
          )}
        </div>
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {project.stages.filter(s => s.status === 'Completed').length} of {project.stages.length} stages completed
          </p>
        </div>
        {orchestrationState && (
          <div className="mt-2.5">
            {(orchestrationState.status === 'completed' || orchestrationState.reviewApproved) ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
                <CheckCircle2 className="w-3 h-3" />
                <span>Completed</span>
              </span>
            ) : orchestrationState.status === 'paused_at_approval_boundary' ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/20">
                <Clock className="w-3 h-3" />
                <span>Paused for Review</span>
              </span>
            ) : orchestrationState.status === 'halted' ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/20">
                <Clock className="w-3 h-3" />
                <span>Prerequisite Required</span>
              </span>
            ) : null}
          </div>
        )}
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-1 no-scrollbar">
        {project.stages.map((stage, index) => {
          const isActive = activeStageId ? activeStageId === stage.id : project.currentStage === stage.type;
          const isLocked = stage.status === 'Locked';
          
          return (
            <button
              key={stage.id}
              onClick={() => !isLocked && onStageSelect(stage.id)}
              disabled={isLocked}
              className={cn(
                "w-full flex items-center gap-4 p-3 rounded-xl transition-all duration-300 text-left relative group cursor-pointer disabled:cursor-not-allowed",
                isActive ? "bg-primary/10 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]" : "hover:bg-muted",
                isLocked && "opacity-60 cursor-not-allowed"
              )}
            >
              {/* Vertical connector line */}
              {index < project.stages.length - 1 && (
                <div className="absolute left-[1.35rem] top-[2.5rem] bottom-[-0.75rem] w-px bg-border group-hover:bg-border/80 transition-colors z-0" />
              )}
              
              <div className="relative z-10 bg-background rounded-full">
                {getStageIcon(stage.status)}
              </div>
              
              <div className="flex flex-col">
                <span className={cn(
                  "text-sm tracking-tight transition-colors",
                  isActive ? "font-semibold text-foreground" : "font-medium text-muted-foreground group-hover:text-foreground",
                  isLocked && "text-muted-foreground/70"
                )}>
                  {getStageLabel(stage)}
                </span>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
                  {stage.status}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
