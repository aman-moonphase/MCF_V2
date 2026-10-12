from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.workflow import initial_status, product_workflow_stages
from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.models.project import Project
from app.repositories.workflow_stage_repo import WorkflowStageRepository
from app.schemas.workflow_stage import WorkflowStageCreate

class ProjectService:
    def __init__(self, session: AsyncSession, user_id: int):
        self.repo = ProjectRepository(session, user_id)

    async def create_project(self, project_in: ProjectCreate) -> Project:
        if not project_in.title.strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be empty")

        if project_in.title.startswith("Idea: Project Name") or project_in.title.startswith("Idea: Title") or (project_in.title.startswith("Idea: ") and "Project Name:" in project_in.title):
            if project_in.description:
                import re
                match = re.search(r"^\s*(?:Project\s*Name|Project\s*Title|Title)\s*:\s*([^\r\n]+)", project_in.description, re.MULTILINE | re.IGNORECASE)
                if match and match.group(1).strip():
                    project_in.title = match.group(1).strip()

        project = await self.repo.create(project_in)

        stage_repo = WorkflowStageRepository(self.repo.session)
        # One row per stage of the product workflow (app/core/workflow.py). Legacy-only stages
        # (content-selection … final-script) are not created for new projects.
        for index, stage in enumerate(product_workflow_stages()):
            stage_in = WorkflowStageCreate(stage_type=stage.key, status=initial_status(index))
            await stage_repo.create(project.id, stage_in)

        return await self.repo.get(project.id)

    async def get_project(self, project_id: UUID) -> Project:
        project = await self.repo.get(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    async def get_projects(self, skip: int = 0, limit: int = 100) -> List[Project]:
        return await self.repo.get_multi(skip=skip, limit=limit)

    async def update_project(self, project_id: UUID, obj_in: ProjectUpdate) -> Project:
        project = await self.get_project(project_id)
        if obj_in.title is not None and not obj_in.title.strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be empty")
        return await self.repo.update(project, obj_in)

    async def delete_project(self, project_id: UUID) -> bool:
        project = await self.get_project(project_id)
        return await self.repo.delete(project.id)
