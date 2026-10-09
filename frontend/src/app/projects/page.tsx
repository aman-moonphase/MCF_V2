"use client"

import React, { useEffect, useState } from 'react';
import { ProjectService } from '@/lib/project-service';
import { toast } from 'sonner';
import { Project } from '@/types/project';
import { ProjectCard } from '@/components/projects/project-card';
import { Search, Plus, Filter, LayoutGrid, Trash2, Loader2 } from 'lucide-react';
import Link from 'next/link';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('All');
  const [isLoading, setIsLoading] = useState(true);
  
  // Delete project state
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDeleteProject = async () => {
    if (!projectToDelete || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const success = await ProjectService.deleteProject(projectToDelete.id);
      if (success) {
        setProjects(projects.filter(p => p.id !== projectToDelete.id));
        setProjectToDelete(null);
        toast.success('Project deleted');
      } else {
        setDeleteError('Failed to delete project. Please try again.');
      }
    } catch (e) {
      setDeleteError('An unexpected error occurred.');
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    const fetchProjects = async () => {
      const loadedProjects = await ProjectService.getProjects();
      setProjects(loadedProjects);
      setIsLoading(false);
    };
    fetchProjects();
  }, []);

  const filteredProjects = projects.filter(p => {
    const matchesSearch = p.title.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          p.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'All' || p.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="flex-1 flex flex-col w-full max-w-7xl mx-auto px-4 sm:px-6 md:px-8 py-4 relative z-10">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 mb-10">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-foreground mb-2">Projects</h1>
          <p className="text-muted-foreground">Manage and track your multimodal content workflows.</p>
        </div>
        <Link 
          href="/" 
          className="inline-flex items-center justify-center gap-2 h-11 px-6 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-sm shrink-0"
        >
          <Plus className="w-4 h-4" />
          <span>New Project</span>
        </Link>
      </div>

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-4 mb-8 bg-white dark:bg-card border border-slate-200 dark:border-border shadow-sm p-2 rounded-2xl sm:rounded-full">
        <div className="relative flex-1">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <Search className="w-4 h-4 text-muted-foreground" />
          </div>
          <input 
            type="text" 
            placeholder="Search projects..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 h-11 bg-transparent border-none focus:outline-none focus:ring-0 text-foreground placeholder:text-muted-foreground text-sm"
          />
        </div>
        <div className="hidden sm:block w-px h-6 bg-slate-200 dark:bg-border self-center" />
        <div className="flex items-center gap-2 px-2 pb-2 sm:pb-0 overflow-x-auto no-scrollbar">
          {['All', 'Draft', 'In Progress', 'Needs Review', 'Completed'].map(status => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`whitespace-nowrap px-4 h-9 rounded-full text-sm font-medium transition-colors ${
                statusFilter === status 
                  ? 'bg-slate-900 text-white dark:bg-foreground dark:text-background shadow-sm' 
                  : 'text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-muted hover:text-slate-900 dark:hover:text-foreground'
              }`}
            >
              {status}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center min-h-[40vh]">
          <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        </div>
      ) : filteredProjects.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProjects.map(project => (
            <ProjectCard 
              key={project.id} 
              project={project} 
              onDelete={(p) => setProjectToDelete(p)}
            />
          ))}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-12 bg-slate-50 dark:bg-muted/30 rounded-3xl border-dashed border-2 border-slate-200 dark:border-border/50 min-h-[40vh]">
          <div className="h-16 w-16 bg-white dark:bg-card border border-slate-200 dark:border-border shadow-sm rounded-full flex items-center justify-center mb-6">
            <LayoutGrid className="w-8 h-8 text-slate-400 dark:text-muted-foreground" />
          </div>
          <h3 className="text-xl font-semibold mb-2">No projects found</h3>
          <p className="text-muted-foreground mb-8 max-w-md">
            {searchQuery 
              ? "We couldn't find any projects matching your search or filter criteria."
              : "You haven't created any projects yet. Start a new workflow from the Create page."}
          </p>
          {searchQuery || statusFilter !== 'All' ? (
            <button 
              onClick={() => { setSearchQuery(''); setStatusFilter('All'); }}
              className="text-primary font-medium hover:underline"
            >
              Clear filters
            </button>
          ) : (
            <Link 
              href="/" 
              className="inline-flex items-center justify-center h-11 px-6 rounded-full bg-primary text-primary-foreground font-medium hover:scale-[1.02] active:scale-95 transition-all shadow-sm"
            >
              Start New Project
            </Link>
          )}
        </div>
      )}

      <Dialog open={!!projectToDelete} onOpenChange={(open) => !open && setProjectToDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this project?</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-sm text-muted-foreground">
              Are you sure you want to permanently delete <strong>{projectToDelete?.title}</strong>? This will permanently remove the project and all associated data, including generated content and source documents. This action cannot be undone.
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
              onClick={() => setProjectToDelete(null)}
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
