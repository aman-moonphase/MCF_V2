"""Generate Content: a grounded LinkedIn Social Post for a product-workflow project.

Everything the generator sees is loaded here, server-side, from PostgreSQL — never from the client:
the owned project and its product, the approved and current Product Profile, the approved Competitor
Analysis and comparison (or its explicit limited-evidence approval), the approved and current
Promotion Strategy, the project's approved Content Type, the project's own sources (+ retrieved
excerpts), and the campaign instructions the user typed for this generation.

Generation is refused when any of that is missing, unapproved or stale, and when the approved content
type is not one this version can generate. Drafts are stored in `generated_contents`; regenerating or
editing bumps the version and never overwrites an approved asset.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import build_embedding_config, normalize_provider_name
from app.ai.generation_validation import EDIT_BLOCKING, validate_post
from app.ai.graphs.generation_graph import run_linkedin_generation
from app.ai.platform_policy import MVP_CONTENT_TYPE, generation_support, platform_policy
from app.ai.pillar_alignment import pillar_context
from app.ai.usage import collect_usage, summarize_usage
from app.core.config import settings
from app.core.text_encoding import repair_mojibake
from app.core.workflow import uses_product_workflow
from app.models.competitor import Competitor, CompetitorEvidence
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.promotion_strategy import PromotionStrategy
from app.models.workflow_stage import WorkflowStage
from app.services.retrieval_service import RetrievalService
from app.services.source_text_service import cap_for_prompt, get_project_source_texts
from app.services.strategy_service import StrategyService

STAGE_KEY = "generate-content"
REVIEW_STAGE_KEY = "review-approval"
CONTENT_TYPE_STAGE = "content-type"
EDITABLE_FIELDS = ("hook", "alternative_hooks", "body", "cta", "hashtags")
_PROFILE_SKIP = ("source_references", "missing_fields", "confidence")
MAX_INSTRUCTIONS_CHARS = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _statement(item: dict) -> str:
    return item.get("statement") or item.get("suggestion") or ""


# "Momoyoga: the supplied evidence does not establish whether Momoyoga offers something like our "X". …"
_UNRESOLVED = re.compile(r'^(?P<competitor>.+?): the supplied evidence does not establish whether .+? offers something like our "(?P<feature>[^"]+)"')


def competitor_findings(comparison: Optional[dict]) -> Dict[str, list]:
    """The approved comparison, kept in four groups with their uncertainty and citations:
    - differences: evidence-based differences and messaging gaps (each observed or inferred);
    - similarities: possible overlaps with our features — NOT unique advantages;
    - suggestions: angles to evaluate — not facts, not proven opportunities;
    - unresolved: features the evidence does not settle — unknown, never "the competitor lacks it".
    Nothing is added or reclassified here."""
    c = comparison or {}

    def findings(*sections: str) -> List[dict]:
        return [{"statement": _statement(f), "status": f.get("status") or "inferred", "refs": f.get("refs") or [],
                 "section": section} for section in sections for f in c.get(section) or [] if _statement(f)]

    unresolved = []
    for line in c.get("evidence_needed") or []:
        m = _UNRESOLVED.match(line or "")
        if m:
            unresolved.append({"competitor": m.group("competitor"), "feature": m.group("feature")})
    return {
        "differences": findings("differences", "messaging_gaps"),
        "similarities": findings("similarities"),
        "suggestions": [{"suggestion": s.get("suggestion") or "", "rationale": s.get("rationale") or "",
                         "refs": s.get("refs") or [], "section": section}
                        for section in ("positioning_opportunities", "promotion_patterns_to_investigate")
                        for s in c.get(section) or [] if s.get("suggestion")],
        "unresolved": unresolved,
    }


def _competitor_prompt_sections(groups: Dict[str, list]) -> List[Tuple[str, str]]:
    def lines(items, render):
        return "\n".join(render(i) for i in items)

    cite = lambda refs: f" [{', '.join(refs)}]" if refs else ""  # noqa: E731
    sections = [(
        "Competitor insights 1/4 — evidence-based differences and messaging gaps (status shown; use ONLY to choose "
        "emphasis; never name or quote competitors)",
        lines(groups["differences"], lambda f: f"- ({f['status']}) {f['statement']}{cite(f['refs'])}")
        or "None: the evidence establishes no differences or messaging gaps. Do not claim any.",
    )]
    if groups["similarities"]:
        sections.append((
            "Competitor insights 2/4 — POSSIBLE OVERLAPS (inferred, not confirmed). The related features of ours are NOT "
            "unique advantages: do not present them as something only we offer",
            lines(groups["similarities"], lambda f: f"- ({f['status']}, unconfirmed) {f['statement']}{cite(f['refs'])}")))
    if groups["suggestions"]:
        sections.append((
            "Competitor insights 3/4 — SUGGESTIONS to evaluate (not facts, not proven opportunities; optional)",
            lines(groups["suggestions"], lambda s: f"- {s['suggestion']}{cite(s['refs'])}")))
    if groups["unresolved"]:
        sections.append((
            "Competitor insights 4/4 — UNRESOLVED comparisons (unknown). The evidence does not establish whether the "
            "competitor offers these. Never say or imply that it lacks them",
            lines(groups["unresolved"], lambda u: f"- {u['feature']}")))
    return sections


class GenerationService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.strategies = StrategyService(db, user_id)
        self.products = self.strategies.products

    # ─── Loading (owner-scoped) ─────────────────────────────────────────────

    async def _stages(self, project: Project) -> Dict[str, WorkflowStage]:
        rows = (await self.db.execute(select(WorkflowStage).where(WorkflowStage.project_id == project.id))).scalars().all()
        return {row.stage_type: row for row in rows}

    async def get_project(self, project_id: UUID) -> Tuple[Project, Dict[str, WorkflowStage]]:
        project = await self.products.projects.get_project(project_id)  # 404 unless owned
        return project, await self._stages(project)

    async def get_draft(self, project: Project) -> Optional[GeneratedContent]:
        return (await self.db.execute(select(GeneratedContent).where(
            GeneratedContent.project_id == project.id, GeneratedContent.content_type == MVP_CONTENT_TYPE,
            GeneratedContent.platform == platform_policy().key,
        ))).scalar_one_or_none()

    async def readiness(self, project: Project, stages: Dict[str, WorkflowStage]) -> Dict[str, Any]:
        """Prerequisite checks plus the loaded approved context. Never raises for an unmet prerequisite."""
        checks: List[Dict[str, Any]] = []
        out: Dict[str, Any] = {"checks": checks, "product": None, "strategy": None, "approved_type": None,
                               "problem": None, "problem_status": None}

        def check(key: str, label: str, problem: Optional[str], code: int = status.HTTP_409_CONFLICT) -> bool:
            checks.append({"key": key, "label": label, "met": problem is None, "detail": problem})
            if problem and not out["problem"]:
                out["problem"], out["problem_status"] = problem, code
            return problem is None

        product = await self.products.get_product(project.product_id) if project.product_id else None
        out["product"] = product
        if not check("product", "Product linked to this project",
                     None if product else "Link a product in the Product Understanding stage first."):
            return out
        profile_ok = product.understanding_status == "approved" and product.approved_version == product.profile_version
        check("profile", "Product Profile approved and current",
              None if profile_ok else "Approve the current Product Profile first.")
        competitor_ok = (product.competitor_analysis_status == "approved"
                         and product.competitor_approved_version == product.competitor_version)
        check("competitors", "Competitor Analysis approved and current",
              None if competitor_ok else "Approve the current Competitor Analysis (or approve it with limited evidence) first.")

        strategy = await self.strategies.get_strategy(product)
        approved_strategy = await self.strategies.approved_strategy_for_project(project)
        out["strategy"] = approved_strategy
        if approved_strategy:
            strategy_problem = None
        elif strategy and strategy.status == "approved" and strategy.approved_version == strategy.version:
            strategy_problem = "The Promotion Strategy is out of date with the profile or competitors. Regenerate and approve it."
        else:
            strategy_problem = "Approve the Promotion Strategy first."
        check("strategy", "Promotion Strategy approved and current", strategy_problem)

        type_stage = stages.get(CONTENT_TYPE_STAGE)
        data = (type_stage.data or {}) if type_stage else {}
        approved_type = data.get("approved_type") or data.get("approvedType")
        out["approved_type"] = approved_type
        if not approved_type:
            type_problem = "Approve a Content Type first."
        elif approved_strategy and data.get("strategy_version") != approved_strategy.version:
            type_problem = "The Promotion Strategy changed after the Content Type was approved. Approve the Content Type again."
        else:
            type_problem = None
        if check("content_type", "Content Type approved for the current strategy", type_problem) and approved_type:
            check("supported", f"Content type can be generated (this version: LinkedIn {MVP_CONTENT_TYPE})",
                  generation_support(approved_type), status.HTTP_422_UNPROCESSABLE_ENTITY)
        return out

    # ─── Context for the generator ──────────────────────────────────────────

    async def _sources(self, project: Project, query: str):
        """([(label, title, text)], full_text, excerpt_meta, retrieval) — "S1" = the project's own sources (full),
        "S:<source>#<chunk>" = relevant retrieved excerpts with stable references (owner-scoped; unverified text)."""
        texts = await get_project_source_texts(self.db, project)
        full = "\n\n".join(f"--- {name} ---\n{body}" for name, body in texts)
        items: List[Tuple[str, str, str]] = []
        excerpt_meta: Dict[str, Dict[str, Any]] = {}
        retrieval: Dict[str, Any] = {"status": "no_sources", "note": "The project has no ingested sources.", "refs": []}
        if full:
            items.append(("S1", "Project sources: " + ", ".join(name for name, _ in texts), cap_for_prompt(full)))
            try:
                async with self.db.begin_nested():
                    found = await RetrievalService.retrieve_evidence(self.db, query, build_embedding_config(), user_id=self.user_id,
                                                                     project_ids=[project.id], top_k=4)
            except Exception:
                found = None
            if found is None:
                retrieval = {"status": "error", "note": "Retrieval failed; only the full project source was used.", "refs": []}
            else:
                for chunk in found.chunks:
                    items.append((chunk.ref, chunk.describe(), chunk.content))
                    # Identity = source + chunk index + content hash. The chunk row id is deliberately not stored:
                    # re-indexing replaces every row, so it would make unchanged evidence look different.
                    excerpt_meta[chunk.ref] = {"source_document_id": chunk.source_document_id, "chunk_index": chunk.chunk_index,
                                               "content_hash": (chunk.metadata or {}).get("content_hash"), "page": chunk.page,
                                               "source_name": chunk.source_name, "score": chunk.score}
                retrieval = {"status": found.status, "note": found.note(), "refs": [c.ref for c in found.chunks],
                             "mode": found.mode, "skipped_stale": found.skipped_stale}
        return items, full, excerpt_meta, retrieval

    async def _competitor_material(self, product: Product) -> Tuple[List[str], List[str]]:
        """Competitor names and raw evidence text — used only to stop the post naming or copying them.

        A name the approved profile itself uses (e.g. an integration) is a product fact, not leakage;
        `known_competitors` merely lists them, so it does not count."""
        profile = {k: v for k, v in (product.profile or {}).items() if k != "known_competitors"}
        profile_text = json.dumps(profile, ensure_ascii=False).lower()
        competitors = (await self.db.execute(select(Competitor).where(Competitor.product_id == product.id))).scalars().all()
        evidence = (await self.db.execute(select(CompetitorEvidence.content).where(
            CompetitorEvidence.product_id == product.id, CompetitorEvidence.status == "completed"))).scalars().all()
        texts = [repair_mojibake(e) for e in evidence if e]
        for c in competitors:
            for example in (c.analysis or {}).get("content_examples") or []:
                texts.append(example.get("excerpt") or "")
        return [c.name for c in competitors if c.name.lower() not in profile_text], texts

    async def _forbidden_names(self, product: Product, own_name: str) -> List[str]:
        own = {own_name.lower(), (product.name or "").lower()}
        profile_text = json.dumps(product.profile or {}, ensure_ascii=False).lower()
        names = []
        for other in await self.products.list_products():
            name = (other.name or "").strip()
            if other.id != product.id and len(name) >= 3 and name.lower() not in own and name.lower() not in profile_text:
                names.append(name)
        return names

    @staticmethod
    def _emphasis(profile: dict, pillar: dict, comparison: Optional[dict], limited: bool) -> Dict[str, Any]:
        """Which differentiator the post leads with. Competitor evidence only informs the choice."""
        diffs: List[str] = profile.get("differentiators") or []
        differences = [] if limited or not comparison else (comparison.get("differences") or [])
        heading = (pillar.get("name") or "").lower()
        # A pillar may carry the full differentiator or a concise heading of it ("Offline attendance check-in").
        ordered = sorted(diffs, key=lambda d: not (heading and (d.lower() in heading or heading in d.lower())))
        for d in ordered:
            refs = [r for f in differences if d.lower() in _statement(f).lower() for r in f.get("refs") or []]
            if refs:
                return {"text": d, "field": "differentiators", "competitor_refs": refs}
        if ordered:
            return {"text": ordered[0], "field": "differentiators", "competitor_refs": []}
        return {}

    async def _build_state(self, project: Project, product: Product, strategy: PromotionStrategy,
                           pillar_index: int, instructions: str) -> Tuple[dict, dict]:
        profile = {k: v for k, v in (product.profile or {}).items() if v and k not in _PROFILE_SKIP}
        plan = strategy.strategy
        pillars = plan.get("content_pillars") or []
        pillar = pillars[pillar_index]
        audience, direction = plan.get("audience") or {}, plan.get("content_direction") or {}
        channels = plan.get("channels") or []
        primary_channel = next((c for c in channels if c.get("priority") == "primary"), channels[0] if channels else {})
        limited = bool(product.competitor_limited_evidence)
        comparison = (product.competitor_comparison
                      if product.competitor_comparison_version == product.competitor_version else None)
        product_name = (profile.get("name") or product.name or "").strip()

        query = " ".join(filter(None, [pillar.get("name"), pillar.get("relation_to_product"), profile.get("value_proposition")]))
        sources, full_source, excerpt_meta, retrieval = await self._sources(project, query or product_name)
        competitor_names, competitor_texts = await self._competitor_material(product)

        evidence: Dict[str, str] = {label: title for label, title, _ in sources}
        evidence.update({f"P:{k}": f"Approved profile: {k.replace('_', ' ')}" for k in profile})
        context: List[Tuple[str, str]] = [
            ("Our approved Product Profile (cite as P:<field>)", json.dumps(profile, ensure_ascii=False, indent=1)),
        ]
        for label, title, text in sources:
            context.append((f"{label} — {title} (our own material)", text))

        strategy_view = {
            "primary_audience": audience.get("primary_audience"),
            "problems_and_needs": audience.get("problems_and_needs"),
            "value_proposition": audience.get("value_proposition"),
            "differentiators": audience.get("differentiators"),
            "messaging_direction": audience.get("messaging_direction"),
            "messaging_angles": direction.get("messaging_angles"),
            "primary_channel": primary_channel.get("channel"),
        }
        context.append(("Approved Promotion Strategy (positioning)", json.dumps(strategy_view, ensure_ascii=False, indent=1)))
        context.append(("Selected content pillar for THIS post", json.dumps(
            {k: pillar.get(k) for k in ("name", "purpose", "relation_to_product")}, ensure_ascii=False, indent=1)))

        competitor_refs: List[str] = []
        if limited:
            context.append(("Competitor insights", "LIMITED — Competitor Analysis was approved without full evidence. "
                                                   "Do not position against competitors; rely on the Product Profile."))
        elif comparison:
            context += _competitor_prompt_sections(competitor_findings(comparison))
            for ref, info in (comparison.get("references") or {}).items():
                competitor_refs.append(ref)
                evidence[ref] = f"Competitor evidence ({info.get('competitor')}): {info.get('title') or info.get('kind')}"
        if instructions:
            context.append(("Campaign instructions from the user (follow them within the approved context)", instructions))
        policy = platform_policy()
        context.append(("Platform rules", f"{policy.name}: at most {policy.max_chars} characters in total; the hook should "
                                          f"fit in about {policy.hook_max_chars} characters; at most {policy.max_hashtags} hashtags."))
        allowed = [label for label, _, _ in sources] + [f"P:{k}" for k in profile] + competitor_refs
        context.append(("Allowed references", ", ".join(allowed)))

        emphasis = self._emphasis(profile, pillar, comparison, limited)
        context_limitations = []
        if limited:
            context_limitations.append("Competitor evidence was limited, so the post is positioned from the Product Profile only.")
        if not sources:
            context_limitations.append("The project has no ingested sources, so claims rely on the approved profile.")

        state = {
            "prompt_context": context,
            "allowed_refs": allowed,
            "corpus": "\n".join([full_source, json.dumps(profile, ensure_ascii=False), json.dumps(plan, ensure_ascii=False), instructions]),
            "meta": {
                **pillar_context(pillar, profile),
                "product_name": product_name, "pillar": pillar.get("name"),
                "forbidden_names": await self._forbidden_names(product, product_name),
                "competitor_names": competitor_names, "competitor_texts": competitor_texts,
            },
            "demo_input": {
                "profile": profile, "product_name": product_name, "strategy": strategy_view, "pillar": pillar,
                "emphasis": emphasis, "source_text": full_source, "instructions": instructions,
                "context_limitations": context_limitations,
            },
        }
        snapshot = {
            "product_id": str(product.id), "product_name": product_name,
            "profile_version": product.profile_version, "competitor_version": product.competitor_version,
            "competitor_approved_version": product.competitor_approved_version, "limited_evidence": limited,
            "strategy_id": str(strategy.id), "strategy_version": strategy.version,
            "content_type": MVP_CONTENT_TYPE, "platform": policy.key,
            "pillar_index": pillar_index, "pillar": pillar.get("name"), "instructions": instructions,
            "primary_channel": primary_channel.get("channel"), "emphasis": emphasis.get("text"),
            "evidence": evidence, "source_count": len(sources),
            # Retrieved excerpts cited by this post: where they came from, so Evaluate & Improve can tell when a
            # cited excerpt changed or disappeared. Excerpts are unverified source text, not approved facts.
            "evidence_meta": excerpt_meta, "retrieval": retrieval,
        }
        return state, snapshot

    # ─── Generate / edit ────────────────────────────────────────────────────

    async def generate(self, project_id: UUID, pillar_index: int = 0, instructions: Optional[str] = None) -> GeneratedContent:
        project, stages = await self.get_project(project_id)
        if not uses_product_workflow(stages):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Generate Content is part of the product workflow; this project uses the legacy workflow.")
        ready = await self.readiness(project, stages)
        if ready["problem"]:
            raise HTTPException(status_code=ready["problem_status"], detail=ready["problem"])
        product, strategy = ready["product"], ready["strategy"]
        pillars = strategy.strategy.get("content_pillars") or []
        if not pillars:
            raise HTTPException(status_code=409, detail="The approved Promotion Strategy has no content pillars.")
        if not 0 <= pillar_index < len(pillars):
            raise HTTPException(status_code=422, detail=f"Choose a content pillar between 1 and {len(pillars)}.")
        instructions = (instructions or "").strip()
        if len(instructions) > MAX_INSTRUCTIONS_CHARS:
            raise HTTPException(status_code=422, detail=f"Campaign instructions are limited to {MAX_INSTRUCTIONS_CHARS} characters.")

        existing = await self.get_draft(project)
        if existing and existing.status == "approved":
            raise HTTPException(status_code=409, detail="This post has been approved. It cannot be regenerated or overwritten.")

        state, snapshot = await self._build_state(project, product, strategy, pillar_index, instructions)
        try:
            with collect_usage() as usage_records:  # real-provider requests only; Demo Mode records nothing
                result = await run_linkedin_generation(state)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=f"LinkedIn post generation failed: {e}")

        provider = normalize_provider_name(settings.AI_PROVIDER)
        draft = existing or GeneratedContent(project_id=project.id, product_id=product.id, content_type=MVP_CONTENT_TYPE,
                                             platform=platform_policy().key, version=0)
        if existing is None:
            self.db.add(draft)
        draft.product_id = product.id
        draft.content = result["post"]
        draft.validation = self._report(result["validation"])
        draft.status = "draft"
        draft.version = (draft.version or 0) + 1
        draft.edited = False
        draft.edited_at = None
        draft.context_snapshot = snapshot
        draft.provider = provider
        draft.is_demo = provider == "demo"
        draft.generated_at = _now()
        draft.usage = summarize_usage(usage_records, draft.version)
        try:
            await self.db.flush()
        except IntegrityError:
            # A second request (e.g. a double click) saved the first post for this project at the same moment.
            await self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="This post was just generated by another request. Reload to see the saved post.")
        stage = stages.get(STAGE_KEY)
        if stage:
            stage.data = {"generated_content_id": str(draft.id), "version": draft.version, "pillar": snapshot["pillar"]}
        await self.db.commit()
        return draft

    @staticmethod
    def _report(validation: dict) -> dict:
        return {k: validation.get(k) for k in ("warnings", "unsupported_claims", "character_count", "platform_limit",
                                               "within_limit", "issues")}

    async def update(self, project_id: UUID, changes: Dict[str, Any], version: Optional[int]) -> GeneratedContent:
        project, stages = await self.get_project(project_id)
        draft = await self.get_draft(project)
        if not draft:
            raise HTTPException(status_code=404, detail="No generated post yet. Generate one first.")
        if draft.status == "approved":
            raise HTTPException(status_code=409, detail="This post has been approved and can no longer be edited.")
        if version is not None and version != draft.version:
            raise HTTPException(status_code=409, detail="The post changed since you opened it. Reload the latest version.")
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown field(s): {', '.join(sorted(unknown))}")
        merged = {**draft.content, **changes}

        product = await self.products.get_product(draft.product_id)
        allowed, corpus, meta = await self.saved_validation_inputs(project, product, draft)
        report = validate_post(merged, allowed, corpus, meta, platform_policy())
        blocking = [i["message"] for i in report["issues"] if i["code"] in EDIT_BLOCKING]
        if blocking:
            raise HTTPException(status_code=422, detail=" ".join(blocking))
        report["warnings"] = [i["message"] for i in report["issues"]] + report["warnings"]
        report["warnings"].append("Edited by hand: the claims and evidence list describe the generated text; check them against your edits.")
        report["issues"] = []

        draft.content = report["post"]
        draft.validation = self._report(report)
        draft.version = (draft.version or 0) + 1
        draft.edited = True
        draft.edited_at = _now()
        stage = stages.get(STAGE_KEY)
        if stage:
            stage.data = {**(stage.data or {}), "version": draft.version}
        await self.db.commit()
        return draft

    async def saved_validation_inputs(self, project: Project, product: Product, draft: GeneratedContent):
        """(allowed_refs, corpus, meta) for re-validating a SAVED draft — used by manual saves and by
        Evaluate & Improve, so both always judge a post the same way."""
        snapshot = draft.context_snapshot or {}
        names, texts = await self._competitor_material(product)
        product_name = snapshot.get("product_name") or product.name
        sources = await get_project_source_texts(self.db, project)
        strategy = await self.strategies.get_strategy(product)
        corpus = "\n".join([b for _, b in sources] + [json.dumps(product.profile or {}, ensure_ascii=False),
                                                       json.dumps(strategy.strategy if strategy else {}, ensure_ascii=False),
                                                       snapshot.get("instructions") or ""])
        meta = {**self._saved_pillar_context(snapshot, product, strategy),
                "product_name": product_name, "pillar": snapshot.get("pillar"), "competitor_names": names,
                "competitor_texts": texts, "forbidden_names": await self._forbidden_names(product, product_name)}
        return list((snapshot.get("evidence") or {}).keys()), corpus, meta

    @staticmethod
    def _saved_pillar_context(snapshot: dict, product: Product, strategy: Optional[PromotionStrategy]) -> dict:
        """Pillar details for re-validating a saved draft: the strategy pillar it was generated for (matched by
        index and name), or none — then only the literal pillar check applies."""
        pillars = (strategy.strategy.get("content_pillars") if strategy else None) or []
        index = snapshot.get("pillar_index")
        pillar = pillars[index] if isinstance(index, int) and 0 <= index < len(pillars) else None
        if not pillar or pillar.get("name") != snapshot.get("pillar"):
            pillar = None
        profile = {k: v for k, v in (product.profile or {}).items() if v and k not in _PROFILE_SKIP}
        return pillar_context(pillar, profile) if pillar else {}

    # ─── Review Approval ────────────────────────────────────────────────────

    async def approve(self, project_id: UUID, version: int) -> GeneratedContent:
        """A human approves the CURRENTLY SAVED version of the post. Records the decision only: nothing is
        published, scheduled or sent to any platform."""
        project, stages = await self.get_project(project_id)  # 404 unless owned
        if not uses_product_workflow(stages):
            raise HTTPException(status_code=409, detail="Review Approval of generated posts is part of the product workflow.")
        draft = await self.get_draft(project)
        if not draft:
            raise HTTPException(status_code=409, detail="There is no saved post to approve. Generate one first.")
        if draft.status == "approved":
            raise HTTPException(status_code=409, detail=f"Version {draft.approved_version} of this post is already approved.")
        if version != draft.version:
            raise HTTPException(status_code=409, detail="The saved post changed since you opened it. Review the latest "
                                                        "version before approving.")
        ready = await self.readiness(project, stages)
        if ready["problem"]:
            raise HTTPException(status_code=409, detail=f"Cannot approve: {ready['problem']}")
        stale = self.stale_reasons(draft, ready["product"], ready["strategy"], ready["approved_type"])
        if stale:
            raise HTTPException(status_code=409, detail="Cannot approve a stale post: " + " ".join(stale) + " Regenerate it first.")
        from app.services.evaluation_service import evaluation_problem

        problem = await evaluation_problem(self.db, project, stages, draft)
        if problem:
            raise HTTPException(status_code=409, detail=f"Cannot approve: {problem}")
        if not (draft.validation or {}).get("within_limit", True):
            raise HTTPException(status_code=409, detail="The saved post is over the platform's character limit.")

        draft.status = "approved"
        draft.approved_version = draft.version
        draft.approved_at = _now()
        stage = stages.get(REVIEW_STAGE_KEY)
        if stage:
            stage.data = {**(stage.data or {}), "generated_content_id": str(draft.id), "approved_version": draft.version,
                          "approved_at": draft.approved_at.isoformat()}
        await self.db.commit()
        return draft

    async def has_current_approval(self, project: Project) -> bool:
        draft = await self.get_draft(project)
        return bool(draft and draft.status == "approved" and draft.approved_version == draft.version)

    # ─── State for the UI ───────────────────────────────────────────────────

    def stale_reasons(self, draft: GeneratedContent, product: Optional[Product], strategy: Optional[PromotionStrategy],
                      approved_type: Optional[str]) -> List[str]:
        snap = draft.context_snapshot or {}
        reasons = []
        if not product or str(product.id) != snap.get("product_id"):
            reasons.append("The project is now linked to a different product.")
            return reasons
        if snap.get("profile_version") != product.profile_version:
            reasons.append("The Product Profile changed after this post was generated.")
        if snap.get("competitor_version") != product.competitor_version:
            reasons.append("The Competitor Analysis changed after this post was generated.")
        if not strategy or snap.get("strategy_version") != strategy.version:
            reasons.append("The Promotion Strategy changed (or is no longer approved) after this post was generated.")
        if approved_type != snap.get("content_type"):
            reasons.append("The approved Content Type changed after this post was generated.")
        return reasons

    async def state(self, project_id: UUID) -> Dict[str, Any]:
        project, stages = await self.get_project(project_id)
        policy = platform_policy()
        base: Dict[str, Any] = {
            "project_id": project.id,
            "policy": {"platform": policy.name, "content_type": policy.content_type, "max_chars": policy.max_chars,
                       "hook_max_chars": policy.hook_max_chars, "max_hashtags": policy.max_hashtags},
            "provider": normalize_provider_name(settings.AI_PROVIDER),
        }
        if not uses_product_workflow(stages):
            return {**base, "status": "not_applicable", "can_generate": False, "prerequisites": [],
                    "blocking_problem": "Generate Content is part of the product workflow; this project uses the legacy workflow."}
        ready = await self.readiness(project, stages)
        product, strategy = ready["product"], ready["strategy"]
        context = None
        if product:
            profile = product.profile or {}
            plan = strategy.strategy if strategy else {}
            audience = plan.get("audience") or {}
            channels = plan.get("channels") or []
            comparison = (product.competitor_comparison
                          if product.competitor_comparison_version == product.competitor_version else None) or {}
            competitor_current = (product.competitor_analysis_status == "approved"
                                  and product.competitor_approved_version == product.competitor_version and bool(comparison))
            context = {
                "product_id": product.id, "product_name": profile.get("name") or product.name,
                "target_audience": audience.get("primary_audience") or profile.get("target_audience"),
                "problem_solved": profile.get("problem_solved"),
                "value_proposition": audience.get("value_proposition") or profile.get("value_proposition"),
                "key_features": profile.get("key_features") or [],
                "differentiators": profile.get("differentiators") or [],
                "messaging_direction": audience.get("messaging_direction"),
                "pillars": [{"name": p.get("name"), "purpose": p.get("purpose")} for p in plan.get("content_pillars") or []],
                "primary_channel": next((c.get("channel") for c in channels if c.get("priority") == "primary"), None),
                "approved_type": ready["approved_type"],
                "limited_evidence": bool(product.competitor_limited_evidence),
                # Approved, current comparison only; the same four groups the generator receives.
                "competitor": None if product.competitor_limited_evidence or not competitor_current
                else competitor_findings(comparison),
            }
        draft = await self.get_draft(project)
        draft_view = None
        stale: List[str] = []
        if draft:
            stale = self.stale_reasons(draft, product, strategy, ready["approved_type"])
            draft_view = {
                "id": draft.id, "content": draft.content, "validation": draft.validation, "status": draft.status,
                "version": draft.version, "edited": draft.edited, "provider": draft.provider, "is_demo": draft.is_demo,
                "generated_at": draft.generated_at, "edited_at": draft.edited_at,
                "approved_version": draft.approved_version, "approved_at": draft.approved_at,
                "usage": draft.usage,
                # Evidence labels (e.g. "P:key_features") are values, not keys, so clients that rewrite keys keep them intact.
                "context_snapshot": {k: v for k, v in (draft.context_snapshot or {}).items() if k != "evidence"},
                "evidence": [{"ref": ref, "description": text} for ref, text in ((draft.context_snapshot or {}).get("evidence") or {}).items()],
            }
        if draft:
            status_ = "approved" if draft.status == "approved" else "draft"
        else:
            status_ = "blocked" if ready["problem"] else "not_generated"
        return {
            **base, "status": status_, "can_generate": ready["problem"] is None and status_ != "approved",
            "prerequisites": ready["checks"], "blocking_problem": ready["problem"], "context": context,
            "draft": draft_view, "stale": bool(stale), "stale_reasons": stale,
        }
