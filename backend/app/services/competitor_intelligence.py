"""Competitor intelligence providers — where candidate competitors (and, later, evidence) come from.

Implemented today:
- ProductSourcesIntelligence: competitors explicitly named in the approved Product Profile
  (i.e. in the user's own product sources);
- AISuggestionIntelligence: candidates suggested by a REAL AI provider from the approved profile,
  always marked unverified. Not available in Demo Mode, which never invents companies.

Future integrations (e.g. UGC Explorer for competitor UGC, Key Signals for market signals) would
implement this same interface. They are NOT implemented: no class for them exists, and nothing in
MCF claims to use them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from app.ai.config import normalize_provider_name
from app.ai.graphs.competitor_graph import run_competitor_suggestions
from app.ai.prompts import bullet_list


@dataclass
class CandidateCompetitor:
    name: str
    origin: str  # product_sources | ai_suggested
    reason: str
    website_url: Optional[str] = None


class CompetitorIntelligenceProvider(ABC):
    key: str
    label: str

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can run in the current configuration."""

    @abstractmethod
    async def discover_candidates(self, profile: dict, existing_names: List[str]) -> List[CandidateCompetitor]:
        """Candidate competitors for the product. Must not return names already in existing_names."""

    async def collect_evidence(self, competitor_name: str, website_url: Optional[str]) -> List[dict]:
        """Evidence about a competitor. Current providers collect none; evidence is supplied by the user."""
        return []


def _is_new(name: str, existing: List[str], product_name: Optional[str]) -> bool:
    key = name.strip().lower()
    return bool(key) and key not in {e.strip().lower() for e in existing} and key != (product_name or "").strip().lower()


class ProductSourcesIntelligence(CompetitorIntelligenceProvider):
    key = "product_sources"
    label = "Named in your product sources"

    def is_available(self) -> bool:
        return True

    async def discover_candidates(self, profile: dict, existing_names: List[str]) -> List[CandidateCompetitor]:
        return [
            CandidateCompetitor(name=n.strip(), origin=self.key, reason="Named as a competitor or alternative in your product sources.")
            for n in profile.get("known_competitors") or []
            if _is_new(n, existing_names, profile.get("name"))
        ]


class AISuggestionIntelligence(CompetitorIntelligenceProvider):
    key = "ai_suggested"
    label = "Suggested by AI (unverified)"

    def is_available(self) -> bool:
        from app.core.config import settings

        return normalize_provider_name(settings.AI_PROVIDER) in ("claude", "openai")

    async def discover_candidates(self, profile: dict, existing_names: List[str]) -> List[CandidateCompetitor]:
        import json

        context = [
            ("Our approved Product Profile", json.dumps({k: v for k, v in profile.items() if v and k != "source_references"}, ensure_ascii=False, indent=1)),
            ("Competitors already listed", bullet_list(existing_names) or None),
        ]
        output = await run_competitor_suggestions({"prompt_context": context})
        return [
            CandidateCompetitor(name=c["name"].strip(), origin=self.key, reason=c.get("why_relevant") or "", website_url=c.get("website_url"))
            for c in (output.get("candidates") or [])[:5]
            if _is_new(c.get("name", ""), existing_names, profile.get("name"))
        ]


class KeySignalsIntelligence(CompetitorIntelligenceProvider):
    key = "key_signals"
    label = "Key Signals (GDELT)"

    def is_available(self) -> bool:
        from app.core.config import settings

        # Available when real AI/research is active; Demo Mode stays strictly offline
        return normalize_provider_name(settings.AI_PROVIDER) in ("claude", "openai")

    async def discover_candidates(self, profile: dict, existing_names: List[str]) -> List[CandidateCompetitor]:
        # Candidate discovery from GDELT relies on explicit signal search; background discovery does not invent candidates.
        return []

    async def collect_evidence(self, competitor_name: str, website_url: Optional[str] = None) -> List[dict]:
        from app.services.gdelt_provider import GDELTProvider

        provider = GDELTProvider()
        res = await provider.search_articles(competitor_name, max_records=5)
        if res.get("status") == "success":
            return res.get("articles") or []
        return []


class UGCExplorerIntelligence(CompetitorIntelligenceProvider):
    key = "ugc_explorer"
    label = "UGC Explorer (Reddit)"

    def is_available(self) -> bool:
        from app.core.config import settings
        from app.services.reddit_provider import RedditUGCProvider

        return (
            RedditUGCProvider.is_configured()
            and normalize_provider_name(settings.AI_PROVIDER) in ("claude", "openai")
        )

    async def discover_candidates(self, profile: dict, existing_names: List[str]) -> List[CandidateCompetitor]:
        return []

    async def collect_evidence(self, competitor_name: str, website_url: Optional[str] = None) -> List[dict]:
        from app.services.reddit_provider import RedditUGCProvider

        provider = RedditUGCProvider()
        res = await provider.search_posts(competitor_name, max_results=5)
        if res.get("status") == "success":
            return res.get("posts") or []
        return []


def intelligence_providers() -> List[CompetitorIntelligenceProvider]:
    return [
        ProductSourcesIntelligence(),
        AISuggestionIntelligence(),
        KeySignalsIntelligence(),
        UGCExplorerIntelligence(),
    ]
