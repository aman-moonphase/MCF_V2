"use client"

import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ProjectService } from '@/lib/project-service';
import { toast } from 'sonner';
import { Project, ProjectStatus, WorkflowStage } from '@/types/project';
import { WorkflowSidebar } from '@/components/projects/workflow-sidebar';
import { WorkspaceContent } from '@/components/projects/workspace-content';
import { ArrowLeft, CheckCircle2, Clock, PlayCircle, Trash2, Loader2 } from 'lucide-react';
import Link from 'next/link';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ProductWorkflowState, WorkflowOrchestrationService } from '@/lib/services/workflow-orchestration.service';
import { isProductWorkflow } from '@/components/projects/stage-registry';
import { getDisplayProjectTitle } from '@/lib/project-title';

export default function ProjectWorkspace() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [project, setProject] = useState<Project | null>(null);
  const [activeStageId, setActiveStageId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [orchestrationState, setOrchestrationState] = useState<ProductWorkflowState | null>(null);
  const [isOrchestrationLoading, setIsOrchestrationLoading] = useState(false);
  const [orchestrationError, setOrchestrationError] = useState<string | null>(null);

  const fetchProject = useCallback(async () => {
    if (id) {
      const p = await ProjectService.getProject(id);
      if (p) {
        setProject(p);
        // Default to the current active stage, or the first stage if none
        const current = p.stages.find((s: WorkflowStage) => s.type === p.currentStage) || p.stages[0];
        if (current) setActiveStageId(current.id);

        if (isProductWorkflow(p)) {
          setIsOrchestrationLoading(true);
          setOrchestrationError(null);
          try {
            const orch = await WorkflowOrchestrationService.getStatus(id);
            setOrchestrationState(orch);
          } catch (e: unknown) {
            console.warn("Failed to load orchestration status:", e);
            const msg = e instanceof Error ? e.message : 'Unable to load orchestration status.';
            setOrchestrationError(msg);
          } finally {
            setIsOrchestrationLoading(false);
          }
        }
      }
      setIsLoading(false);
    }
  }, [id]);

  const refreshOrchestration = useCallback(async () => {
    if (!id) return;
    try {
      const orch = await WorkflowOrchestrationService.getStatus(id);
      setOrchestrationState(orch);
      setOrchestrationError(null);
    } catch (e: unknown) {
      console.warn("Failed to refresh orchestration status:", e);
      const msg = e instanceof Error ? e.message : 'Unable to load orchestration status.';
      setOrchestrationError(msg);
    }
  }, [id]);

  const handleRetryOrchestration = async () => {
    if (!id || !project || !isProductWorkflow(project)) return;
    setIsOrchestrationLoading(true);
    setOrchestrationError(null);
    try {
      const orch = await WorkflowOrchestrationService.getStatus(id);
      setOrchestrationState(orch);
      toast.success('Orchestration status refreshed');
    } catch (e: unknown) {
      console.warn("Retry failed to load orchestration status:", e);
      const msg = e instanceof Error ? e.message : 'Unable to load orchestration status.';
      setOrchestrationError(msg);
      toast.error(`Retry failed: ${msg}`);
    } finally {
      setIsOrchestrationLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchProject();
  }, [fetchProject]);

  const handleStageSelect = (stageId: string) => {
    setActiveStageId(stageId);
    if (project && isProductWorkflow(project)) {
      refreshOrchestration();
    }
  };

  const handleAdvanceStage = async () => {
    if (!project || !activeStageId) return;

    const currentIndex = project.stages.findIndex((s: WorkflowStage) => s.id === activeStageId);
    const nextStage = project.stages[currentIndex + 1];

    if (nextStage) {
      // Run updates concurrently to eliminate sequential network lag
      const [, newlyUpdated] = await Promise.all([
        ProjectService.updateWorkflowStage(project.id, activeStageId, { status: 'Completed' }),
        ProjectService.updateWorkflowStage(project.id, nextStage.id, { status: 'In Progress' })
      ]);
      
      if (newlyUpdated) {
        setProject(newlyUpdated);
        setActiveStageId(nextStage.id);
        await refreshOrchestration();
      }
    } else {
      // The stage update can be refused (e.g. Review Approval without an approved post): then the project
      // is not completed either. The refusal was already shown as a toast.
      const completed = await ProjectService.updateWorkflowStage(project.id, activeStageId, { status: 'Completed' });
      if (!completed) return;
      const finalProject = await ProjectService.updateProjectStatus(project.id, 'Completed');
      setProject(finalProject);
      await refreshOrchestration();
    }
  };

  const handleDeleteProject = async () => {
    if (!project || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const success = await ProjectService.deleteProject(project.id);
      if (success) {
        toast.success('Project deleted');
        router.push('/projects');
      } else {
        setDeleteError('Failed to delete project. Please try again.');
        setIsDeleting(false);
      }
    } catch {
      setDeleteError('An unexpected error occurred.');
      setIsDeleting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-[50vh]">
        <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[50vh] p-4 text-center">
        <h2 className="text-3xl font-bold mb-4">Project Not Found</h2>
        <p className="text-muted-foreground mb-8">The project you are looking for does not exist or has been deleted.</p>
        <Link href="/projects" className="inline-flex items-center justify-center px-6 py-3 rounded-full bg-foreground text-background font-medium hover:scale-[1.02] active:scale-95 transition-all">
          Back to Projects
        </Link>
      </div>
    );
  }

  const activeStage = project.stages.find(s => s.id === activeStageId) || project.stages[0];

  const getStatusColor = (status: ProjectStatus) => {
    switch (status) {
      case 'Draft': return 'text-muted-foreground bg-muted';
      case 'In Progress': return 'text-blue-500 bg-blue-500/10 border-blue-500/20';
      case 'Needs Review': return 'text-amber-500 bg-amber-500/10 border-amber-500/20';
      case 'Approved': return 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20';
      case 'Completed': return 'text-primary bg-primary/10 border-primary/20';
      case 'Failed': return 'text-red-500 bg-red-500/10 border-red-500/20';
      default: return 'text-muted-foreground bg-muted';
    }
  };

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-6rem)] relative z-10 w-full">
      
      {/* Project Global Header */}
      <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <Link href="/projects" className="p-2 rounded-full hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="h-6 w-px bg-border/50" />
          <div>
            <h1 className="text-lg font-bold tracking-tight text-foreground leading-tight line-clamp-1">{getDisplayProjectTitle(project)}</h1>
            <p className="text-xs text-muted-foreground line-clamp-1">{project.description}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <div className={`hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border ${getStatusColor(project.status)}`}>
            {project.status === 'Completed' ? <CheckCircle2 className="w-3.5 h-3.5" /> : 
             project.status === 'In Progress' ? <PlayCircle className="w-3.5 h-3.5" /> : 
             <Clock className="w-3.5 h-3.5" />}
            <span>{project.status}</span>
          </div>
          
          <div className="h-4 w-px bg-border/50 hidden sm:block" />
          
          <button 
            onClick={() => setIsDeleteDialogOpen(true)}
            className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-full transition-colors"
            title="Delete Project"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Workspace Body */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
        <WorkflowSidebar 
          project={project} 
          onStageSelect={handleStageSelect} 
          activeStageId={activeStageId} 
          orchestrationState={orchestrationState}
        />
        
        <WorkspaceContent 
          project={project}
          activeStage={activeStage}
          onAdvanceStage={handleAdvanceStage}
          onSelectStage={handleStageSelect}
          orchestrationState={orchestrationState}
          isOrchestrationLoading={isOrchestrationLoading}
          orchestrationError={orchestrationError}
          onOrchestrationRetry={handleRetryOrchestration}
          onOrchestrationUpdate={(newState) => {
            setOrchestrationState(newState);
            setOrchestrationError(null);
          }}
          onProjectRefresh={fetchProject}
          onOrchestrationRefresh={refreshOrchestration}
        />
      </div>

      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this project?</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-muted-foreground">
              Are you sure you want to permanently delete <strong>{getDisplayProjectTitle(project)}</strong>? This will permanently remove the project and all associated data, including generated content and source documents. This action cannot be undone.
            </p>
            {deleteError && (
              <div className="mt-4 p-3 bg-destructive/10 border border-destructive/20 text-destructive text-sm rounded-lg">
                {deleteError}
              </div>
            )}
          </div>
          <div className="flex justify-end gap-3 mt-4">
            <button
              type="button"
              className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-secondary/80 rounded-full transition-colors"
              onClick={() => setIsDeleteDialogOpen(false)}
              disabled={isDeleting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="px-4 py-2 text-sm font-medium text-destructive-foreground bg-destructive hover:bg-destructive/90 rounded-full transition-colors inline-flex items-center gap-2"
              onClick={handleDeleteProject}
              disabled={isDeleting}
            >
              {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              <span>{isDeleting ? 'Deleting...' : 'Delete Project'}</span>
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
