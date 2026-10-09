import { Project, ProjectStatus, WorkflowStage, CreateProjectInput } from '../types/project';
import { toast } from 'sonner';
import { apiClient } from './api-client';
import { errorFromResponse } from './api-errors';

export const ProjectService = {
  getProjects: async (): Promise<Project[]> => {
    try {
      const projects = await apiClient.get('/projects');
      return projects.map((p: any) => ({
        ...p,
        stages: p.stages?.map((s: any) => ({ ...s, type: s.stageType || s.type }))
      }));
    } catch (e) {
      console.error("Failed to fetch projects", e);
      return [];
    }
  },

  getProject: async (id: string): Promise<Project | undefined> => {
    try {
      const p = await apiClient.get(`/projects/${id}`);
      return {
        ...p,
        stages: p.stages?.map((s: any) => ({ ...s, type: s.stageType || s.type }))
      };
    } catch (e) {
      console.error(`Failed to fetch project ${id}`, e);
      return undefined;
    }
  },

  createProject: async (input: CreateProjectInput): Promise<Project> => {
    const p = await apiClient.post('/projects', input);
    return {
      ...p,
      stages: p.stages?.map((s: any) => ({ ...s, type: s.stageType || s.type }))
    };
  },

  updateProjectStatus: async (id: string, status: ProjectStatus): Promise<Project | null> => {
    try {
      const p = await apiClient.patch(`/projects/${id}`, { status });
      return {
        ...p,
        stages: p.stages?.map((s: any) => ({ ...s, type: s.stageType || s.type }))
      };
    } catch (e) {
      console.error(`Failed to update project status ${id}`, e);
      toast.error(`Could not update the project status: ${e instanceof Error ? e.message : String(e)}`);
      return null;
    }
  },

  deleteProject: async (id: string): Promise<boolean> => {
    try {
      await apiClient.delete(`/projects/${id}`);
      return true;
    } catch (e) {
      console.error(`Failed to delete project ${id}`, e);
      toast.error(`Could not delete the project: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    }
  },

  updateWorkflowStage: async (projectId: string, stageId: string, updates: Partial<WorkflowStage>): Promise<Project | null> => {
    try {
      // Find the stage type from the stageId if needed, but since we need stage_type for the backend API,
      // and we might only have stageId or stageType. Wait, the frontend might be passing stageId.
      // Let's check how the backend expects it.
      // @router.patch("/{project_id}/stages/{stage_type}")
      // This means we need the stage_type, not the stage_id.
      
      // We will need to fetch the project first to find the stage type if not provided, OR we can change the API
      // Actually, if we look at the frontend, `activeStage.id` was used previously, but `activeStage.type` is what the backend expects.
      // Let's change the parameter to accept stageType instead of stageId, or resolve it.
      // It's safer to fetch the project if we only have stageId, but we know the type from the components.
      // Wait, let's look at how updateWorkflowStage is called in components:
      // ProjectService.updateWorkflowStage(project.id, activeStage.id, { status: 'Completed', data: {...} })
      // Since it's passing `activeStage.id`, we need to map `id` to `type`.
      const project = await apiClient.get(`/projects/${projectId}`);
      const stage = project.stages.find((s: WorkflowStage) => s.id === stageId);
      if (!stage) return null;

      // Now call the backend with stage.type
      await apiClient.patch(`/projects/${projectId}/stages/${stage.type || stage.stageType}`, updates);
      
      // Return the updated project since components expect the updated project.
      const updatedP = await apiClient.get(`/projects/${projectId}`);
      return {
        ...updatedP,
        stages: updatedP.stages?.map((s: any) => ({ ...s, type: s.stageType || s.type }))
      };
    } catch (e) {
      console.error(`Failed to update workflow stage`, e);
      toast.error(`Could not save your changes: ${e instanceof Error ? e.message : String(e)}`);
      return null;
    }
  },

  ingestSource: async (projectId: string, formData: FormData): Promise<any> => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      
      const response = await fetch(`${API_BASE}/projects/${projectId}/sources/ingest`, {
        method: 'POST',
        headers,
        body: formData,
      });
      if (!response.ok) {
        const error = await errorFromResponse(response);
        throw new Error(`Failed to ingest source: ${error.message}`);
      }
      return await response.json();
    } catch (e) {
      console.error(`Failed to ingest source for project ${projectId}`, e);
      throw e;
    }
  }
};
