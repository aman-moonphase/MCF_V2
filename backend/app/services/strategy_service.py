"""Promotion Strategy: a product-level plan shared by all of the Product's campaigns.

Prerequisites: an approved, current Product Profile and an approved, current Competitor Analysis
(possibly explicitly approved with limited evidence). Edits bump the version and revoke approval.
A strategy generated from an older profile/competitor version is reported as stale and cannot be
approved until it is regenerated.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.competitor_schemas import FINDING_SECTIONS, SECTION_LABELS
from app.ai.config import normalize_provider_name
from app.ai.graphs.strategy_graph import run_promotion_strategy
from app.ai.platform_policy import MVP_CONTENT_TYPE, MVP_STRATEGY_NOTE, apply_mvp_content_type
from app.ai.strategy_schemas import EDITABLE_SECTIONS, PromotionStrategyOutput
from app.core.config import settings
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.project import Project
from app.models.promotion_strategy import PromotionStrategy
from app.models.workflow_stage import WorkflowStage
from app.ai.config import build_embedding_config
from app.services.product_service import ProductService
from app.services.retrieval_service import product_background

STAGE_KEY = "promotion-strategy"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StrategyService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.products = ProductService(db, user_id)

    # ─── Prerequisites ──────────────────────────────────────────────────────

    @staticmethod
    def prerequisite_problem(product: Product) -> Optional[str]:
        if not (product.understanding_status == "approved" and product.approved_version == product.profile_version):
            return "Approve the Product Profile first."
        if not (product.competitor_analysis_status == "approved"
                and product.competitor_approved_version == product.competitor_version):
            return "Approve the Competitor Analysis (or explicitly approve it with limited evidence) first."
        return None

    async def _ready_product(self, product_id: UUID) -> Product:
        product = await self.products.get_product(product_id)
        problem = self.prerequisite_problem(product)
        if problem:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problem)
        return product

    async def get_strategy(self, product: Product) -> Optional[PromotionStrategy]:
        result = await self.db.execute(select(PromotionStrategy).where(PromotionStrategy.product_id == product.id))
        return result.scalar_one_or_none()

    @staticmethod
    def is_stale(strategy: PromotionStrategy, product: Product) -> bool:
        basis = strategy.basis or {}
        return (basis.get("profile_version") != product.profile_version
                or basis.get("competitor_version") != product.competitor_version)

    # ─── Generate ───────────────────────────────────────────────────────────

    async def _context(self, product: Product) -> Dict[str, Any]:
        profile = {k: v for k, v in (product.profile or {}).items() if v and k not in ("source_references", "missing_fields", "confidence")}
        profile_text = json.dumps(profile, ensure_ascii=False, indent=1)
        limited = bool(product.competitor_limited_evidence)
        comparison = product.competitor_comparison if product.competitor_comparison_version == product.competitor_version else None

        competitors: List[Competitor] = list((await self.db.execute(
            select(Competitor).where(Competitor.product_id == product.id).order_by(Competitor.created_at.asc())
        )).scalars().all())
        analyzed = [c for c in competitors if c.analysis_status == "analyzed" and c.analysis]
        # Reuse the comparison's competitor labels so references line up with it.
        labels = {v["competitor_id"]: k for k, v in ((comparison or {}).get("competitors") or {}).items()}
        demo_competitors, sections, allowed, corpus = [], [], [], [profile_text]
        for index, c in enumerate(analyzed, start=1):
            label = labels.get(str(c.id), f"C{index}")
            lines = []
            for section in FINDING_SECTIONS:
                for f in c.analysis.get(section) or []:
                    refs = ", ".join(f"{label}:{r}" for r in f["refs"])
                    lines.append(f"[{SECTION_LABELS[section]}] ({f['status']}) {f['statement']}" + (f" [{refs}]" if refs else ""))
                    corpus.append(f["statement"])
            allowed += [f"{label}:{r}" for r in (c.analysis.get("references") or {})]
            sections.append((f"Competitor {label}: {c.name} — analysed findings", "\n".join(lines) or "(no findings)"))
            demo_competitors.append({"label": label, "name": c.name, "analysis": c.analysis})

        allowed += [f"profile:{k}" for k in profile]
        evidence_status = (
            "LIMITED — the user approved Competitor Analysis without full competitor evidence. Treat any competitor-based "
            "idea as a hypothesis." if limited else f"Approved, with {len(analyzed)} analysed competitor(s)."
        )
        context = [("Our approved Product Profile (cite as profile:<field>)", profile_text),
                   ("Competitor evidence status", evidence_status)]
        context += sections
        if comparison:
            context.append(("Approved comparison with our product (observations and suggestions)",
                            json.dumps({k: comparison.get(k) for k in ("similarities", "differences", "messaging_gaps",
                                                                         "positioning_opportunities", "promotion_patterns_to_investigate",
                                                                         "evidence_needed")}, ensure_ascii=False, indent=1)))
            corpus.append(json.dumps(comparison, ensure_ascii=False))
        background, background_refs = await product_background(self.db, product, self.user_id, profile, build_embedding_config())
        if background:
            context.append(background)
        context.append(("Output constraint", MVP_STRATEGY_NOTE))
        context.append(("Allowed references", ", ".join(allowed) or "(none)"))
        return {
            "prompt_context": context,
            "allowed_refs": allowed,
            "corpus": "\n".join(corpus),
            "meta": {"limited": limited},
            "demo_input": {"product": product.profile or {}, "comparison": comparison, "competitors": demo_competitors, "limited": limited,
                           "mvp_content_type": MVP_CONTENT_TYPE},
            "_competitor_names": [c.name for c in analyzed],
        }

    async def generate(self, product_id: UUID) -> PromotionStrategy:
        product = await self._ready_product(product_id)
        context = await self._context(product)
        names = context.pop("_competitor_names")
        try:
            output = apply_mvp_content_type(await run_promotion_strategy(context))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=f"Promotion Strategy failed: {e}")

        strategy = await self.get_strategy(product)
        basis = {
            "profile_version": product.profile_version,
            "competitor_version": product.competitor_version,
            "limited_evidence": bool(product.competitor_limited_evidence),
            "competitors": names,
        }
        if strategy is None:
            strategy = PromotionStrategy(product_id=product.id, strategy=output, version=1)
            self.db.add(strategy)
        else:
            strategy.strategy = output
            strategy.version = (strategy.version or 0) + 1
        strategy.status = "draft"
        strategy.edited_sections = []
        strategy.basis = basis
        strategy.provider = normalize_provider_name(settings.AI_PROVIDER)
        strategy.generated_at = _now()
        await self.db.commit()
        return strategy

    # ─── Edit / approve ─────────────────────────────────────────────────────

    async def _existing(self, product: Product) -> PromotionStrategy:
        strategy = await self.get_strategy(product)
        if not strategy:
            raise HTTPException(status_code=404, detail="No Promotion Strategy yet. Generate one first.")
        return strategy

    async def update(self, product_id: UUID, changes: Dict[str, Any]) -> PromotionStrategy:
        product = await self.products.get_product(product_id)
        strategy = await self._existing(product)
        unknown = set(changes) - set(EDITABLE_SECTIONS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown strategy section(s): {', '.join(sorted(unknown))}")
        merged = {**strategy.strategy, **changes}
        try:
            validated = PromotionStrategyOutput.model_validate(merged).model_dump()
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False))
        cd = validated["content_direction"]
        cd["alternatives"] = [a for a in dict.fromkeys(cd["alternatives"]) if a != cd["primary_content_type"]][:2]
        strategy.strategy = validated
        strategy.edited_sections = sorted(set(strategy.edited_sections or []) | set(changes))
        strategy.version = (strategy.version or 0) + 1
        strategy.status = "draft"  # edits revoke approval
        await self.db.commit()
        return strategy

    async def approve(self, product_id: UUID, project_id: UUID, version: int) -> PromotionStrategy:
        product = await self._ready_product(product_id)
        project = await self.products._linked_project(project_id, product)
        strategy = await self._existing(product)
        if version != strategy.version:
            raise HTTPException(status_code=409, detail="The strategy changed since you reviewed it. Review the latest version.")
        if self.is_stale(strategy, product):
            raise HTTPException(status_code=409, detail="The Product Profile or Competitor Analysis changed after this strategy was "
                                                        "generated. Regenerate it before approving.")
        strategy.status = "approved"
        strategy.approved_version = strategy.version
        strategy.approved_at = _now()
        await self.db.commit()
        stage = (await self.db.execute(
            select(WorkflowStage).where(WorkflowStage.project_id == project.id, WorkflowStage.stage_type == STAGE_KEY)
        )).scalar_one_or_none()
        if stage:
            stage.data = {"product_id": str(product.id), "approved_version": strategy.version}
            await self.db.commit()
        return strategy

    # ─── Downstream use ─────────────────────────────────────────────────────

    async def approved_strategy_for_project(self, project: Project) -> Optional[PromotionStrategy]:
        """The approved, current strategy for a project's product, or None."""
        if not project.product_id:
            return None
        product = await self.products.get_product(project.product_id)
        strategy = await self.get_strategy(product)
        if (strategy and strategy.status == "approved" and strategy.approved_version == strategy.version
                and not self.is_stale(strategy, product) and not self.prerequisite_problem(product)):
            return strategy
        return None


async def project_uses_strategy(db: AsyncSession, project: Project) -> bool:
    """New-flow projects (linked to a Product and with a Promotion Strategy stage) must follow the strategy."""
    if not project.product_id:
        return False
    stage = (await db.execute(
        select(WorkflowStage.id).where(WorkflowStage.project_id == project.id, WorkflowStage.stage_type == STAGE_KEY)
    )).scalar_one_or_none()
    return stage is not None
