from typing import List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.ai.content_types import CONTENT_TYPES, normalize_content_type
from app.ai.platform_policy import generation_support
from app.core.workflow import (LOCKED_STAGE_STATUS, is_known_stage, stage_order, stages_for, uses_product_workflow,
                               visible_stage_types)
from app.repositories.workflow_stage_repo import WorkflowStageRepository
from app.services.project_service import ProjectService
from app.schemas.workflow_stage import WorkflowStageCreate, WorkflowStageUpdate
from app.schemas.project import ProjectUpdate
from app.models.workflow_stage import WorkflowStage

_APPROVED_TYPE_KEYS = ("approved_type", "approvedType")


def _validate_stage_data(stage_type: str, stage_in: WorkflowStageUpdate) -> None:
    """Server-side guards for stage data that later stages depend on."""
    if stage_type != "content-type" or not isinstance(stage_in.data, dict):
        return
    for key in _APPROVED_TYPE_KEYS:
        value = stage_in.data.get(key)
        if value is None:
            continue
        canonical = normalize_content_type(value)
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{value}' is not a supported content type. Supported: {', '.join(CONTENT_TYPES)}.",
            )
        stage_in.data[key] = canonical


class WorkflowStageService:
    def __init__(self, session: AsyncSession, user_id: int):
        self.repo = WorkflowStageRepository(session)
        self.project_service = ProjectService(session, user_id)
        self.session = session

    async def create_or_update_stage(self, project_id: UUID, stage_type: str, stage_in: WorkflowStageUpdate) -> WorkflowStage:
        # Verify project exists
        project = await self.project_service.get_project(project_id)

        _validate_stage_data(stage_type, stage_in)
        await self._apply_strategy_to_content_type(project, stage_type, stage_in)
        await self._require_approved_post(project, stage_type, stage_in)
        await self._require_current_evaluation(project, stage_type, stage_in)
        existing_stage = await self.repo.get_by_project_and_type(project_id, stage_type)

        if existing_stage:
            updated_stage = await self.repo.update(existing_stage, stage_in)
        else:
            if not is_known_stage(stage_type):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown workflow stage '{stage_type}'.",
                )
            create_schema = WorkflowStageCreate(
                stage_type=stage_type,
                status=stage_in.status or LOCKED_STAGE_STATUS,
                data=stage_in.data
            )
            try:
                updated_stage = await self.repo.create(project_id, create_schema)
            except IntegrityError:
                # Another request created the same (project, stage) row concurrently; the unique
                # constraint rejected the duplicate, so update the row that now exists instead.
                await self.session.rollback()
                existing_stage = await self.repo.get_by_project_and_type(project_id, stage_type)
                updated_stage = await self.repo.update(existing_stage, stage_in)

        # Sync project current_stage if status is in progress
        if stage_in.status == 'In Progress' and project.current_stage != stage_type:
            await self.project_service.update_project(project_id, ProjectUpdate(current_stage=stage_type))

        return updated_stage

    async def _require_current_evaluation(self, project, stage_type: str, stage_in: WorkflowStageUpdate) -> None:
        """Product workflow with Evaluate & Improve: completing it, or entering Review Approval, needs an evaluation
        of the CURRENT saved post version. Projects without that stage (legacy, completed earlier) are unaffected."""
        leaving_evaluation = stage_type == "evaluate-improve" and stage_in.status == "Completed"
        entering_review = stage_type == "review-approval" and stage_in.status in ("In Progress", "Completed")
        if not (leaving_evaluation or entering_review):
            return
        from app.services.evaluation_service import require_current_evaluation

        problem = await require_current_evaluation(self.session, project)
        if problem:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problem)

    async def _require_approved_post(self, project, stage_type: str, stage_in: WorkflowStageUpdate) -> None:
        """Product workflow: Review Approval is only Completed by approving the saved post (never by a status change)."""
        if stage_type != "review-approval" or stage_in.status != "Completed":
            return
        existing = {s.stage_type for s in await self.repo.get_all_by_project(project.id)}
        if not uses_product_workflow(existing):
            return  # legacy projects keep their generic approve step
        from app.services.generation_service import GenerationService

        if not await GenerationService(self.session, self.project_service.repo.user_id).has_current_approval(project):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Approve the saved post in Review Approval before completing this stage.")

    async def _apply_strategy_to_content_type(self, project, stage_type: str, stage_in: WorkflowStageUpdate) -> None:
        """For product-workflow projects, the content type can only be approved after the Promotion Strategy.
        Choosing a different type than the strategy recommends is allowed, but recorded explicitly."""
        if stage_type != "content-type" or not isinstance(stage_in.data, dict):
            return
        approved = stage_in.data.get("approved_type") or stage_in.data.get("approvedType")
        if not approved:
            return
        from app.services.strategy_service import StrategyService, project_uses_strategy

        if not await project_uses_strategy(self.session, project):
            return
        strategy = await StrategyService(self.session, self.project_service.repo.user_id).approved_strategy_for_project(project)
        if strategy is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Approve the Promotion Strategy before approving the Content Type.")
        recommended = strategy.strategy["content_direction"]["primary_content_type"]
        stage_in.data["strategy_recommended_type"] = recommended
        stage_in.data["strategy_version"] = strategy.version
        stage_in.data["overrides_strategy"] = approved != recommended
        # Any of the six types may be chosen; only some can be generated in this version (platform_policy).
        stage_in.data["generation_supported"] = generation_support(approved) is None

    async def get_stages(self, project_id: UUID) -> List[WorkflowStage]:
        # Verify project exists
        await self.project_service.get_project(project_id)
        stages = await self.repo.get_all_by_project(project_id)
        visible = visible_stage_types([stage.stage_type for stage in stages])
        return sorted((s for s in stages if s.stage_type in visible), key=lambda stage: stage_order(stage.stage_type))

    async def get_stage(self, project_id: UUID, stage_type: str) -> WorkflowStage:
        await self.project_service.get_project(project_id)
        stage = await self.repo.get_by_project_and_type(project_id, stage_type)
        if not stage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow stage not found")
        return stage

    async def ensure_project_stages(self, project_id: UUID) -> List[WorkflowStage]:
        """Create any stage rows of the project's workflow it is missing (as Locked). Idempotent.

        For use by data migrations when a new stage is added to WORKFLOW_STAGES. A legacy project
        only gets legacy stages; a product-workflow project only gets product-workflow stages.
        """
        await self.project_service.get_project(project_id)
        existing = {stage.stage_type for stage in await self.repo.get_all_by_project(project_id)}
        for stage in stages_for(existing):
            if stage.key not in existing:
                await self.repo.create(project_id, WorkflowStageCreate(stage_type=stage.key, status=LOCKED_STAGE_STATUS))
        return await self.get_stages(project_id)
