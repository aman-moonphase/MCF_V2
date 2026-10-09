"""Product Understanding: one reusable Product Profile per Product, shared by its projects.

Ownership rules enforced here:
- a product is only visible to its owner (products.user_id);
- a project is only visible to its owner (ProjectService);
- understanding, answers and approval for a product happen through a project that is linked to it,
  and that project's sources are the only sources used.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import build_embedding_config
from app.ai.graphs.product_understanding_graph import run_product_understanding
from app.ai.nodes.product_understanding_nodes import clean_profile, is_empty
from app.ai.product_schemas import CRITICAL_FIELDS, PROFILE_FIELDS, ProductProfileDraft
from app.models.product import Product
from app.models.project import Project
from app.models.source import SourceDocument
from app.models.workflow_stage import WorkflowStage
from app.services.project_service import ProjectService
from app.services.retrieval_service import RetrievalService
from app.services.source_text_service import get_project_source_text

STAGE_KEY = "product-understanding"
_GROUNDING_QUERY = (
    "What is the product, who is it for, what problem does it solve, its features, benefits, "
    "differentiators, pricing, market, and any named competitors or alternatives?"
)


def compute_confidence(profile: Dict[str, Any]) -> str:
    filled = sum(1 for f in CRITICAL_FIELDS if not is_empty(profile.get(f)))
    ratio = filled / len(CRITICAL_FIELDS)
    return "high" if ratio >= 0.85 else "medium" if ratio >= 0.5 else "low"


def _missing(profile: Dict[str, Any]) -> List[str]:
    return [f for f in PROFILE_FIELDS if is_empty(profile.get(f))]


class ProductService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.projects = ProjectService(db, user_id)

    # ─── Lookup / ownership ──────────────────────────────────────────────────

    async def get_product(self, product_id: UUID) -> Product:
        result = await self.db.execute(
            select(Product).where(Product.id == product_id, Product.user_id == self.user_id)
            .execution_options(populate_existing=True)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return product

    async def list_products(self) -> List[Product]:
        result = await self.db.execute(
            select(Product).where(Product.user_id == self.user_id).order_by(Product.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_project_product(self, project_id: UUID) -> Optional[Product]:
        project = await self.projects.get_project(project_id)
        return await self.get_product(project.product_id) if project.product_id else None

    async def _linked_project(self, project_id: UUID, product: Product) -> Project:
        project = await self.projects.get_project(project_id)
        if project.product_id != product.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This project is not linked to this product")
        return project

    async def link_project(self, project_id: UUID, product_id: UUID) -> Product:
        """Reuse an existing product (and its profile) for another project."""
        project = await self.projects.get_project(project_id)
        product = await self.get_product(product_id)
        project.product_id = product.id
        await self.db.commit()
        await self._set_stage_data(project.id, product)
        return product

    async def project_ids(self, product: Product) -> List[UUID]:
        result = await self.db.execute(
            select(Project.id).where(Project.product_id == product.id, Project.user_id == self.user_id)
        )
        return list(result.scalars().all())

    # ─── Understanding ──────────────────────────────────────────────────────

    async def run_understanding(self, project_id: UUID) -> Product:
        """Start (or refresh) Product Understanding from the project's own sources."""
        project = await self.projects.get_project(project_id)
        if project.product_id:
            product = await self.get_product(project.product_id)
        else:
            product = Product(user_id=self.user_id, name=(project.title or "Untitled product")[:255])
            self.db.add(product)
            await self.db.flush()
            project.product_id = product.id
            await self.db.commit()
        await self._refresh(product, project)
        return product

    async def _refresh(self, product: Product, project: Project) -> None:
        source_text = await get_project_source_text(self.db, project)
        if not source_text.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add a product source before running Product Understanding.")

        questions = list(product.clarification_questions or [])
        clarifications = [
            {"question": q["question"], "fields": q["fields"], "answer": q["answer"]}
            for q in questions if q.get("status") == "answered"
        ]
        asked_fields = sorted({f for q in questions if q.get("status") in ("open", "answered") for f in q["fields"]})

        try:
            result = await run_product_understanding(
                input_text=source_text,
                grounding_context=await self._grounding(project.id),
                current_profile=product.profile,
                clarifications=clarifications,
                asked_fields=asked_fields,
                edited_fields=list(product.edited_fields or []),
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=f"Product Understanding failed: {e}")

        profile = {f: result["profile"].get(f) for f in PROFILE_FIELDS}
        profile["source_references"] = await self._source_references(project.id)
        now = datetime.now(timezone.utc).isoformat()
        new_questions = [
            {"id": uuid.uuid4().hex[:12], **q, "status": "open", "answer": None, "answered_at": None, "asked_at": now}
            for q in result["questions"]
        ]
        self._store(product, profile, questions + new_questions)
        await self.db.commit()
        await self._set_stage_data(project.id, product)

    def _store(self, product: Product, profile: Dict[str, Any], questions: List[dict]) -> None:
        """Persist a new profile version; questions whose fields are now known are resolved."""
        profile["missing_fields"] = _missing(profile)
        profile["confidence"] = compute_confidence(profile)
        updated_questions = []
        for q in questions:
            q = dict(q)
            if q.get("status") == "open" and all(not is_empty(profile.get(f)) for f in q["fields"]):
                q["status"] = "resolved"
            updated_questions.append(q)

        product.profile = profile
        product.clarification_questions = updated_questions
        product.profile_version = (product.profile_version or 0) + 1
        product.understanding_status = (
            "needs_clarification" if any(q["status"] == "open" for q in updated_questions) else "ready_for_review"
        )
        if profile.get("name"):
            product.name = profile["name"][:255]
        if profile.get("description"):
            product.description = profile["description"]

    async def _grounding(self, project_id: UUID) -> dict:
        # A savepoint keeps a retrieval failure from aborting the outer transaction (and pending answers).
        try:
            async with self.db.begin_nested():
                chunks = await RetrievalService.retrieve(self.db, project_id, _GROUNDING_QUERY, build_embedding_config(), top_k=5)
        except Exception:
            return {}
        return {"text": "\n\n---\n\n".join(c.content for c in chunks)} if chunks else {}

    async def _source_references(self, project_id: UUID) -> List[dict]:
        result = await self.db.execute(
            select(SourceDocument)
            .where(SourceDocument.project_id == project_id, SourceDocument.status == "completed")
            .order_by(SourceDocument.created_at.asc())
        )
        return [
            {"source_id": str(d.id), "name": d.name, "source_type": d.source_type}
            for d in result.scalars().all()
        ]

    async def _set_stage_data(self, project_id: UUID, product: Product) -> None:
        """The project's stage stores only a reference to the product, never a copy of the profile."""
        result = await self.db.execute(
            select(WorkflowStage).where(WorkflowStage.project_id == project_id, WorkflowStage.stage_type == STAGE_KEY)
        )
        stage = result.scalar_one_or_none()
        if stage:
            data = {"product_id": str(product.id)}
            if product.understanding_status == "approved":
                data["approved_version"] = product.approved_version
            stage.data = data
            await self.db.commit()

    # ─── Human in the loop ──────────────────────────────────────────────────

    async def submit_answers(self, product_id: UUID, project_id: UUID, answers: List[dict]) -> Product:
        product = await self.get_product(product_id)
        project = await self._linked_project(project_id, product)
        questions = [dict(q) for q in (product.clarification_questions or [])]
        by_id = {q["id"]: q for q in questions}
        if not answers:
            raise HTTPException(status_code=422, detail="Provide at least one answer.")
        now = datetime.now(timezone.utc).isoformat()
        for item in answers:
            question = by_id.get(item["question_id"])
            if question is None:
                raise HTTPException(status_code=422, detail=f"Question '{item['question_id']}' does not belong to this product.")
            if question["status"] != "open":
                raise HTTPException(status_code=422, detail=f"Question '{item['question_id']}' has already been {question['status']}.")
            answer = (item.get("answer") or "").strip()
            if not answer:
                raise HTTPException(status_code=422, detail="Answers cannot be empty.")
            question.update(status="answered", answer=answer, answered_at=now)
        product.clarification_questions = questions
        await self._refresh(product, project)
        return product

    async def update_profile(self, product_id: UUID, changes: Dict[str, Any]) -> Product:
        product = await self.get_product(product_id)
        if not product.profile:
            raise HTTPException(status_code=400, detail="Run Product Understanding before editing the profile.")
        unknown = set(changes) - set(PROFILE_FIELDS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown profile field(s): {', '.join(sorted(unknown))}")
        merged = {f: product.profile.get(f) for f in PROFILE_FIELDS}
        merged.update(changes)
        try:
            validated = clean_profile(ProductProfileDraft.model_validate(merged).model_dump())
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False))
        validated["source_references"] = product.profile.get("source_references", [])
        product.edited_fields = sorted(set(product.edited_fields or []) | set(changes))
        self._store(product, validated, list(product.clarification_questions or []))
        await self.db.commit()
        return product

    async def approve(self, product_id: UUID, project_id: UUID, profile_version: int) -> Product:
        product = await self.get_product(product_id)
        project = await self._linked_project(project_id, product)
        if not product.profile:
            raise HTTPException(status_code=400, detail="There is no Product Profile to approve yet.")
        if profile_version != product.profile_version:
            raise HTTPException(
                status_code=409,
                detail="The Product Profile changed since you reviewed it. Review the latest version before approving.",
            )
        product.understanding_status = "approved"
        product.approved_version = product.profile_version
        product.approved_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self._set_stage_data(project.id, product)
        return product

    async def get_approved_profile(self, project_id: UUID) -> Dict[str, Any]:
        """The approved Product Profile used as context by later stages (competitor analysis, strategy)."""
        project = await self.projects.get_project(project_id)
        if not project.product_id:
            raise HTTPException(status_code=409, detail="This project has no product yet.")
        product = await self.get_product(project.product_id)
        if product.understanding_status != "approved" or product.approved_version != product.profile_version:
            raise HTTPException(status_code=409, detail="The Product Profile has not been approved.")
        return {"product_id": str(product.id), "profile_version": product.approved_version, "profile": product.profile}
