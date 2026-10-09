from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

class ProjectRepository:
    def __init__(self, session: AsyncSession, user_id: int):
        self.session = session
        self.user_id = user_id

    async def create(self, project_in: ProjectCreate) -> Project:
        db_obj = Project(**project_in.model_dump(), user_id=self.user_id)
        self.session.add(db_obj)
        await self.session.commit()
        return await self.get(db_obj.id)

    async def get(self, project_id: UUID) -> Optional[Project]:
        result = await self.session.execute(
            select(Project)
            .options(selectinload(Project.stages))
            .where(Project.id == project_id, Project.user_id == self.user_id)
            # Sessions use expire_on_commit=False, so without this an already-loaded (possibly
            # stale, e.g. empty right after creation) stages collection would be returned as-is.
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def get_multi(self, skip: int = 0, limit: int = 100) -> List[Project]:
        result = await self.session.execute(
            select(Project)
            .where(Project.user_id == self.user_id)
            .options(selectinload(Project.stages))
            .order_by(Project.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update(self, db_obj: Project, obj_in: ProjectUpdate) -> Project:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        
        self.session.add(db_obj)
        await self.session.commit()
        return await self.get(db_obj.id)

    async def delete(self, project_id: UUID) -> bool:
        obj = await self.get(project_id)
        if obj:
            await self.session.delete(obj)
            await self.session.commit()
            return True
        return False
