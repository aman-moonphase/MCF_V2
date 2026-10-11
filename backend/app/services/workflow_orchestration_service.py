"""Workflow Orchestration Service: Connects existing domain services into the stateful LangGraph pipeline.

Preserves all safety rules:
- No automatic human approval or social posting (execution pauses at the review boundary).
- Exact version matching for evaluation.
- Full claim and citation traceability (P:*, S*).
- Safe prerequisite gating.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graphs.product_workflow_graph import ProductWorkflowState, get_product_workflow_graph
from app.ai.platform_policy import MVP_CONTENT_TYPE
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
        strategy = await self.strategies.approved_strategy_for_project(project) if product else None
        strat_dict = strategy.strategy if strategy else None
        strat_version = strategy.version if strategy else None
        strategy_approved = bool(strategy and strategy.status == "approved")
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
        }
        return state

    async def orchestrate(
        self,
        project_id: UUID,
        pillar_index: int = 0,
        campaign_instructions: Optional[str] = None,
    ) -> ProductWorkflowState:
        """Executes the stateful LangGraph pipeline up to the next required human checkpoint.
        
        Guaranteed stops:
        1. If product profile requires approval -> halts at product-understanding.
        2. If competitor analysis requires approval -> halts at competitor-analysis.
        3. If promotion strategy requires approval -> halts at promotion-strategy.
        4. If post is generated and evaluated -> STRICTLY PAUSES at human_review_boundary.
        """
        project, stages = await self._get_project_and_stages(project_id)
        current = await self.get_state(project_id)

        # If already approved and completed, safely return the completed state
        # without regenerating, altering content, or resetting progress.
        if current.get("review_approved") and current.get("status") == "completed":
            return current

        # ── Step 1: Ground Sources ──
        sources = await get_project_source_texts(self.db, project)
        if not sources:
            current["status"] = "error"
            current["errors"] = ["No source material ingested. Ingest product sources first."]
            current["halt_reason"] = "Ingest product sources before running workflow orchestration."
            return current

        # ── Step 2: Product Understanding ──
        if not current.get("product_profile"):
            product = await self.products.run_understanding(project_id)
            current["product_id"] = str(product.id)
            current["product_profile"] = product.profile
            current["profile_version"] = product.profile_version
            current["profile_approved"] = False
            current["status"] = "halted"
            current["current_stage"] = "product-understanding"
            current["halt_reason"] = (
                f"Product profile (version {product.profile_version}) generated. "
                "Human review and approval is required before competitor analysis."
            )
            project.current_stage = "product-understanding"
            await self.db.commit()
            return current

        if not current.get("profile_approved"):
            current["status"] = "halted"
            current["current_stage"] = "product-understanding"
            current["halt_reason"] = (
                f"Product profile (version {current.get('profile_version')}) requires human approval before proceeding."
            )
            project.current_stage = "product-understanding"
            await self.db.commit()
            return current

        # ── Step 3: Competitor Analysis ──
        if not current.get("competitors_approved"):
            current["status"] = "halted"
            current["current_stage"] = "competitor-analysis"
            current["halt_reason"] = "Competitor analysis requires human review and approval before promotion strategy."
            project.current_stage = "competitor-analysis"
            await self.db.commit()
            return current

        # ── Step 4: Promotion Strategy ──
        product = await self.products.get_product(UUID(current["product_id"]))
        if not current.get("promotion_strategy"):
            strategy = await self.strategies.generate(product.id)
            current["promotion_strategy"] = strategy.strategy
            current["strategy_version"] = strategy.version
            current["strategy_approved"] = False
            current["status"] = "halted"
            current["current_stage"] = "promotion-strategy"
            current["halt_reason"] = (
                f"Promotion strategy (version {strategy.version}) generated. "
                "Human review and approval is required before content generation."
            )
            project.current_stage = "promotion-strategy"
            await self.db.commit()
            return current

        if not current.get("strategy_approved"):
            current["status"] = "halted"
            current["current_stage"] = "promotion-strategy"
            current["halt_reason"] = (
                f"Promotion strategy (version {current.get('strategy_version')}) requires human approval before proceeding."
            )
            project.current_stage = "promotion-strategy"
            await self.db.commit()
            return current

        # ── Step 5: Content Type Check ──
        ct_stage = stages.get("content-type")
        if ct_stage and ct_stage.status != "Completed":
            ct_stage.status = "Completed"
            ct_stage.data = {**(ct_stage.data or {}), "approved_type": MVP_CONTENT_TYPE}
            await self.db.commit()

        # ── Step 6: Generate Content Draft ──
        draft = await self.generation.get_draft(project)
        ready = await self.generation.readiness(project, stages)
        needs_generation = False
        if not draft:
            needs_generation = True
        else:
            stale = self.generation.stale_reasons(
                draft, ready.get("product"), ready.get("strategy"), ready.get("approved_type")
            )
            if stale:
                needs_generation = True

        if needs_generation:
            draft = await self.generation.generate(
                project_id=project.id,
                pillar_index=pillar_index,
                instructions=campaign_instructions,
            )

        post_content = dict(draft.content) if draft and draft.content else None
        claims_traceability: List[Dict[str, Any]] = []
        if post_content and "claims" in post_content:
            for c in post_content.get("claims") or []:
                if isinstance(c, dict):
                    claims_traceability.append({
                        "text": c.get("text", ""),
                        "kind": c.get("kind", "product_fact"),
                        "refs": c.get("refs", []),
                    })

        current["generated_post"] = post_content
        current["content_version"] = draft.version
        current["claims_traceability"] = claims_traceability
        current["generation_validation"] = draft.validation

        # ── Step 7: Evaluate & Improve ──
        latest_eval = await latest_evaluation(self.db, draft)
        if not latest_eval or latest_eval.content_version != draft.version:
            evaluation = await self.evaluation.evaluate(project.id, draft.version)
            current["evaluation"] = evaluation.result
            current["evaluation_version"] = evaluation.content_version
            current["evaluation_current"] = True
        else:
            current["evaluation"] = latest_eval.result
            current["evaluation_version"] = latest_eval.content_version
            current["evaluation_current"] = True

        # ── Step 8: Human Review & Approval Boundary ──
        # Update stage statuses and project current stage in DB so progress survives refresh
        if "source-grounding" in stages and stages["source-grounding"].status != "Completed":
            stages["source-grounding"].status = "Completed"
        if "product-understanding" in stages and current.get("profile_approved"):
            stages["product-understanding"].status = "Completed"
        if "competitor-analysis" in stages and current.get("competitors_approved"):
            stages["competitor-analysis"].status = "Completed"
        if "promotion-strategy" in stages and current.get("strategy_approved"):
            stages["promotion-strategy"].status = "Completed"
        if "generate-content" in stages and draft:
            stages["generate-content"].status = "Completed"
        if "evaluate-improve" in stages and current.get("evaluation_current"):
            stages["evaluate-improve"].status = "Completed"
        if "review-approval" in stages and stages["review-approval"].status != "Completed":
            stages["review-approval"].status = "In Progress"

        project.current_stage = "review-approval"
        await self.db.commit()

        # Run graph validation through compiled LangGraph to ensure all edge invariants hold
        graph = get_product_workflow_graph()
        workflow_input: ProductWorkflowState = {
            **current,
            "current_stage": "generate-content",
            "campaign_instructions": campaign_instructions,
            "pillar_index": pillar_index,
        }
        graph_output = await graph.ainvoke(workflow_input)

        # Merge graph output
        for k, v in graph_output.items():
            if v is not None:
                current[k] = v

        return current

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
