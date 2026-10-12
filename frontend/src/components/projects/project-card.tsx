import React from 'react';
import Link from 'next/link';
import { Project, ProjectStatus } from '@/types/project';
import { Clock, CheckCircle2, AlertCircle, PlayCircle, FileText, Globe, Trash2 } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns'; // Wait, is date-fns installed? I can just use a simple formatter or Intl.RelativeTimeFormat
import { getStageLabelByType } from '@/lib/workflow-stages';
import { getDisplayProjectTitle } from '@/lib/project-title';

const getStatusColor = (status: ProjectStatus) => {
  switch (status) {
    case 'Draft': return 'text-slate-600 bg-slate-100 border-slate-200 dark:text-muted-foreground dark:bg-muted dark:border-border';
    case 'In Progress': return 'text-blue-600 bg-blue-50 border-blue-100 dark:text-blue-500 dark:bg-blue-500/10 dark:border-blue-500/20';
    case 'Needs Review': return 'text-amber-600 bg-amber-50 border-amber-100 dark:text-amber-500 dark:bg-amber-500/10 dark:border-amber-500/20';
    case 'Approved': return 'text-emerald-600 bg-emerald-50 border-emerald-100 dark:text-emerald-500 dark:bg-emerald-500/10 dark:border-emerald-500/20';
    case 'Completed': return 'text-primary bg-primary/10 border-primary/20';
    case 'Failed': return 'text-red-600 bg-red-50 border-red-100 dark:text-red-500 dark:bg-red-500/10 dark:border-red-500/20';
    default: return 'text-slate-600 bg-slate-100 border-slate-200 dark:text-muted-foreground dark:bg-muted dark:border-border';
  }
};

const getStatusIcon = (status: ProjectStatus) => {
  switch (status) {
    case 'Draft': return <Clock className="w-3 h-3" />;
    case 'In Progress': return <PlayCircle className="w-3 h-3" />;
    case 'Needs Review': return <AlertCircle className="w-3 h-3" />;
    case 'Approved': 
    case 'Completed': return <CheckCircle2 className="w-3 h-3" />;
    case 'Failed': return <AlertCircle className="w-3 h-3" />;
    default: return null;
  }
};

// Simple relative time formatter
function timeAgo(dateString: string) {
  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
    
    if (diffInSeconds < 60) return 'Just now';
    if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
    if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
    return `${Math.floor(diffInSeconds / 86400)}d ago`;
  } catch (e) {
    return 'Unknown';
  }
}

export function ProjectCard({ project, onDelete }: { project: Project, onDelete?: (project: Project) => void }) {
  const completedStages = project.stages.filter(s => s.status === 'Completed').length;
  const progressPercent = Math.round((completedStages / project.stages.length) * 100);

  return (
    <div className="group relative flex flex-col justify-between p-5 bg-white dark:bg-card border border-slate-200 dark:border-border rounded-2xl hover:border-primary/30 dark:hover:border-primary/50 hover:shadow-md transition-all duration-300">
      <Link href={`/projects/${project.id}`} className="absolute inset-0 z-0" aria-label={`View project ${getDisplayProjectTitle(project)}`} />
      
      <div className="relative z-10 pointer-events-none">
        <div className="flex items-start justify-between mb-4 gap-2">
          <h3 className="font-semibold text-lg leading-tight group-hover:text-primary transition-colors line-clamp-2">
            {getDisplayProjectTitle(project)}
          </h3>
          <div className="flex items-center gap-2 pointer-events-auto">
            <div className={`shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(project.status)}`}>
              {getStatusIcon(project.status)}
              <span>{project.status}</span>
            </div>
            {onDelete && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onDelete(project);
                }}
                className="p-1.5 text-slate-400 hover:text-destructive hover:bg-destructive/10 rounded-full transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100 bg-white dark:bg-card"
                title="Delete Project"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
        
        <p className="text-sm text-slate-500 dark:text-muted-foreground line-clamp-2 mb-6">
          {project.description}
        </p>
      </div>

      <div className="space-y-4">
        {/* Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs font-medium text-slate-500 dark:text-muted-foreground">
            <span>{getStageLabelByType(project, project.currentStage)}</span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-1.5 w-full bg-slate-100 dark:bg-muted rounded-full overflow-hidden">
            <div 
              className="h-full bg-gradient-to-r from-indigo-500 to-primary rounded-full transition-all duration-500" 
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Meta info */}
        <div className="flex items-center justify-between text-xs font-medium text-slate-400 dark:text-muted-foreground pt-4 border-t border-slate-100 dark:border-border/50">
          <div className="flex items-center gap-1.5">
            {project.sourceType.toLowerCase() === 'url' ? (
              <Globe className="w-3.5 h-3.5" />
            ) : (
              <FileText className="w-3.5 h-3.5" />
            )}
            <span>{project.sourceType}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            <span>Updated {timeAgo(project.updatedAt)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
