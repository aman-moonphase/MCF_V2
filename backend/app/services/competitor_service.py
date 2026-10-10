"""Competitor Analysis for an approved Product.

Ownership: every call resolves the Product through ProductService (owner-scoped), every competitor
through its product_id, and every evidence item through its competitor_id and product_id. Mutations
require the Product Profile to be approved (and still current).
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.competitor_schemas import FINDING_SECTIONS, PERFORMANCE_DATA_NOTE, SECTION_LABELS
from app.ai.config import normalize_provider_name
from app.ai.graphs.competitor_graph import run_competitor_analysis, run_competitor_comparison
from app.core.config import settings
from app.core.url_safety import UnsafeURLError, validate_public_url
from app.models.competitor import Competitor, CompetitorEvidence
from app.models.product import Product
from app.models.workflow_stage import WorkflowStage
from app.services.competitor_intelligence import intelligence_providers
from app.services.extraction_service import ExtractionService
from app.core.text_encoding import repair_mojibake
from app.ai.competitor_grounding import EVIDENCE_GAP_PREFIX
from app.ai.providers.demo_competitor import _mentioned
from app.services.product_service import ProductService

STAGE_KEY = "competitor-analysis"
MAX_EVIDENCE_CHARS_IN_PROMPT = 12000
# MCF does not scrape social platforms (logins, terms of service). Users paste observations instead.
RESTRICTED_DOMAINS = (
    "linkedin.com", "instagram.com", "facebook.com", "fb.com", "x.com", "twitter.com", "tiktok.com",
    "threads.net", "pinterest.com", "reddit.com", "youtube.com", "youtu.be",
)
EDITABLE_FIELDS = ("name", "website_url", "description", "notes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_restricted(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in RESTRICTED_DOMAINS)


def _capped(text: str) -> str:
    if len(text) <= MAX_EVIDENCE_CHARS_IN_PROMPT:
        return text
    return text[:MAX_EVIDENCE_CHARS_IN_PROMPT] + f"\n[Evidence truncated for this prompt: first {MAX_EVIDENCE_CHARS_IN_PROMPT:,} of {len(text):,} characters.]"


def _insufficient_analysis() -> dict:
    coverage = {s: "unknown" for s in (*FINDING_SECTIONS, "content_examples")}
    return {
        **{s: [] for s in FINDING_SECTIONS},
        "content_examples": [],
        "coverage": coverage,
        "unknown_sections": list(coverage),
        "unknowns": [
            "No evidence yet. Add the competitor's website URL, paste observations (e.g. posts or ads you have seen), "
            "upload a PDF, or describe their product."
        ],
        "performance_data": PERFORMANCE_DATA_NOTE,
        "confidence": "low",
        "references": {},
    }


def _unresolved_features(product: Product, competitor: Competitor) -> List[str]:
    """Feature comparisons the supplied evidence does not settle. Unresolved is not absent."""
    covered = " ".join(f["statement"] for f in (competitor.analysis or {}).get("overlapping_features") or []).lower()
    return [f"{competitor.name}: the supplied evidence does not establish whether {competitor.name} offers something like "
            f"our \"{feature}\". This comparison is unresolved (not evidence that the feature is absent) — add their "
            "feature list, help pages or pricing page to settle it."
            for feature in (product.profile or {}).get("key_features") or [] if feature.lower() not in covered]


def _evidence_gaps(product: Product, name: str, analysis: dict, evidence_text: str) -> List[str]:
    """Unknowns for OUR features and differentiators the supplied evidence does not show.

    Not shown is not absent: each is an unknown, and a differentiator is only a messaging angle to
    investigate (a hypothesis), never a confirmed competitor weakness. One line per item, no duplicates.
    """
    profile = product.profile or {}
    covered = " ".join(f["statement"] for f in analysis.get("overlapping_features") or []).lower()
    differentiators = [d for d in profile.get("differentiators") or [] if d]
    hypothesis = (" Messaging angle to investigate (hypothesis, not a confirmed weakness): it is one of our "
                  "differentiators — verify before positioning against " + name + ".")
    lines, used = [], set()
    for feature in profile.get("key_features") or []:
        if feature.lower() in covered:
            continue
        line = f"Whether {name} offers something like our \"{feature}\" is unknown: the supplied evidence does not show it."
        linked = [d for d in differentiators if feature.lower() in d.lower() or d.lower() in feature.lower()]
        if linked:
            used.update(linked)
            line += hypothesis
        lines.append(line)
    for d in differentiators:
        if d not in used and not _mentioned(d, evidence_text):
            lines.append(f"The supplied evidence for {name} does not mention our differentiator \"{d}\"." + hypothesis)
    return lines


class CompetitorService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.products = ProductService(db, user_id)

    # ─── Ownership / prerequisites ─────────────────────────────────────────

    async def get_product(self, product_id: UUID) -> Product:
        return await self.products.get_product(product_id)

    @staticmethod
    def profile_is_approved(product: Product) -> bool:
        return product.understanding_status == "approved" and product.approved_version == product.profile_version

    async def approved_product(self, product_id: UUID) -> Product:
        product = await self.get_product(product_id)
        if not self.profile_is_approved(product):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approve the Product Profile before working on Competitor Analysis.",
            )
        return product

    async def competitors(self, product: Product) -> List[Competitor]:
        result = await self.db.execute(
            select(Competitor).where(Competitor.product_id == product.id).order_by(Competitor.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_competitor(self, product: Product, competitor_id: UUID) -> Competitor:
        result = await self.db.execute(
            select(Competitor).where(Competitor.id == competitor_id, Competitor.product_id == product.id)
        )
        competitor = result.scalar_one_or_none()
        if not competitor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
        return competitor

    async def evidence_for(self, competitor: Competitor) -> List[CompetitorEvidence]:
        result = await self.db.execute(
            select(CompetitorEvidence)
            .where(CompetitorEvidence.competitor_id == competitor.id, CompetitorEvidence.product_id == competitor.product_id)
            .order_by(CompetitorEvidence.created_at.asc())
        )
        return list(result.scalars().all())

    async def _name_taken(self, product: Product, name: str, exclude: Optional[UUID] = None) -> bool:
        query = select(func.count(Competitor.id)).where(
            Competitor.product_id == product.id, func.lower(Competitor.name) == name.strip().lower()
        )
        if exclude:
            query = query.where(Competitor.id != exclude)
        return (await self.db.scalar(query)) > 0

    def _touch(self, product: Product) -> None:
        """Any change to competitors invalidates approval and makes the comparison outdated."""
        product.competitor_version = (product.competitor_version or 0) + 1
        product.competitor_analysis_status = "in_progress"

    # ─── Competitors ───────────────────────────────────────────────────────

    async def create_competitor(self, product_id: UUID, data: Dict[str, Any], origin: str = "user", reason: Optional[str] = None) -> Competitor:
        product = await self.approved_product(product_id)
        return await self._create(product, data, origin, reason)

    async def _create(self, product: Product, data: Dict[str, Any], origin: str, reason: Optional[str]) -> Competitor:
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Competitor name is required.")
        if await self._name_taken(product, name):
            raise HTTPException(status_code=409, detail=f"'{name}' is already in the competitor list.")
        website = self._clean_url(data.get("website_url"))
        competitor = Competitor(
            product_id=product.id, name=name[:255], website_url=website,
            description=(data.get("description") or "").strip() or None,
            notes=(data.get("notes") or "").strip() or None,
            origin=origin, suggestion_reason=reason,
        )
        self.db.add(competitor)
        self._touch(product)
        await self.db.commit()
        return competitor

    @staticmethod
    def _clean_url(url: Optional[str]) -> Optional[str]:
        url = (url or "").strip()
        if not url:
            return None
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) and not re.match(r"^https?://", url, re.I):
            raise HTTPException(status_code=422, detail="Website URL must be a valid http(s) URL.")
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise HTTPException(status_code=422, detail="Website URL must be a valid http(s) URL.")
        return url[:1024]

    async def update_competitor(self, product_id: UUID, competitor_id: UUID, changes: Dict[str, Any]) -> Competitor:
        product = await self.approved_product(product_id)
        competitor = await self.get_competitor(product, competitor_id)
        for field in EDITABLE_FIELDS:
            if field not in changes:
                continue
            value = changes[field]
            if field == "name":
                value = (value or "").strip()
                if not value:
                    raise HTTPException(status_code=422, detail="Competitor name is required.")
                if await self._name_taken(product, value, exclude=competitor.id):
                    raise HTTPException(status_code=409, detail=f"'{value}' is already in the competitor list.")
            elif field == "website_url":
                value = self._clean_url(value)
            else:
                value = (value or "").strip() or None
            setattr(competitor, field, value)
        self._touch(product)
        await self.db.commit()
        return competitor

    async def delete_competitor(self, product_id: UUID, competitor_id: UUID) -> None:
        product = await self.approved_product(product_id)
        competitor = await self.get_competitor(product, competitor_id)
        await self.db.delete(competitor)
        self._touch(product)
        await self.db.commit()

    async def discover(self, product_id: UUID) -> Dict[str, Any]:
        product = await self.approved_product(product_id)
        existing = [c.name for c in await self.competitors(product)]
        added, messages = [], []
        for provider in intelligence_providers():
            if not provider.is_available():
                messages.append(f"{provider.label}: not available in the current configuration (Demo Mode never invents competitors).")
                continue
            try:
                candidates = await provider.discover_candidates(product.profile or {}, existing)
            except Exception as e:  # a failing optional provider must not block the others
                messages.append(f"{provider.label}: failed ({e}).")
                continue
            for c in candidates:
                await self._create(product, {"name": c.name, "website_url": c.website_url}, c.origin, c.reason)
                existing.append(c.name)
                added.append(c.name)
            if not candidates:
                messages.append(f"{provider.label}: no new candidates.")
        if not added and not existing:
            messages.append("No competitors found. Add the competitors you know, with their website or your observations.")
        return {"added": added, "messages": messages}

    # ─── Evidence ──────────────────────────────────────────────────────────

    async def add_evidence(self, product_id: UUID, competitor_id: UUID, evidence_type: str,
                           content: Optional[str] = None, title: Optional[str] = None,
                           file_bytes: Optional[bytes] = None, filename: Optional[str] = None) -> CompetitorEvidence:
        product = await self.approved_product(product_id)
        competitor = await self.get_competitor(product, competitor_id)
        evidence = CompetitorEvidence(competitor_id=competitor.id, product_id=product.id, evidence_type=evidence_type)

        if evidence_type == "url":
            try:
                url = validate_public_url((content or "").strip(), allow_private=settings.ALLOW_PRIVATE_URL_INGESTION)
            except UnsafeURLError as e:
                raise HTTPException(status_code=400, detail=str(e))
            evidence.source_url = url[:1024]
            evidence.title = (title or url)[:255]
            if _is_restricted(url):
                evidence.status = "not_fetched"
                evidence.error = ("MCF does not fetch social media platforms. Paste what you observed there "
                                  "(posts, ads, captions) as a note instead.")
            else:
                try:
                    extracted = await asyncio.to_thread(ExtractionService.extract_from_url, url)
                    evidence.content = extracted.text
                    evidence.title = (title or extracted.metadata.get("title") or url)[:255]
                    evidence.status = "completed"
                except Exception as e:
                    evidence.status = "failed"
                    evidence.error = f"Could not fetch this page: {e}"
        elif evidence_type == "note":
            text = (content or "").strip()
            if not text:
                raise HTTPException(status_code=422, detail="Note text is required.")
            evidence.content = text
            evidence.title = (title or "Your observations")[:255]
            evidence.status = "completed"
        elif evidence_type == "pdf":
            if not file_bytes:
                raise HTTPException(status_code=422, detail="A PDF file is required.")
            from app.api.routes.sources import safe_display_name

            evidence.title = (title or safe_display_name(filename))[:255]
            try:
                extracted = await asyncio.to_thread(ExtractionService.extract_from_pdf, file_bytes)
                evidence.content = extracted.text
                evidence.status = "completed"
            except Exception as e:
                evidence.status = "failed"
                evidence.error = f"Could not read this PDF: {e}"
        else:
            raise HTTPException(status_code=422, detail="evidence_type must be url, note, or pdf.")

        self.db.add(evidence)
        self._touch(product)
        await self.db.commit()
        return evidence

    async def delete_evidence(self, product_id: UUID, competitor_id: UUID, evidence_id: UUID) -> None:
        product = await self.approved_product(product_id)
        competitor = await self.get_competitor(product, competitor_id)
        result = await self.db.execute(
            select(CompetitorEvidence).where(
                CompetitorEvidence.id == evidence_id,
                CompetitorEvidence.competitor_id == competitor.id,
                CompetitorEvidence.product_id == product.id,
            )
        )
        evidence = result.scalar_one_or_none()
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")
        await self.db.delete(evidence)
        self._touch(product)
        await self.db.commit()

    # ─── Analysis ──────────────────────────────────────────────────────────

    def _items(self, competitor: Competitor, evidence: List[CompetitorEvidence]) -> List[dict]:
        items = []
        for i, e in enumerate([e for e in evidence if e.status == "completed" and (e.content or "").strip()], start=1):
            items.append({"label": f"E{i}", "kind": e.evidence_type, "evidence_id": str(e.id), "title": e.title,
                          "url": e.source_url, "text": repair_mojibake(e.content)})
        if competitor.description:
            items.append({"label": "D", "kind": "user_description", "evidence_id": None, "title": "Your description", "url": None, "text": competitor.description})
        if competitor.notes:
            items.append({"label": "N", "kind": "user_notes", "evidence_id": None, "title": "Your notes", "url": None, "text": competitor.notes})
        return items

    @staticmethod
    def _profile_text(product: Product) -> str:
        profile = {k: v for k, v in (product.profile or {}).items() if v and k not in ("source_references", "missing_fields", "confidence")}
        return json.dumps(profile, ensure_ascii=False, indent=1)

    async def analyze(self, product_id: UUID, competitor_id: UUID) -> Competitor:
        product = await self.approved_product(product_id)
        competitor = await self.get_competitor(product, competitor_id)
        items = self._items(competitor, await self.evidence_for(competitor))
        references = {i["label"]: {k: i[k] for k in ("kind", "evidence_id", "title", "url")} for i in items}

        if not items:
            competitor.analysis = _insufficient_analysis()
            competitor.analysis_status = "insufficient_evidence"
            competitor.analysis_error = None
            competitor.last_analyzed_at = _now()
            self._touch(product)
            await self.db.commit()
            return competitor

        profile_text = self._profile_text(product)
        context = [("Our approved Product Profile", profile_text),
                   ("Competitor", competitor.name + (f" ({competitor.website_url})" if competitor.website_url else ""))]
        context += [(f"Evidence {i['label']} — {i['title']}" + (f" ({i['url']})" if i["url"] else ""), _capped(i["text"])) for i in items]
        state = {
            "prompt_context": context,
            "allowed_refs": list(references),
            "corpus": "\n".join(i["text"] for i in items) + "\n" + profile_text,
            "evidence_count": sum(1 for i in items if i["label"].startswith("E")),
            "demo_input": {"product": product.profile or {}, "competitor": {"name": competitor.name}, "items": items},
        }
        try:
            analysis = await run_competitor_analysis(state)
        except RuntimeError as e:
            competitor.analysis_status = "failed"
            competitor.analysis_error = str(e)
            await self.db.commit()
            raise HTTPException(status_code=500, detail=f"Competitor analysis failed: {e}")

        analysis["references"] = references
        analysis["provider"] = normalize_provider_name(settings.AI_PROVIDER)
        gaps = _evidence_gaps(product, competitor.name, analysis, " ".join(i["text"] for i in items))
        # A provider's own evidence-gap note about the same feature is replaced by the single line above.
        existing = [u for u in analysis.get("unknowns") or []
                    if not (u.startswith(EVIDENCE_GAP_PREFIX) and any(f'"{f.lower()}"' in u.lower() for f in
                                                                      (product.profile or {}).get("key_features") or []))]
        analysis["unknowns"] = existing + gaps
        competitor.analysis = analysis
        competitor.analysis_status = "analyzed"
        competitor.analysis_error = None
        competitor.last_analyzed_at = _now()
        self._touch(product)
        await self.db.commit()
        return competitor

    async def compare(self, product_id: UUID) -> Product:
        product = await self.approved_product(product_id)
        analyzed = [c for c in await self.competitors(product) if c.analysis_status == "analyzed" and c.analysis]
        if not analyzed:
            raise HTTPException(status_code=409, detail="Analyze at least one competitor with evidence before comparing.")

        context = [("Our approved Product Profile", self._profile_text(product))]
        allowed, references, competitors_map, demo, corpus = [], {}, {}, [], [self._profile_text(product)]
        for index, c in enumerate(analyzed, start=1):
            label = f"C{index}"
            competitors_map[label] = {"competitor_id": str(c.id), "name": c.name}
            lines = []
            for section in FINDING_SECTIONS:
                for f in c.analysis.get(section) or []:
                    refs = ", ".join(f"{label}:{r}" for r in f["refs"])
                    lines.append(f"[{SECTION_LABELS[section]}] ({f['status']}) {f['statement']}" + (f" [{refs}]" if refs else ""))
            context.append((f"Competitor {label}: {c.name} — analysed findings", "\n".join(lines) or "(no findings)"))
            for ref, info in (c.analysis.get("references") or {}).items():
                allowed.append(f"{label}:{ref}")
                references[f"{label}:{ref}"] = {**info, "competitor": c.name}
            items = self._items(c, await self.evidence_for(c))
            corpus += [i["text"] for i in items]
            demo.append({"label": label, "name": c.name, "analysis": c.analysis, "items": items})

        state = {
            "prompt_context": context, "allowed_refs": allowed, "corpus": "\n".join(corpus),
            "demo_input": {"product": product.profile or {}, "competitors": demo},
        }
        try:
            comparison = await run_competitor_comparison(state)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=f"Competitor comparison failed: {e}")

        unresolved = [line for c in analyzed for line in _unresolved_features(product, c)]
        comparison["evidence_needed"] = unresolved + [e for e in comparison.get("evidence_needed") or [] if e not in unresolved]
        comparison.update(competitors=competitors_map, references=references,
                          provider=normalize_provider_name(settings.AI_PROVIDER))
        product.competitor_comparison = comparison
        product.competitor_comparison_version = product.competitor_version
        product.competitor_comparison_at = _now()
        product.competitor_analysis_status = "ready_for_review"
        await self.db.commit()
        return product

    async def approve(self, product_id: UUID, project_id: UUID, version: int, limited_evidence: bool = False) -> Product:
        """Approve the analysis. When competitor evidence is unavailable, the user may explicitly approve a
        limited-evidence state instead, so the product is never blocked; later stages are told about it."""
        product = await self.approved_product(product_id)
        project = await self.products._linked_project(project_id, product)
        if version != product.competitor_version:
            raise HTTPException(status_code=409, detail="Competitor Analysis changed since you reviewed it. Review the latest version.")
        has_analysis = any(c.analysis_status == "analyzed" for c in await self.competitors(product))
        comparison_current = product.competitor_comparison_version == product.competitor_version
        complete = has_analysis and comparison_current
        if not complete and not limited_evidence:
            if not has_analysis:
                raise HTTPException(status_code=409, detail="Analyze at least one competitor with evidence before approving, "
                                                            "or explicitly approve with limited evidence.")
            raise HTTPException(status_code=409, detail="Generate the comparison with our product before approving.")
        product.competitor_limited_evidence = not complete
        product.competitor_analysis_status = "approved"
        product.competitor_approved_version = product.competitor_version
        product.competitor_approved_at = _now()
        await self.db.commit()

        stage = (await self.db.execute(
            select(WorkflowStage).where(WorkflowStage.project_id == project.id, WorkflowStage.stage_type == STAGE_KEY)
        )).scalar_one_or_none()
        if stage:
            stage.data = {"product_id": str(product.id), "approved_version": product.competitor_approved_version}
            await self.db.commit()
        return product
