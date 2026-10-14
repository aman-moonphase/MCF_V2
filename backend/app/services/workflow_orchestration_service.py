"""Workflow Orchestration Service: Connects existing domain services into the stateful LangGraph pipeline.

Preserves all safety rules:
- No automatic human approval or social posting (execution pauses at the review boundary).
- Exact version matching for evaluation.
- Full claim and citation traceability (P:*, S*).
- Safe prerequisite gating.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graphs.product_workflow_graph import ProductWorkflowState, get_product_workflow_graph
from app.ai.platform_policy import MVP_CONTENT_TYPE
from app.core.redaction import redact
from app.core.workflow import uses_product_workflow
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from app.services.competitor_service import CompetitorService
from app.services.evaluation_service import EvaluationService, latest_evaluation, evaluation_problem
from app.services.generation_service import GenerationService, STAGE_KEY as GEN_STAGE_KEY, REVIEW_STAGE_KEY
from app.services.product_service import ProductService
from app.services.source_text_service import get_project_source_texts
from app.services.strategy_service import StrategyService


class WorkflowOrchestrationService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.products = ProductService(db, user_id)
        self.competitors = CompetitorService(db, user_id)
        self.strategies = StrategyService(db, user_id)
        self.generation = GenerationService(db, user_id)
        self.evaluation = EvaluationService(db, user_id)

    async def _get_project_and_stages(self, project_id: UUID) -> tuple[Project, Dict[str, WorkflowStage]]:
        project, stages = await self.generation.get_project(project_id)
        if not uses_product_workflow(stages):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Workflow orchestration applies to product-workflow projects.",
            )
        return project, stages

    async def get_state(self, project_id: UUID) -> ProductWorkflowState:
        """Inspects current database records and returns a full ProductWorkflowState snapshot."""
        project, stages = await self._get_project_and_stages(project_id)

        # 1. Sources & Evidence
        sources = await get_project_source_texts(self.db, project)
        source_evidence = {f"S{i + 1}": name for i, (name, _) in enumerate(sources)}

        # 2. Product
        product: Optional[Product] = None
        if project.product_id:
            try:
                product = await self.products.get_product(project.product_id)
            except HTTPException:
                product = None

        profile = product.profile if product else None
        profile_version = product.profile_version if product else None
        profile_approved = bool(
            product
            and product.understanding_status == "approved"
            and product.approved_version == product.profile_version
        )

        # 3. Competitor Analysis
        comp_comparison = product.competitor_comparison if product else None
        comp_version = product.competitor_version if product else None
        comp_approved_version = product.competitor_approved_version if product else None
        comp_limited = bool(product and product.competitor_limited_evidence)
        competitors_approved = bool(
            product
            and product.competitor_analysis_status == "approved"
            and (comp_limited or (comp_approved_version == comp_version and comp_comparison))
        )

        # 4. Promotion Strategy
        # The CURRENT strategy (draft or approved), so a person's unapproved edits are never mistaken for "no strategy"
        # and regenerated over. It only counts as approved when it is the approved, current version.
        strategy = await self.strategies.get_strategy(product) if product else None
        approved_strategy = await self.strategies.approved_strategy_for_project(project) if product else None
        strat_dict = strategy.strategy if strategy else None
        strat_version = strategy.version if strategy else None
        strategy_approved = approved_strategy is not None
        pillars = (strat_dict.get("content_pillars") if strat_dict else []) or []

        # 5. Content Generation
        draft = await self.generation.get_draft(project)
        post_content = dict(draft.content) if draft and draft.content else None
        content_version = draft.version if draft else None
        claims_traceability: List[Dict[str, Any]] = []
        if post_content and "claims" in post_content:
            for c in post_content.get("claims") or []:
                if isinstance(c, dict):
                    claims_traceability.append({
                        "text": c.get("text", ""),
                        "kind": c.get("kind", "product_fact"),
                        "refs": c.get("refs", []),
                    })

        # 6. Evaluation
        latest_eval = await latest_evaluation(self.db, draft) if draft else None
        eval_dict = latest_eval.result if latest_eval else None
        eval_version = latest_eval.content_version if latest_eval else None
        eval_current = bool(latest_eval and draft and latest_eval.content_version == draft.version)

        # 7. Human Review
        review_approved = await self.generation.has_current_approval(project)
        approved_version = draft.approved_version if (draft and review_approved) else None
        approved_at = draft.approved_at.isoformat() if (draft and draft.approved_at) else None

        # Determine current stage and status
        if review_approved:
            current_stage = "review-approval"
            current_status = "completed"
            halt_reason = None
        elif draft and eval_current:
            current_stage = "review-approval"
            current_status = "paused_at_approval_boundary"
            halt_reason = (
                f"Generated content (v{content_version}) evaluated (v{eval_version}). "
                "Awaiting explicit human review and approval."
            )
        elif draft:
            current_stage = "evaluate-improve"
            current_status = "in_progress"
            halt_reason = None
        elif strategy_approved:
            current_stage = "generate-content"
            current_status = "in_progress"
            halt_reason = None
        elif competitors_approved:
            current_stage = "promotion-strategy"
            current_status = "in_progress"
            halt_reason = None
        elif profile_approved:
            current_stage = "competitor-analysis"
            current_status = "in_progress"
            halt_reason = None
        elif profile:
            current_stage = "product-understanding"
            current_status = "halted"
            halt_reason = "Product profile awaiting human review and approval."
        else:
            current_stage = "source-grounding"
            current_status = "in_progress"
            halt_reason = None

        state: ProductWorkflowState = {
            "project_id": str(project.id),
            "product_id": str(product.id) if product else None,
            "user_id": self.user_id,
            "current_stage": current_stage,
            "status": current_status,
            "halt_reason": halt_reason,
            "errors": [],
            "stage_history": [current_stage],
            "execution_log": [{"stage": current_stage, "message": f"Snapshot status: {current_status}"}],
            "sources_grounded": bool(sources),
            "source_count": len(sources),
            "source_evidence": source_evidence,
            "product_profile": profile,
            "profile_version": profile_version,
            "profile_approved": profile_approved,
            "competitor_comparison": comp_comparison,
            "competitor_version": comp_version,
            "competitor_approved_version": comp_approved_version,
            "competitors_approved": competitors_approved,
            "competitor_limited_evidence": comp_limited,
            "promotion_strategy": strat_dict,
            "strategy_version": strat_version,
            "strategy_approved": strategy_approved,
            "content_pillars": pillars,
            "content_type": MVP_CONTENT_TYPE,
            "pillar_index": 0,
            "campaign_instructions": None,
            "generated_post": post_content,
            "content_version": content_version,
            "claims_traceability": claims_traceability,
            "generation_validation": draft.validation if draft else None,
            "evaluation": eval_dict,
            "evaluation_version": eval_version,
            "evaluation_current": eval_current,
            "review_approved": review_approved,
            "approved_version": approved_version,
            "approved_at": approved_at,
            "last_run": project.last_workflow_run,
        }
        return state

    @asynccontextmanager
    async def _exclusive(self, project_id: UUID):
        """One orchestration at a time per project. The lock lives on its own database connection, because the
        services commit (and so release) the session's own transaction several times during a run. A second request
        waits, then re-reads the saved state, so a double click can never create duplicate profiles, strategies or posts."""
        engine = getattr(self.db, "bind", None)
        if engine is None:
            yield
            return
        key = {"k": f"mcf-orchestrate:{project_id}"}
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), key)
            try:
                yield
            finally:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), key)

    @staticmethod
    def _step_log(state: ProductWorkflowState, stage: str, message: str) -> List[Dict[str, Any]]:
        return list(state.get("execution_log") or []) + [{"stage": stage, "message": message}]

    def _delegates(self, project: Project, stages: Dict[str, WorkflowStage], pillar_index: int,
                   campaign_instructions: Optional[str]) -> Dict[str, Any]:
        """The service-backed behaviour of each graph node. The master graph decides the ORDER and where to stop;
        these functions do the work (using the same domain services as the stage pages) and report what happened.
        The graph itself never approves anything: every human gate still halts it."""
        log = self._step_log

        async def grounding(state: ProductWorkflowState) -> Dict[str, Any]:
            sources = await get_project_source_texts(self.db, project)
            if not sources:
                return {
                    "status": "error", "sources_grounded": False, "source_count": 0,
                    "errors": ["No source material ingested. Ingest product sources first."],
                    "halt_reason": "Ingest product sources before running workflow orchestration.",
                    "execution_log": log(state, "source-grounding", "Failed: no source material."),
                }
            return {
                "status": "in_progress", "sources_grounded": True, "source_count": len(sources),
                "source_evidence": {f"S{i + 1}": name for i, (name, _) in enumerate(sources)},
                "execution_log": log(state, "source-grounding", f"{len(sources)} source(s) grounded."),
            }

        async def understanding(state: ProductWorkflowState) -> Dict[str, Any]:
            if not state.get("product_profile"):
                product = await self.products.run_understanding(project.id)
                return {
                    "product_id": str(product.id), "product_profile": product.profile, "profile_version": product.profile_version,
                    "profile_approved": False, "status": "halted",
                    "halt_reason": (f"Product profile (version {product.profile_version}) generated. "
                                    "Human review and approval is required before competitor analysis."),
                    "execution_log": log(state, "product-understanding", f"Generated profile v{product.profile_version}; awaiting approval."),
                }
            if not state.get("profile_approved"):
                return {
                    "status": "halted",
                    "halt_reason": f"Product profile (version {state.get('profile_version')}) requires human approval before proceeding.",
                    "execution_log": log(state, "product-understanding", "Halted: profile awaiting approval."),
                }
            return {"status": "in_progress",
                    "execution_log": log(state, "product-understanding", f"Profile v{state.get('profile_version')} is approved.")}

        async def competitors(state: ProductWorkflowState) -> Dict[str, Any]:
            if not state.get("competitors_approved"):
                return {
                    "status": "halted",
                    "halt_reason": "Competitor analysis requires human review and approval before promotion strategy.",
                    "execution_log": log(state, "competitor-analysis", "Halted: competitor analysis awaiting approval."),
                }
            return {"status": "in_progress", "execution_log": log(state, "competitor-analysis", "Competitor analysis is approved.")}

        async def strategy(state: ProductWorkflowState) -> Dict[str, Any]:
            if not state.get("promotion_strategy"):
                generated = await self.strategies.generate(UUID(state["product_id"]))
                pillars = (generated.strategy.get("content_pillars") if generated.strategy else None) or []
                return {
                    "promotion_strategy": generated.strategy, "strategy_version": generated.version, "strategy_approved": False,
                    "content_pillars": pillars, "status": "halted",
                    "halt_reason": (f"Promotion strategy (version {generated.version}) generated. "
                                    "Human review and approval is required before content generation."),
                    "execution_log": log(state, "promotion-strategy", f"Generated strategy v{generated.version}; awaiting approval."),
                }
            if not state.get("strategy_approved"):
                return {
                    "status": "halted",
                    "halt_reason": f"Promotion strategy (version {state.get('strategy_version')}) requires human approval before proceeding.",
                    "execution_log": log(state, "promotion-strategy", "Halted: strategy awaiting approval."),
                }
            return {"status": "in_progress",
                    "execution_log": log(state, "promotion-strategy", f"Strategy v{state.get('strategy_version')} is approved.")}

        async def generation(state: ProductWorkflowState) -> Dict[str, Any]:
            ready = await self.generation.readiness(project, stages)
            type_check = next((c for c in ready["checks"] if c["key"] == "content_type"), None)
            if type_check and not type_check["met"]:
                # Choosing the content type is the person's decision (and must be repeated when the strategy changes).
                return {
                    "status": "halted", "current_stage": "content-type",
                    "halt_reason": f"{type_check['detail']} Content generation needs an approved Content Type for the current strategy.",
                    "execution_log": log(state, "content-type", "Halted: Content Type needs your approval."),
                }

            draft = await self.generation.get_draft(project)
            stale = (self.generation.stale_reasons(draft, ready.get("product"), ready.get("strategy"), ready.get("approved_type"))
                     if draft else [])
            if draft and stale and draft.edited:
                # A person edited this post. Regenerating would silently overwrite their work, so stop and say so.
                return {
                    "status": "halted", "current_stage": "generate-content",
                    "generated_post": dict(draft.content or {}), "content_version": draft.version,
                    "halt_reason": (f"Your edited post (v{draft.version}) is out of date: {' '.join(stale)} "
                                    "It was NOT regenerated, so your edits are safe. Regenerate it yourself if you want a new version."),
                    "execution_log": log(state, "generate-content", "Halted: edited post is stale; not overwritten."),
                }
            if not draft or stale:
                draft = await self.generation.generate(project_id=project.id, pillar_index=pillar_index,
                                                       instructions=campaign_instructions)
                message = f"Generated post v{draft.version}."
            else:
                message = f"Using saved post v{draft.version}."
            post = dict(draft.content) if draft.content else None
            claims = [{"text": c.get("text", ""), "kind": c.get("kind", "product_fact"), "refs": c.get("refs", [])}
                      for c in ((post or {}).get("claims") or []) if isinstance(c, dict)]
            return {
                "status": "in_progress", "generated_post": post, "content_version": draft.version,
                "claims_traceability": claims, "generation_validation": draft.validation,
                "execution_log": log(state, "generate-content", message),
            }

        async def evaluation(state: ProductWorkflowState) -> Dict[str, Any]:
            draft = await self.generation.get_draft(project)
            existing = await latest_evaluation(self.db, draft) if draft else None
            if not existing or existing.content_version != draft.version:
                existing = await self.evaluation.evaluate(project.id, draft.version)
                message = f"Evaluated post v{draft.version}."
            else:
                message = f"Evaluation v{existing.content_version} is current."
            return {
                "status": "in_progress", "evaluation": existing.result, "evaluation_version": existing.content_version,
                "evaluation_current": existing.content_version == draft.version,
                "execution_log": log(state, "evaluate-improve", message),
            }

        return {
            "grounding_delegate": grounding, "understanding_delegate": understanding, "competitor_delegate": competitors,
            "strategy_delegate": strategy, "generation_delegate": generation, "evaluation_delegate": evaluation,
        }

    async def _record_run(self, project: Project, outcome: str, state: Optional[ProductWorkflowState], error: Optional[str] = None) -> None:
        """Keep a small trace of the latest run (what it visited, how it ended). Errors are redacted; no prompts or
        source text are stored."""
        project.last_workflow_run = {
            "at": datetime.now(timezone.utc).isoformat(),
            "outcome": outcome,
            "final_stage": (state or {}).get("current_stage"),
            "stages_visited": list((state or {}).get("stage_history") or []),
            "log": list((state or {}).get("execution_log") or [])[-20:],
            "error": redact(error) if error else None,
        }
        await self.db.commit()

    async def orchestrate(
        self,
        project_id: UUID,
        pillar_index: int = 0,
        campaign_instructions: Optional[str] = None,
    ) -> ProductWorkflowState:
        """Runs the master LangGraph up to the next required human checkpoint.

        The graph (app/ai/graphs/product_workflow_graph.py) decides the order and where to stop; this service supplies
        the work for each node. Guaranteed stops:
        1. Product profile awaiting approval -> halts at product-understanding.
        2. Competitor analysis awaiting approval -> halts at competitor-analysis.
        3. Promotion strategy awaiting approval -> halts at promotion-strategy.
        4. A stale post that a person edited -> halts at generate-content (never overwritten).
        5. Post generated and evaluated -> STRICTLY PAUSES at the human review boundary.
        Approved posts are never regenerated, and progress is derived from saved records, so a refresh, a restart or a
        second request resumes from the same place.
        """
        async with self._exclusive(project_id):
            project, stages = await self._get_project_and_stages(project_id)
            current = await self.get_state(project_id)

            # Already approved: return the saved state without touching the post or any progress.
            if current.get("review_approved") and current.get("status") == "completed":
                return current

            workflow_input: ProductWorkflowState = {
                **current,
                "status": "in_progress",
                "halt_reason": None,
                "errors": [],
                "stage_history": [],
                "execution_log": [],
                "campaign_instructions": campaign_instructions,
                "pillar_index": pillar_index,
                **self._delegates(project, stages, pillar_index, campaign_instructions),
            }
            try:
                result = await get_product_workflow_graph().ainvoke(workflow_input)
            except Exception as exc:  # noqa: BLE001 - recorded (redacted), then re-raised for the API layer
                await self.db.rollback()
                project = (await self._get_project_and_stages(project_id))[0]
                await self._record_run(project, "failed", None, error=f"{type(exc).__name__}: {getattr(exc, 'detail', exc)}")
                raise

            for key in ("grounding_delegate", "understanding_delegate", "competitor_delegate",
                        "strategy_delegate", "generation_delegate", "evaluation_delegate"):
                result.pop(key, None)
            return await self._finish_run(project_id, result)

    async def _finish_run(self, project_id: UUID, state: ProductWorkflowState) -> ProductWorkflowState:
        """Write stage statuses and the run trace so progress survives a refresh."""
        project, stages = await self._get_project_and_stages(project_id)
        status_now = state.get("status")

        def mark(key: str, done: bool) -> None:
            if key in stages and done and stages[key].status != "Completed":
                stages[key].status = "Completed"

        mark("source-grounding", bool(state.get("sources_grounded")))
        mark("product-understanding", bool(state.get("profile_approved")))
        mark("competitor-analysis", bool(state.get("competitors_approved")))
        mark("promotion-strategy", bool(state.get("strategy_approved")))
        mark("generate-content", bool(state.get("generated_post")) and status_now != "halted")
        mark("evaluate-improve", bool(state.get("evaluation_current")))
        if status_now == "paused_at_approval_boundary" and "review-approval" in stages                 and stages["review-approval"].status != "Completed":
            stages["review-approval"].status = "In Progress"
        if status_now in ("halted", "paused_at_approval_boundary", "completed") and state.get("current_stage"):
            project.current_stage = state["current_stage"]

        await self.db.commit()
        outcome = {"paused_at_approval_boundary": "paused_for_review", "halted": "halted_for_input",
                   "error": "error", "completed": "completed"}.get(status_now or "", "in_progress")
        await self._record_run(project, outcome, state, error=(state.get("halt_reason") if status_now == "error" else None))
        state["last_run"] = project.last_workflow_run  # the response shows the run that just finished, not the previous one
        return state

    async def approve_review(self, project_id: UUID, version: int) -> ProductWorkflowState:
        """A human explicitly reviews and approves the current saved post version.
        
        Strict safety:
        - Must be explicit human invocation.
        - Fails if version is stale.
        - Records approval decision only; never publishes or schedules.
        """
        project, stages = await self._get_project_and_stages(project_id)
        draft = await self.generation.approve(project_id, version)

        # Mark review-approval stage completed
        review_stage = stages.get(REVIEW_STAGE_KEY)
        if review_stage:
            review_stage.status = "Completed"
        project.status = "Completed"
        project.current_stage = "review-approval"
        await self.db.commit()

        # Update state snapshot
        state = await self.get_state(project_id)
        state["status"] = "completed"
        state["current_stage"] = "review-approval"
        state["review_approved"] = True
        state["approved_version"] = draft.approved_version
        state["halt_reason"] = None

        return state
