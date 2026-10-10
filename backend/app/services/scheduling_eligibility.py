"""Calendar & content planning: may this saved post be planned on the calendar? (read-only)

The one authoritative answer for planning. It reuses the rules that already gate Review Approval instead of
restating them: owner-scoped loading, `GenerationService.readiness` (approved, current profile / competitors /
strategy / content type), `GenerationService.stale_reasons`, and Evaluate & Improve's `evaluation_problem`.

Planning is not publishing: an eligible post may be put on the calendar by a human; nothing is posted anywhere.
This module never writes — it does not create schedules, approve, evaluate or change any record.

Refusals are structured ({code, message}). A project that does not exist and a project owned by someone else get
the same `project_not_found` refusal, and nothing about another user's project or content is returned.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.platform_policy import GENERATION_SUPPORTED_TYPES, MVP_PLATFORM_KEY
from app.core.workflow import uses_product_workflow
from app.models.generated_content import GeneratedContent
from app.models.project import Project

# Evaluation outcomes that block planning: confirmed high-severity problems (see RuleBasedEvaluator).
BLOCKING_EVALUATION_LEVELS = frozenset({"not_ready"})
SUPPORTED_PLATFORMS = frozenset({MVP_PLATFORM_KEY})


def content_digest(content: Any) -> Optional[str]:
    """Stable fingerprint (sha256, 64 hex chars) of saved post content: identical content → identical digest,
    regardless of key order. None when there is no content to fingerprint."""
    if not content:
        return None
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Refusal:
    code: str
    message: str


@dataclass
class SchedulingEligibility:
    eligible: bool
    reasons: List[Refusal] = field(default_factory=list)
    # Only filled for the requesting user's own project (never for a refused ownership check).
    project_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    generated_content_id: Optional[UUID] = None
    content_type: Optional[str] = None
    platform: Optional[str] = None
    content_version: Optional[int] = None
    content_digest: Optional[str] = None
    evaluation_id: Optional[UUID] = None

    @property
    def codes(self) -> List[str]:
        return [r.code for r in self.reasons]

    def as_dict(self) -> Dict[str, Any]:
        """API-ready shape: {"eligible": bool, "reasons": [{code, message}], ...ids as strings}."""
        data = asdict(self)
        for key in ("project_id", "product_id", "generated_content_id", "evaluation_id"):
            data[key] = str(data[key]) if data[key] else None
        return data


def _time_problems(scheduled_at: Optional[datetime], now: datetime) -> List[Refusal]:
    if scheduled_at is None:
        return []
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        return [Refusal("timezone_required", "The planned time must include a time zone.")]
    if scheduled_at <= now:
        return [Refusal("time_in_past", "The planned time must be in the future.")]
    return []


async def check_scheduling_eligibility(
    db: AsyncSession, user_id: int, project_id: UUID, *, product_id: Optional[UUID] = None,
    scheduled_at: Optional[datetime] = None, now: Optional[datetime] = None,
) -> SchedulingEligibility:
    """Whether the project's saved post can be planned (optionally at `scheduled_at`, for `product_id`).

    All applicable refusals are reported together, except that nothing past an ownership or missing-content
    refusal is examined. Read-only."""
    from app.services.evaluation_service import evaluation_problem, latest_evaluation
    from app.services.generation_service import GenerationService

    now = now or datetime.now(timezone.utc)
    result = SchedulingEligibility(eligible=False)
    refuse = result.reasons.append

    project = (await db.execute(select(Project).where(Project.id == project_id, Project.user_id == user_id))
               ).scalar_one_or_none()
    if project is None:
        refuse(Refusal("project_not_found", "Project not found."))
        return result
    result.project_id, result.product_id = project.id, project.product_id

    if product_id is not None and project.product_id != product_id:
        refuse(Refusal("product_mismatch", "This project does not belong to the selected product."))
    generation = GenerationService(db, user_id)
    stages = await generation._stages(project)
    if not uses_product_workflow(stages):
        refuse(Refusal("legacy_workflow", "Only posts from the product workflow (generated, evaluated and approved) can be planned."))
        return result

    draft = await generation.get_draft(project)
    if draft is None:
        others = (await db.execute(select(GeneratedContent).where(GeneratedContent.project_id == project.id))).scalars().all()
        if others:
            refuse(Refusal("unsupported_content", "Only a LinkedIn Social Post can be planned in this version."))
        else:
            refuse(Refusal("no_content", "There is no saved post to plan. Generate, evaluate and approve one first."))
        result.reasons.extend(_time_problems(scheduled_at, now))
        return result
    if draft.content_type not in GENERATION_SUPPORTED_TYPES or draft.platform not in SUPPORTED_PLATFORMS:
        refuse(Refusal("unsupported_content", "Only a LinkedIn Social Post can be planned in this version."))
    result.generated_content_id, result.content_type, result.platform = draft.id, draft.content_type, draft.platform
    result.content_version = draft.version

    # Human approval of exactly the saved version.
    if draft.status != "approved":
        refuse(Refusal("not_approved", f"Version {draft.version} of the post has not been approved in Review Approval."))
    elif draft.approved_version != draft.version:
        refuse(Refusal("approval_outdated", f"Version {draft.approved_version} was approved, but the saved post is now "
                                            f"version {draft.version}. Approve the current version first."))

    # The approved context the post was generated from must still be current (same rules as approval).
    try:
        ready = await generation.readiness(project, stages)
    except HTTPException:  # e.g. the linked product is not the user's own: say nothing about it
        ready = {"problem": "The product linked to this project is not available.", "product": None,
                 "strategy": None, "approved_type": None}
    if ready["problem"]:
        refuse(Refusal("context_not_current", ready["problem"]))
    stale = generation.stale_reasons(draft, ready["product"], ready["strategy"], ready["approved_type"])
    if stale:
        refuse(Refusal("stale_content", "The post is out of date: " + " ".join(stale)))
    if not (draft.validation or {}).get("within_limit", True):
        refuse(Refusal("over_limit", "The saved post is over the platform's character limit."))

    # A current evaluation of exactly this version, without blocking problems. Required for every product-workflow
    # post (unlike stage transitions, which only gate projects that have the Evaluate & Improve stage).
    latest = await latest_evaluation(db, draft)
    if latest is None:
        refuse(Refusal("evaluation_missing", f"Evaluate the saved post (version {draft.version}) in Evaluate & Improve first."))
    elif latest.content_version != draft.version:
        refuse(Refusal("evaluation_outdated", await evaluation_problem(db, project, stages, draft)
                       or f"The latest evaluation is for version {latest.content_version}, not version {draft.version}."))
    elif latest.overall in BLOCKING_EVALUATION_LEVELS:
        refuse(Refusal("evaluation_blocking", "The evaluation of this version found high-severity problems. Fix them "
                                              "and re-evaluate before planning."))
    else:
        result.evaluation_id = latest.id

    result.content_digest = content_digest(draft.content)
    if result.content_digest is None:
        refuse(Refusal("content_unavailable", "The saved post has no content to plan."))

    result.reasons.extend(_time_problems(scheduled_at, now))
    result.eligible = not result.reasons
    return result
