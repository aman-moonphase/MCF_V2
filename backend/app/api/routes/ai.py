from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List
from pydantic import BaseModel
from uuid import UUID

from ...db.session import get_db
from ...services.project_service import ProjectService
from ...services.workflow_stage_service import WorkflowStageService
from ...services.retrieval_service import RetrievalService
from ...ai.services.ai_orchestrator import AIOrchestrator
from ...ai.config import build_embedding_config
from ...ai.content_types import CONTENT_TYPES, normalize_content_type
from ...services.source_text_service import get_project_source_text
from ...services.strategy_service import StrategyService, project_uses_strategy
from ...api.deps import get_current_user
from ...models.user import User

router = APIRouter()


@router.get("/mode", response_model=Dict[str, Any])
async def get_ai_mode(current_user: User = Depends(get_current_user)):
    """Which AI mode generation actions will use, from configuration only. Contains no secrets, makes no
    external call, and never claims a verified connection."""
    from ...ai.config import claude_model_problem, normalize_provider_name
    from ...core.config import settings
    from ...ai.usage import CLAUDE_RATES

    provider = normalize_provider_name(settings.AI_PROVIDER)
    if provider == "demo":
        return {"mode": "demo", "provider": "demo", "model": None, "configured": True, "configuration_problem": None,
                "may_incur_charges": False, "connection_verified": False, "cost_estimates_available": False,
                "single_attempt": settings.AI_SINGLE_ATTEMPT}
    if provider == "claude":
        model = settings.CLAUDE_MODEL
        problem = (None if (settings.ANTHROPIC_API_KEY or "").strip() else "ANTHROPIC_API_KEY is not set.") or claude_model_problem(model)
        rates_known = model in CLAUDE_RATES
    elif provider == "openai":
        model = settings.AI_MODEL_NAME
        problem = None if (settings.OPENAI_API_KEY or "").strip() else "OPENAI_API_KEY is not set."
        rates_known = False
    else:
        model, problem, rates_known = None, f"Unsupported AI_PROVIDER '{provider}'.", False
    return {"mode": "real", "provider": provider, "model": model, "configured": problem is None,
            "configuration_problem": problem, "may_incur_charges": True, "connection_verified": False,
            "cost_estimates_available": rates_known, "single_attempt": settings.AI_SINGLE_ATTEMPT}
orchestrator = AIOrchestrator()


class ContentTypeRequest(BaseModel):
    project_id: str


class ContentSelectionRequest(BaseModel):
    project_id: str


class PlatformStrategyRequest(BaseModel):
    project_id: str
    opportunity_id: str


class TopicAngleRequest(BaseModel):
    project_id: str
    opportunity_id: str
    platform_ids: List[str]


class ContentStrategyRequest(BaseModel):
    project_id: str
    opportunity_id: str
    platform_ids: List[str]
    angle_id: str


class StoryboardRequest(BaseModel):
    project_id: str


class ScriptRequest(BaseModel):
    project_id: str


async def _load_source_text(db: AsyncSession, project) -> str:
    """The project's full ingested source text (never the 500-char source_reference preview)."""
    return await get_project_source_text(db, project)


async def _get_approved_content_type(stage_service: WorkflowStageService, project_uuid: UUID) -> str:
    """The approved content type — a hard constraint for every downstream stage."""
    try:
        content_type_stage = await stage_service.get_stage(project_uuid, "content-type")
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="Content type data not found. Complete Content Type first.")
        raise
    if not content_type_stage.data:
        raise HTTPException(status_code=400, detail="Content type data not found. Complete Content Type first.")

    raw_type = content_type_stage.data.get("approved_type") or content_type_stage.data.get("approvedType")
    if not raw_type:
        raise HTTPException(status_code=400, detail="No approved content type found. Please approve a content type first.")

    approved = normalize_content_type(raw_type)
    if not approved:
        raise HTTPException(
            status_code=400,
            detail=f"Approved content type '{raw_type}' is not supported. Supported: {', '.join(CONTENT_TYPES)}.",
        )
    return approved


async def _get_grounding_context(db: AsyncSession, project_uuid: UUID, query: str) -> dict:
    """Helper to perform retrieval and format it for the LangGraph state."""
    config = build_embedding_config()
    try:
        chunks = await RetrievalService.retrieve(db, project_uuid, query, config, top_k=5)
        if not chunks:
            return {}
        
        # Format the context text
        context_text = "\n\n---\n\n".join(
            f"[Source ID: {c.source_document_id}]\n{c.content}"
            for c in chunks
        )
        return {
            "query": query,
            "text": context_text,
            "sources": [{"id": c.source_document_id, "score": c.score} for c in chunks]
        }
    except Exception as e:
        # If RAG fails (e.g. pgvector not reachable in demo mode), fail gracefully
        return {"error": f"RAG retrieval failed: {str(e)}"}


@router.post("/content-type", response_model=Dict[str, Any])
async def generate_content_type(
    request: ContentTypeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)

    # Projects in the product workflow take their content type recommendation from the approved
    # Promotion Strategy, so the strategy and the generated content can never silently disagree.
    if await project_uses_strategy(db, project):
        strategy = await StrategyService(db, current_user.id).approved_strategy_for_project(project)
        if strategy is None:
            raise HTTPException(status_code=409, detail="Approve the Promotion Strategy before choosing the Content Type.")
        direction = strategy.strategy["content_direction"]
        return {
            "recommendation": {
                "recommendedType": direction["primary_content_type"],
                "alternatives": direction.get("alternatives") or [],
                "reasoning": direction.get("reason") or "",
                "sourceSignals": (direction.get("subject_areas") or [])[:5],
            },
            "from_strategy": True,
            "strategy_version": strategy.version,
        }

    source_text = await _load_source_text(db, project)

    grounding_context = await _get_grounding_context(
        db, project_uuid,
        query="What is the format and primary medium (e.g. video, article, short post) best suited for this source?"
    )

    try:
        result = await orchestrator.run_content_type(source_text, grounding_context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Content Type recommendation failed: {str(e)}")


@router.post("/content-selection", response_model=Dict[str, Any])
async def generate_content_selection(
    request: ContentSelectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)
    
    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query="What are the main themes, content opportunities, and target audiences in this material?"
    )

    stage_service = WorkflowStageService(db, current_user.id)
    
    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    try:
        result = await orchestrator.run_content_selection(source_text, approved_content_type, grounding_context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Content Selection failed: {str(e)}")


@router.post("/platform-strategy", response_model=Dict[str, Any])
async def generate_platform_strategy(
    request: PlatformStrategyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)

    stage_service = WorkflowStageService(db, current_user.id)
    
    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    content_selection_stage = await stage_service.get_stage(project_uuid, "content-selection")

    if not content_selection_stage.data:
        raise HTTPException(status_code=400, detail="Content selection data not found")

    opportunities = content_selection_stage.data.get("opportunities", [])
    selected_opp = next((o for o in opportunities if o.get("id") == request.opportunity_id), None)

    if not selected_opp:
        raise HTTPException(status_code=404, detail="Selected opportunity not found")

    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query=f"Which platforms (like YouTube, LinkedIn, Twitter, TikTok) are best suited for the content opportunity: '{selected_opp.get('title')}'?"
    )

    try:
        result = await orchestrator.run_platform_strategy(source_text, selected_opp, approved_content_type, grounding_context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Platform Strategy failed: {str(e)}")


@router.post("/topic-angle", response_model=Dict[str, Any])
async def generate_topic_angle(
    request: TopicAngleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)
    stage_service = WorkflowStageService(db, current_user.id)

    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    content_selection_stage = await stage_service.get_stage(project_uuid, "content-selection")
    if not content_selection_stage.data:
        raise HTTPException(status_code=400, detail="Content selection data not found")

    opportunities = content_selection_stage.data.get("opportunities", [])
    selected_opp = next((o for o in opportunities if o.get("id") == request.opportunity_id), None)
    if not selected_opp:
        raise HTTPException(status_code=404, detail="Selected opportunity not found")

    platform_strategy_stage = await stage_service.get_stage(project_uuid, "platform-strategy")
    if not platform_strategy_stage.data:
        raise HTTPException(status_code=400, detail="Platform strategy data not found")

    recommendations = platform_strategy_stage.data.get("recommendations", [])
    selected_platforms = [p for p in recommendations if p.get("id") in request.platform_ids]

    if not selected_platforms:
        raise HTTPException(status_code=404, detail="Selected platforms not found")

    platform_names = ", ".join([p.get('platform', '') for p in selected_platforms])
    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query=f"What are engaging topic angles and perspectives for '{selected_opp.get('title')}' targeted at {platform_names}?"
    )

    try:
        result = await orchestrator.run_topic_angle(source_text, selected_opp, selected_platforms, approved_content_type, grounding_context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Topic Angle failed: {str(e)}")


@router.post("/content-strategy", response_model=Dict[str, Any])
async def generate_content_strategy(
    request: ContentStrategyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)
    stage_service = WorkflowStageService(db, current_user.id)

    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    content_selection_stage = await stage_service.get_stage(project_uuid, "content-selection")
    if not content_selection_stage.data:
        raise HTTPException(status_code=400, detail="Content selection data not found")

    opportunities = content_selection_stage.data.get("opportunities", [])
    selected_opp = next((o for o in opportunities if o.get("id") == request.opportunity_id), None)
    if not selected_opp:
        raise HTTPException(status_code=404, detail="Selected opportunity not found")

    platform_strategy_stage = await stage_service.get_stage(project_uuid, "platform-strategy")
    if not platform_strategy_stage.data:
        raise HTTPException(status_code=400, detail="Platform strategy data not found")

    recommendations = platform_strategy_stage.data.get("recommendations", [])
    selected_platforms = [p for p in recommendations if p.get("id") in request.platform_ids]
    if not selected_platforms:
        raise HTTPException(status_code=404, detail="Selected platforms not found")

    topic_angle_stage = await stage_service.get_stage(project_uuid, "topic-angle")
    if not topic_angle_stage.data:
        raise HTTPException(status_code=400, detail="Topic angle data not found")

    angles = topic_angle_stage.data.get("angles", [])
    selected_angle = next((a for a in angles if a.get("id") == request.angle_id), None)
    if not selected_angle:
        raise HTTPException(status_code=404, detail="Selected topic angle not found")

    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query=f"What is the best content strategy, structure, and key talking points for the angle: '{selected_angle.get('title')}'?"
    )

    try:
        result = await orchestrator.run_content_strategy(
            source_text, selected_opp, selected_platforms, selected_angle, approved_content_type, grounding_context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Content Strategy failed: {str(e)}")


@router.post("/storyboard", response_model=Dict[str, Any])
async def generate_storyboard(
    request: StoryboardRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)
    stage_service = WorkflowStageService(db, current_user.id)

    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    try:
        cs_stage = await stage_service.get_stage(project_uuid, "content-selection")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'content-selection' not found. Complete Content Selection first.")
    if not cs_stage.data:
        raise HTTPException(status_code=400, detail="Content selection data is empty")

    opportunities = cs_stage.data.get("opportunities", [])
    selected_id = cs_stage.data.get("selectedId") or cs_stage.data.get("selected_id")
    selected_opp = next((o for o in opportunities if o.get("id") == selected_id), None)
    if not selected_opp and opportunities:
        selected_opp = opportunities[0]
    if not selected_opp:
        raise HTTPException(status_code=400, detail="No selected content opportunity found in content-selection stage")

    try:
        ps_stage = await stage_service.get_stage(project_uuid, "platform-strategy")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'platform-strategy' not found. Complete Platform Strategy first.")
    if not ps_stage.data:
        raise HTTPException(status_code=400, detail="Platform strategy data is empty")

    recommendations = ps_stage.data.get("recommendations", [])
    selected_platform_ids = ps_stage.data.get("selectedIds") or ps_stage.data.get("selected_ids") or []
    selected_platforms = [p for p in recommendations if p.get("id") in selected_platform_ids]
    if not selected_platforms and recommendations:
        selected_platforms = recommendations
    if not selected_platforms:
        raise HTTPException(status_code=400, detail="No platform recommendations found in platform-strategy stage")

    try:
        ta_stage = await stage_service.get_stage(project_uuid, "topic-angle")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'topic-angle' not found. Complete Topic & Angle first.")
    if not ta_stage.data:
        raise HTTPException(status_code=400, detail="Topic angle data is empty")

    angles = ta_stage.data.get("angles", [])
    selected_angle_id = ta_stage.data.get("selectedId") or ta_stage.data.get("selected_id")
    selected_angle = next((a for a in angles if a.get("id") == selected_angle_id), None)
    if not selected_angle and angles:
        selected_angle = angles[0]
    if not selected_angle:
        raise HTTPException(status_code=400, detail="No selected topic angle found in topic-angle stage")

    try:
        strat_stage = await stage_service.get_stage(project_uuid, "content-strategy")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'content-strategy' not found. Complete Content Strategy first.")
    if not strat_stage.data:
        raise HTTPException(status_code=400, detail="Content strategy data is empty")

    approved_strategy = strat_stage.data.get("strategy")
    if not approved_strategy:
        raise HTTPException(status_code=400, detail="No approved strategy found in content-strategy stage")

    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query=f"How should we visually storyboard the strategy for '{selected_angle.get('title')}'? What are the key visual directions and narrative flow?"
    )

    try:
        result = await orchestrator.run_storyboard(
            input_text=source_text,
            selected_opportunity=selected_opp,
            selected_platforms=selected_platforms,
            selected_angle=selected_angle,
            approved_strategy=approved_strategy,
            approved_content_type=approved_content_type,
            grounding_context=grounding_context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Storyboard generation failed: {str(e)}")


@router.post("/script", response_model=Dict[str, Any])
async def generate_script(
    request: ScriptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_uuid = UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(project_uuid)
    source_text = await _load_source_text(db, project)
    stage_service = WorkflowStageService(db, current_user.id)

    approved_content_type = await _get_approved_content_type(stage_service, project_uuid)

    try:
        cs_stage = await stage_service.get_stage(project_uuid, "content-selection")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'content-selection' not found. Complete Content Selection first.")
    if not cs_stage.data:
        raise HTTPException(status_code=400, detail="Content selection data is empty")

    opportunities = cs_stage.data.get("opportunities", [])
    selected_id = cs_stage.data.get("selectedId") or cs_stage.data.get("selected_id")
    selected_opp = next((o for o in opportunities if o.get("id") == selected_id), None)
    if not selected_opp and opportunities:
        selected_opp = opportunities[0]
    if not selected_opp:
        raise HTTPException(status_code=400, detail="No selected content opportunity found")

    try:
        ps_stage = await stage_service.get_stage(project_uuid, "platform-strategy")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'platform-strategy' not found. Complete Platform Strategy first.")
    if not ps_stage.data:
        raise HTTPException(status_code=400, detail="Platform strategy data is empty")

    recommendations = ps_stage.data.get("recommendations", [])
    selected_platform_ids = ps_stage.data.get("selectedIds") or ps_stage.data.get("selected_ids") or []
    selected_platforms = [p for p in recommendations if p.get("id") in selected_platform_ids]
    if not selected_platforms and recommendations:
        selected_platforms = recommendations
    if not selected_platforms:
        raise HTTPException(status_code=400, detail="No platform recommendations found")

    try:
        ta_stage = await stage_service.get_stage(project_uuid, "topic-angle")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'topic-angle' not found. Complete Topic & Angle first.")
    if not ta_stage.data:
        raise HTTPException(status_code=400, detail="Topic angle data is empty")

    angles = ta_stage.data.get("angles", [])
    selected_angle_id = ta_stage.data.get("selectedId") or ta_stage.data.get("selected_id")
    selected_angle = next((a for a in angles if a.get("id") == selected_angle_id), None)
    if not selected_angle and angles:
        selected_angle = angles[0]
    if not selected_angle:
        raise HTTPException(status_code=400, detail="No selected topic angle found")

    try:
        strat_stage = await stage_service.get_stage(project_uuid, "content-strategy")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'content-strategy' not found. Complete Content Strategy first.")
    if not strat_stage.data:
        raise HTTPException(status_code=400, detail="Content strategy data is empty")

    approved_strategy = strat_stage.data.get("strategy")
    if not approved_strategy:
        raise HTTPException(status_code=400, detail="No approved strategy found in content-strategy stage")

    try:
        sb_stage = await stage_service.get_stage(project_uuid, "storyboard")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Prerequisite stage 'storyboard' not found. Complete and approve the Storyboard first.")
    if not sb_stage.data:
        raise HTTPException(status_code=400, detail="Storyboard data is empty")

    approved_storyboard = sb_stage.data.get("storyboard")
    if not approved_storyboard:
        raise HTTPException(status_code=400, detail="No storyboard found in storyboard stage")

    storyboard_status = approved_storyboard.get("status", "")
    if storyboard_status != "Approved":
        raise HTTPException(status_code=400, detail=f"Storyboard must be approved before generating a script (current status: '{storyboard_status}'). Approve the storyboard first.")

    scenes = approved_storyboard.get("scenes", [])
    if not scenes:
        raise HTTPException(status_code=400, detail="Approved storyboard has no scenes")

    grounding_context = await _get_grounding_context(
        db, project_uuid, 
        query=f"What is the detailed narration and script for the storyboard scenes of '{selected_angle.get('title')}'?"
    )

    try:
        result = await orchestrator.run_script(
            input_text=source_text,
            selected_opportunity=selected_opp,
            selected_platforms=selected_platforms,
            selected_angle=selected_angle,
            approved_strategy=approved_strategy,
            approved_storyboard=approved_storyboard,
            approved_content_type=approved_content_type,
            grounding_context=grounding_context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Script generation failed: {str(e)}")

