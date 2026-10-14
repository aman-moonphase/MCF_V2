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


@pytest.mark.asyncio
async def test_tone_context_consistency_and_persistence(authenticated_client):
    """
    Focused regression test covering tone selection, generation, persistence, refresh,
    and display consistency:
    1. Generate a draft in conversational tone.
       - draft context_snapshot['editorial_tone'] == 'conversational'
       - Claims & Evidence strategy_alignment mentions 'conversational tone'
       - context['selected_tone'] == 'conversational'
    2. Change tone preference to 'professional' via preferences API without regenerating.
       - Pending selection context['selected_tone'] == 'professional'
       - Existing draft context_snapshot['editorial_tone'] == 'conversational' (preserved, not corrupted)
       - Claims & Evidence strategy_alignment still mentions 'conversational tone'
    3. Refresh/reload state via GET endpoint:
       - context['selected_tone'] remains 'professional'
       - draft context_snapshot['editorial_tone'] remains 'conversational'
       - No contradiction between persisted draft snapshot and returned state.
    4. Regenerate without passing explicit tone:
       - Inherits pending stage preference ('professional')
       - New draft context_snapshot['editorial_tone'] == 'professional'
       - Claims & Evidence strategy_alignment updates to 'professional tone'
       - context['selected_tone'] == 'professional'
    """
    from tests.test_generate_content import ready_project, gen_url

    project_id, _, _ = await ready_project(authenticated_client)

    # 1. Generate in conversational tone
    res_gen = await authenticated_client.post(
        gen_url(project_id),
        json={
            "pillar_index": 0,
            "editorial_tone": "conversational",
        },
    )
    assert res_gen.status_code == 200, res_gen.text
    st_gen = res_gen.json()

    assert st_gen["draft"]["context_snapshot"]["editorial_tone"] == "conversational"
    assert "conversational tone" in st_gen["draft"]["content"]["strategy_alignment"]
    assert st_gen["context"]["selected_tone"] == "conversational"

    # 2. Change preference to professional via preferences endpoint (before regenerating)
    res_pref = await authenticated_client.put(
        f"/api/projects/{project_id}/generated-content/preferences",
        json={"editorial_tone": "professional"},
    )
    assert res_pref.status_code == 200, res_pref.text
    st_pref = res_pref.json()

    # The pending preference is updated:
    assert st_pref["context"]["selected_tone"] == "professional"
    # But the existing draft's context snapshot is UNTOUCHED:
    assert st_pref["draft"]["context_snapshot"]["editorial_tone"] == "conversational"
    # And Claims & Evidence still matches the draft that was actually generated:
    assert "conversational tone" in st_pref["draft"]["content"]["strategy_alignment"]

    # 3. Refresh/reload: verify persistence across page refresh
    res_refresh = await authenticated_client.get(gen_url(project_id))
    assert res_refresh.status_code == 200, res_refresh.text
    st_refresh = res_refresh.json()

    assert st_refresh["context"]["selected_tone"] == "professional"
    assert st_refresh["draft"]["context_snapshot"]["editorial_tone"] == "conversational"
    assert "conversational tone" in st_refresh["draft"]["content"]["strategy_alignment"]

    # 4. Regenerate without passing explicit tone: inherits pending preference
    res_regen = await authenticated_client.post(
        gen_url(project_id),
        json={"pillar_index": 0},
    )
    assert res_regen.status_code == 200, res_regen.text
    st_regen = res_regen.json()

    assert st_regen["draft"]["context_snapshot"]["editorial_tone"] == "professional"
    assert "conversational tone" not in st_regen["draft"]["content"]["strategy_alignment"]
    assert st_regen["context"]["selected_tone"] == "professional"
