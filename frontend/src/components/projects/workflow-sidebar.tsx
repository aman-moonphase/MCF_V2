"use client"

import React from 'react';
import { Project, WorkflowStage } from '@/types/project';
import { CheckCircle2, Circle, Clock, Lock, PlayCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getStageLabel } from '@/lib/workflow-stages';

interface WorkflowSidebarProps {
  project: Project;
  onStageSelect: (stageId: string) => void;
  activeStageId?: string;
}

export function WorkflowSidebar({ project, onStageSelect, activeStageId }: WorkflowSidebarProps) {
  
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
        <h2 className="text-sm font-semibold tracking-widest text-muted-foreground uppercase mb-1">Agentic Pipeline</h2>
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {project.stages.filter(s => s.status === 'Completed').length} of {project.stages.length} stages completed
          </p>
        </div>
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
                "w-full flex items-center gap-4 p-3 rounded-xl transition-all duration-300 text-left relative group",
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
