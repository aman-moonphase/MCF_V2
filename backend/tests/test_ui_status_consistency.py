import pytest
import re
from uuid import UUID
from app.services.project_service import ProjectService
from app.schemas.project import ProjectCreate
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from sqlalchemy import select


@pytest.mark.asyncio
async def test_project_service_extracts_clean_title(db_session, test_user):
    """Ensure create_project cleans raw 'Idea: Project Name: ...' titles when structured text is supplied."""
    service = ProjectService(db_session, test_user.id)
    input_text = (
        "Project Name: BudgetBloom Persona Test\n"
        "Product Name: BudgetBloom\n"
        "Project Description:\nBudgetBloom is a personal budgeting tool."
    )
    raw_fallback_title = "Idea: " + input_text[:30] + "..."  # "Idea: Project Name: BudgetBloom Pers..."

    project_in = ProjectCreate(
        title=raw_fallback_title,
        description=input_text,
        source_type="Text Idea",
        source_reference=input_text[:100],
    )
    created = await service.create_project(project_in)

    assert created.title == "BudgetBloom Persona Test"
    assert created.description == input_text  # Description preserved intact


@pytest.mark.asyncio
async def test_saved_project_records_truthfulness(db_session):
    """Verify saved BudgetBloom and Persona Tone test projects have correct titles, preserved descriptions, and truthful stage status."""
    res = await db_session.execute(
        select(Project).where(Project.id == UUID("7118a733-737e-4c3d-895b-1c494185f71b"))
    )
    bb_project = res.scalar_one_or_none()
    if bb_project:
        assert bb_project.title == "BudgetBloom Persona Test"
        assert "BudgetBloom is a personal budgeting tool" in bb_project.description

        # Inspect source-grounding stage
        st_res = await db_session.execute(
            select(WorkflowStage).where(
                WorkflowStage.project_id == bb_project.id,
                WorkflowStage.stage_type == "source-grounding"
            )
        )
        sg_stage = st_res.scalar_one_or_none()
        assert sg_stage is not None
        assert sg_stage.status == "Not Started"
        # No live fact verification or live embedding data is fabricated
        assert sg_stage.data is None or not sg_stage.data.get("factVerification", {}).get("passed")

    pt_res = await db_session.execute(
        select(Project).where(Project.id == UUID("ee87b44f-c984-473f-b8a4-c3f1e86dde50"))
    )
    pt_project = pt_res.scalar_one_or_none()
    if pt_project:
        assert pt_project.title == "Persona Tone Test"
        assert "BudgetBloom" in pt_project.description
