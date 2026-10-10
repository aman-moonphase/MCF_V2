"""Evaluate & Improve: evaluate the SAVED post version against its approved context, keep the history, and gate
Review Approval on a current evaluation.

- Read-only towards content: the post, its version, validation, usage and approval are never changed here.
- Every evaluation is a new row tied to the exact post version evaluated (history is kept).
- "Current" means the latest evaluation's version equals the post's version; a saved edit or regeneration bumps
  the version, so the previous evaluation becomes stale automatically and re-evaluation is required.
- Applies to product-workflow projects that have the Evaluate & Improve stage. Projects completed before the stage
  existed, and legacy projects, are untouched (not applicable).
- No AI call: the evaluator is the deterministic rule-based one (app/ai/evaluation).
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.evaluation import EvaluationContext, get_evaluator
from app.ai.generation_validation import validate_post
from app.ai.platform_policy import platform_policy
from app.core.workflow import uses_product_workflow
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.source import DocumentChunk, SourceDocument
from app.services.retrieval_service import is_stale, source_hashes
from app.models.workflow_stage import WorkflowStage
from app.services.generation_service import _PROFILE_SKIP, GenerationService, competitor_findings

STAGE_KEY = "evaluate-improve"


def _summary(e: ContentEvaluation) -> Dict[str, Any]:
    return {"id": e.id, "content_version": e.content_version, "overall": e.overall,
            "overall_label": (e.result.get("overall") or {}).get("label"), "counts": e.result.get("counts"),
            "evaluator": e.evaluator, "mode": e.mode, "created_at": e.created_at}


async def latest_evaluation(db: AsyncSession, draft: GeneratedContent) -> Optional[ContentEvaluation]:
    return (await db.execute(select(ContentEvaluation).where(ContentEvaluation.generated_content_id == draft.id)
                             .order_by(ContentEvaluation.created_at.desc()).limit(1))).scalar_one_or_none()


async def evaluation_problem(db: AsyncSession, project: Project, stages: Dict[str, WorkflowStage],
                             draft: Optional[GeneratedContent]) -> Optional[str]:
    """Why the project may not proceed to Review Approval, or None. Only projects with the Evaluate & Improve
    stage are gated; others (legacy, or completed before the stage existed) are unaffected."""
    if STAGE_KEY not in stages:
        return None
    if draft is None:
        return "There is no saved post to evaluate yet."
    latest = await latest_evaluation(db, draft)
    if latest is None:
        return f"Evaluate the saved post (version {draft.version}) in Evaluate & Improve first."
    if latest.content_version != draft.version:
        return (f"The saved post changed to version {draft.version} after it was evaluated (version {latest.content_version}). "
                "Re-evaluate it in Evaluate & Improve first.")
    return None


class EvaluationService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.generation = GenerationService(db, user_id)

    async def _load(self, project_id: UUID):
        project, stages = await self.generation.get_project(project_id)  # 404 unless owned
        draft = await self.generation.get_draft(project)
        return project, stages, draft

    @staticmethod
    def _applicable(stages: Dict[str, WorkflowStage]) -> Optional[str]:
        if not uses_product_workflow(stages):
            return "Evaluate & Improve is part of the product workflow; this project uses the legacy workflow."
        if STAGE_KEY not in stages:
            return "This project was completed before Evaluate & Improve existed; its approved content is left as it is."
        return None

    async def _context(self, project: Project, draft: GeneratedContent) -> EvaluationContext:
        product = await self.generation.products.get_product(draft.product_id)
        strategy = await self.generation.strategies.get_strategy(product)
        snapshot = draft.context_snapshot or {}
        allowed, corpus, meta = await self.generation.saved_validation_inputs(project, product, draft)
        validation = validate_post(dict(draft.content), allowed, corpus, meta, platform_policy())
        plan = strategy.strategy if strategy else {}
        audience = plan.get("audience") or {}
        comparison = (product.competitor_comparison
                      if product.competitor_comparison_version == product.competitor_version else None)
        competitor_current = (product.competitor_analysis_status == "approved" and not product.competitor_limited_evidence
                              and product.competitor_approved_version == product.competitor_version and bool(comparison))
        ready = await self.generation.readiness(project, await self.generation._stages(project))
        return EvaluationContext(
            post=dict(draft.content), version=draft.version, edited=bool(draft.edited),
            product_name=meta.get("product_name") or product.name,
            profile={k: v for k, v in (product.profile or {}).items() if v and k not in _PROFILE_SKIP},
            pillar_name=snapshot.get("pillar") or draft.content.get("pillar") or "",
            pillar=meta.get("pillar_detail"),
            strategy={"primary_audience": audience.get("primary_audience"),
                      "value_proposition": audience.get("value_proposition"),
                      "messaging_direction": audience.get("messaging_direction"),
                      "differentiators": audience.get("differentiators")},
            competitor=competitor_findings(comparison) if competitor_current else None,
            competitor_limited=bool(product.competitor_limited_evidence),
            excerpts=await self._excerpt_status(project, snapshot),
            validation=validation, evidence=snapshot.get("evidence") or {},
            stale_reasons=self.generation.stale_reasons(draft, ready["product"], ready["strategy"], ready["approved_type"]),
            policy=platform_policy(),
        )

    async def _excerpt_status(self, project: Project, snapshot: dict) -> Dict[str, Dict[str, Any]]:
        """For each retrieved excerpt the post cited: is it still the same text in a current source of THIS project?"""
        statuses: Dict[str, Dict[str, Any]] = {}
        for ref, meta in (snapshot.get("evidence_meta") or {}).items():
            row = (await self.db.execute(
                select(DocumentChunk, SourceDocument)
                .join(SourceDocument, SourceDocument.id == DocumentChunk.source_document_id)
                .where(DocumentChunk.project_id == project.id, SourceDocument.project_id == project.id,
                       DocumentChunk.source_document_id == UUID(meta["source_document_id"]),
                       DocumentChunk.chunk_index == meta["chunk_index"]))).first()
            if row is None or row[1].status != "completed":
                statuses[ref] = {"status": "missing", "content": ""}
                continue
            chunk, doc = row
            chunk_meta = chunk.metadata_ or {}
            changed = ((meta.get("content_hash") and chunk_meta.get("content_hash") != meta["content_hash"])
                       or is_stale(chunk_meta, source_hashes(doc)))
            statuses[ref] = {"status": "changed" if changed else "current", "content": chunk.content}
        return statuses

    async def evaluate(self, project_id: UUID, version: int) -> ContentEvaluation:
        project, stages, draft = await self._load(project_id)
        reason = self._applicable(stages)
        if reason:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
        if draft is None:
            raise HTTPException(status_code=409, detail="There is no saved post to evaluate. Generate one first.")
        if version != draft.version:
            raise HTTPException(status_code=409, detail=f"The saved post is now version {draft.version}. Reload and evaluate "
                                                        "the current version.")
        evaluator = get_evaluator()
        result = evaluator.evaluate(await self._context(project, draft))
        evaluation = ContentEvaluation(generated_content_id=draft.id, project_id=project.id, content_version=draft.version,
                                       evaluator=evaluator.name, mode=evaluator.mode, overall=result["overall"]["level"],
                                       result=result)
        self.db.add(evaluation)
        await self.db.flush()
        stage = stages[STAGE_KEY]
        stage.data = {**(stage.data or {}), "evaluation_id": str(evaluation.id), "content_version": draft.version,
                      "overall": evaluation.overall}
        await self.db.commit()
        return evaluation

    async def state(self, project_id: UUID) -> Dict[str, Any]:
        project, stages, draft = await self._load(project_id)
        evaluator = get_evaluator()
        base: Dict[str, Any] = {"project_id": project.id, "evaluator": {"name": evaluator.name, "mode": evaluator.mode}}
        reason = self._applicable(stages)
        if reason:
            return {**base, "status": "not_applicable", "reason": reason, "can_proceed": True, "history": []}
        if draft is None:
            return {**base, "status": "no_draft", "reason": "Generate and save a post first.", "can_proceed": False, "history": []}
        history: List[ContentEvaluation] = list((await self.db.execute(
            select(ContentEvaluation).where(ContentEvaluation.generated_content_id == draft.id)
            .order_by(ContentEvaluation.created_at.desc()))).scalars().all())
        latest = history[0] if history else None
        if latest is None:
            status_, reason = "not_evaluated", f"Version {draft.version} has not been evaluated yet."
        elif latest.content_version != draft.version:
            status_, reason = "stale", (f"This evaluation is for version {latest.content_version}; the saved post is now "
                                        f"version {draft.version}. Re-evaluate it.")
        else:
            status_, reason = "current", None
        return {
            **base, "status": status_, "reason": reason, "can_proceed": status_ == "current",
            "draft": {"id": draft.id, "version": draft.version, "status": draft.status, "edited": draft.edited,
                      "is_demo": draft.is_demo, "provider": draft.provider},
            "evaluation": ({**_summary(latest), "result": latest.result} if latest else None),
            "history": [_summary(e) for e in history],
        }


async def require_current_evaluation(db: AsyncSession, project: Project) -> Optional[str]:
    """For stage transitions: the reason Review Approval may not be entered yet, or None."""
    rows = (await db.execute(select(WorkflowStage).where(WorkflowStage.project_id == project.id))).scalars().all()
    stages = {r.stage_type: r for r in rows}
    if STAGE_KEY not in stages:
        return None
    draft = (await db.execute(select(GeneratedContent).where(GeneratedContent.project_id == project.id)
                              .order_by(GeneratedContent.created_at.desc()).limit(1))).scalar_one_or_none()
    return await evaluation_problem(db, project, stages, draft)
