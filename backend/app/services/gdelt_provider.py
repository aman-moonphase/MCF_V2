"""GDELT DOC 2.0 Article Search Provider.

Searches the global news media indexed by GDELT DOC 2.0 for competitor mentions,
industry developments, and market signals.

Features:
- Bounded result limits (max 15 articles) and strict timeouts (10 seconds).
- Normalization, validation, and SSRF prevention on article URLs.
- Deduplication by URL and normalized title.
- Clear evidence-strength classification and explicit disclaimers on limitations.
- Zero third-party library dependencies (uses httpx).
"""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import email.utils
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx

from app.core.url_safety import UnsafeURLError, validate_public_url

logger = logging.getLogger(__name__)

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RECORDS_LIMIT = 15

RATE_LIMIT_FRIENDLY_MESSAGE = "GDELT is temporarily rate-limiting searches. Please wait before trying again."
DEFAULT_BACKOFF_SECONDS = 15.0
MIN_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 60.0
CACHE_TTL_SECONDS = 300.0  # 5 minutes


def parse_retry_after(header_val: Optional[str], default_seconds: float = DEFAULT_BACKOFF_SECONDS) -> float:
    """Parse HTTP Retry-After header into seconds, respecting bounds [MIN_BACKOFF, MAX_BACKOFF]."""
    if not header_val or not isinstance(header_val, str):
        return default_seconds

    val = header_val.strip()
    # Try integer/float seconds
    try:
        secs = float(val)
        return max(MIN_BACKOFF_SECONDS, min(secs, MAX_BACKOFF_SECONDS))
    except ValueError:
        pass

    # Try HTTP date format (e.g. Wed, 21 Oct 2026 07:28:00 GMT)
    try:
        parsed_dt = email.utils.parsedate_to_datetime(val)
        if parsed_dt:
            diff = (parsed_dt - datetime.now(timezone.utc)).total_seconds()
            if diff > 0:
                return max(MIN_BACKOFF_SECONDS, min(diff, MAX_BACKOFF_SECONDS))
    except Exception:
        pass

    return default_seconds


@dataclass
class GDELTArticle:
    title: str
    source_url: str
    domain: str
    published_at: Optional[str]
    retrieved_at: str
    matching_query: str
    language: Optional[str] = None
    source_country: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _parse_gdelt_seendate(seendate: Optional[str]) -> Optional[str]:
    """Parse GDELT seendate format (e.g. 20261012T080000Z) to ISO 8601."""
    if not seendate or not isinstance(seendate, str):
        return None
    cleaned = seendate.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _clean_title(title: Optional[str]) -> str:
    """Clean HTML entities and trailing whitespace from article titles."""
    if not title:
        return ""
    text = title.strip()
    # Unescape basic HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def _normalize_title_key(title: str) -> str:
    """Normalize title for fuzzy deduplication."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _normalize_url_key(url: str) -> str:
    """Normalize URL by stripping fragments and tracking query params."""
    try:
        parsed = urlparse(url)
        # Drop fragment, lowercase host and scheme
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except Exception:
        return url.strip().lower()


def evaluate_evidence_strength(articles: List[GDELTArticle]) -> Dict[str, str]:
    """Evaluate evidence strength without labeling a single article as a trend."""
    count = len(articles)
    if count == 0:
        return {
            "strength": "no_signals",
            "label": "No Recent Signals",
            "summary": "No matching articles found in GDELT news indexing.",
            "limitations": (
                "GDELT DOC 2.0 indexes global digital news media over rolling timeframes. "
                "An absence of articles indicates a lack of tracked media coverage, but does not prove "
                "a competitor is inactive."
            ),
        }

    domains = {a.domain for a in articles if a.domain}
    domain_count = len(domains)

    if count == 1:
        domain_name = articles[0].domain or "a single source"
        return {
            "strength": "isolated_mention",
            "label": "Isolated Mention (Unverified)",
            "summary": f"Single media mention identified on {domain_name}. Not verified as an industry trend.",
            "limitations": (
                "A single article indicates isolated media coverage or a press release rather than an industry trend. "
                "Verify factual claims against primary documentation before treating them as confirmed."
            ),
        }

    if domain_count == 1:
        domain_name = next(iter(domains))
        return {
            "strength": "single_source_coverage",
            "label": "Single-Source Coverage",
            "summary": f"{count} articles found, but all originate from a single publisher ({domain_name}).",
            "limitations": (
                "Coverage is confined to a single news outlet. This often reflects syndicated PR or outlet focus "
                "rather than widespread industry momentum."
            ),
        }

    return {
        "strength": "multi_source_coverage",
        "label": "Multi-Source Media Coverage",
        "summary": f"{count} articles distributed across {domain_count} distinct news domains.",
        "limitations": (
            "Multiple distinct publishers are reporting on this topic. While this signals active media interest, "
            "specific competitor claims should still be cross-referenced with primary product evidence."
        ),
    }


class GDELTProvider:
    """Client for GDELT DOC 2.0 Article Search API with rate-limit cooldown and query caching."""

    # Class-level state shared across instances to prevent repeat requests and enforce backoff
    _cooldown_until: float = 0.0
    _cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    _lock: Optional[asyncio.Lock] = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    def reset_cooldown(cls) -> None:
        """Reset cooldown timestamp (used for testing and recovery)."""
        cls._cooldown_until = 0.0

    @classmethod
    def clear_cache(cls) -> None:
        """Clear query cache (used for testing or cache invalidation)."""
        cls._cache.clear()

    @classmethod
    def is_rate_limited(cls) -> bool:
        """Check whether provider is currently in cooldown."""
        return time.monotonic() < cls._cooldown_until

    @classmethod
    def get_cooldown_remaining(cls) -> int:
        """Return remaining cooldown in integer seconds (0 if not in cooldown)."""
        now = time.monotonic()
        if now < cls._cooldown_until:
            return max(1, int(math.ceil(cls._cooldown_until - now)))
        return 0

    @classmethod
    def set_cooldown(cls, seconds: float) -> None:
        """Set cooldown duration bounded between MIN_BACKOFF_SECONDS and MAX_BACKOFF_SECONDS."""
        bounded = max(MIN_BACKOFF_SECONDS, min(seconds, MAX_BACKOFF_SECONDS))
        cls._cooldown_until = time.monotonic() + bounded

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds

    async def search_articles(
        self,
        query: str,
        max_records: int = 10,
        allow_private_urls: bool = False,
    ) -> Dict[str, Any]:
        """Search articles using GDELT DOC 2.0.

        Returns a dictionary with:
        - status: "success" | "empty" | "error" | "rate_limited"
        - articles: List[Dict[str, Any]]
        - evidence_evaluation: Dict[str, str]
        - matching_query: str
        - total_found: int
        - error_message: Optional[str]
        - retry_after: Optional[int]
        - cached: bool
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "status": "empty",
                "articles": [],
                "evidence_evaluation": evaluate_evidence_strength([]),
                "matching_query": "",
                "total_found": 0,
                "error_message": "Query cannot be empty.",
                "retry_after": None,
                "cached": False,
            }

        bounded_limit = max(1, min(max_records, MAX_RECORDS_LIMIT))
        cache_key = f"{clean_query.lower()}:{bounded_limit}"

        # 1. Check in-memory cache for recent identical queries
        now = time.monotonic()
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.debug("Returning cached GDELT result for %s", clean_query)
                res = dict(cached_data)
                res["cached"] = True
                return res
            else:
                del self._cache[cache_key]

        # 2. Check provider-wide cooldown before attempting request
        if self.is_rate_limited():
            remaining = self.get_cooldown_remaining()
            logger.warning("GDELT DOC 2.0 is in rate-limit cooldown for another %ds", remaining)
            return {
                "status": "rate_limited",
                "articles": [],
                "evidence_evaluation": evaluate_evidence_strength([]),
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": RATE_LIMIT_FRIENDLY_MESSAGE,
                "retry_after": remaining,
                "cached": False,
            }

        params = {
            "query": clean_query,
            "mode": "artlist",
            "maxrecords": str(bounded_limit),
            "format": "json",
            "sort": "DateDesc",
        }
        headers = {
            "User-Agent": "MultiContentFactory/1.0 (GDELT Key Signals Integration)",
            "Accept": "application/json, text/plain, */*",
        }

        retrieved_at = datetime.now(timezone.utc).isoformat()

        # 3. Lock requests to prevent parallel duplicate calls
        async with self._get_lock():
            # Re-check cache inside lock
            now = time.monotonic()
            if cache_key in self._cache:
                cached_time, cached_data = self._cache[cache_key]
                if now - cached_time < CACHE_TTL_SECONDS:
                    res = dict(cached_data)
                    res["cached"] = True
                    return res
                else:
                    del self._cache[cache_key]

            # Re-check cooldown inside lock
            if self.is_rate_limited():
                remaining = self.get_cooldown_remaining()
                return {
                    "status": "rate_limited",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": RATE_LIMIT_FRIENDLY_MESSAGE,
                    "retry_after": remaining,
                    "cached": False,
                }

            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(GDELT_DOC_API_URL, params=params, headers=headers)
            except httpx.TimeoutException:
                logger.warning("GDELT DOC 2.0 request timed out after %.1fs", self.timeout_seconds)
                return {
                    "status": "error",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": f"GDELT request timed out after {self.timeout_seconds} seconds.",
                    "retry_after": None,
                    "cached": False,
                }
            except httpx.RequestError as e:
                logger.warning("GDELT DOC 2.0 request network error: %s", e)
                return {
                    "status": "error",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": f"Failed to connect to GDELT DOC 2.0: {e}",
                    "retry_after": None,
                    "cached": False,
                }

            # 4. Handle HTTP 429 Rate Limiting
            if response.status_code == 429:
                retry_after_hdr = response.headers.get("retry-after") or response.headers.get("Retry-After")
                backoff = parse_retry_after(retry_after_hdr, default_seconds=DEFAULT_BACKOFF_SECONDS)
                self.set_cooldown(backoff)
                remaining = self.get_cooldown_remaining()
                logger.warning(
                    "GDELT returned HTTP 429. Setting cooldown for %ds (Retry-After header: %s)",
                    remaining,
                    retry_after_hdr,
                )
                return {
                    "status": "rate_limited",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": RATE_LIMIT_FRIENDLY_MESSAGE,
                    "retry_after": remaining,
                    "cached": False,
                }

            if response.status_code != 200:
                return {
                    "status": "error",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": f"GDELT returned HTTP {response.status_code}.",
                    "retry_after": None,
                    "cached": False,
                }

        # GDELT occasionally returns empty body or plain text error
        try:
            data = response.json()
        except Exception:
            text_snippet = response.text[:200].strip()
            if "rate limit" in text_snippet.lower() or "too many requests" in text_snippet.lower():
                self.set_cooldown(DEFAULT_BACKOFF_SECONDS)
                remaining = self.get_cooldown_remaining()
                return {
                    "status": "rate_limited",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": RATE_LIMIT_FRIENDLY_MESSAGE,
                    "retry_after": remaining,
                    "cached": False,
                }
            # If GDELT returned an empty response or "no articles match"
            if not text_snippet or "no articles" in text_snippet.lower():
                return {
                    "status": "empty",
                    "articles": [],
                    "evidence_evaluation": evaluate_evidence_strength([]),
                    "matching_query": clean_query,
                    "total_found": 0,
                    "error_message": None,
                    "retry_after": None,
                    "cached": False,
                }
            return {
                "status": "error",
                "articles": [],
                "evidence_evaluation": evaluate_evidence_strength([]),
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": f"GDELT returned non-JSON response: {text_snippet}",
                "retry_after": None,
                "cached": False,
            }

        raw_articles = data.get("articles") if isinstance(data, dict) else []
        if not raw_articles or not isinstance(raw_articles, list):
            return {
                "status": "empty",
                "articles": [],
                "evidence_evaluation": evaluate_evidence_strength([]),
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": None,
                "retry_after": None,
                "cached": False,
            }

        deduped_articles: List[GDELTArticle] = []
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()

        for item in raw_articles:
            if not isinstance(item, dict):
                continue
            raw_url = item.get("url") or item.get("url_mobile")
            if not raw_url or not isinstance(raw_url, str):
                continue

            # SSRF validation on source URL
            try:
                validated_url = validate_public_url(raw_url.strip(), allow_private=allow_private_urls)
            except UnsafeURLError as e:
                logger.debug("Skipping unsafe GDELT article URL %s: %s", raw_url, e)
                continue

            url_key = _normalize_url_key(validated_url)
            if url_key in seen_urls:
                continue

            title = _clean_title(item.get("title"))
            if not title:
                continue
            title_key = _normalize_title_key(title)
            if title_key in seen_titles:
                continue

            seen_urls.add(url_key)
            seen_titles.add(title_key)

            domain = (item.get("domain") or "").strip().lower()
            if not domain:
                try:
                    domain = urlparse(validated_url).netloc.lower()
                except Exception:
                    domain = "unknown"

            article = GDELTArticle(
                title=title,
                source_url=validated_url,
                domain=domain,
                published_at=_parse_gdelt_seendate(item.get("seendate")),
                retrieved_at=retrieved_at,
                matching_query=clean_query,
                language=item.get("language"),
                source_country=item.get("sourcecountry"),
            )
            deduped_articles.append(article)

        evaluation = evaluate_evidence_strength(deduped_articles)

        result = {
            "status": "success" if deduped_articles else "empty",
            "articles": [a.to_dict() for a in deduped_articles],
            "evidence_evaluation": evaluation,
            "matching_query": clean_query,
            "total_found": len(deduped_articles),
            "error_message": None,
            "retry_after": None,
            "cached": False,
        }
        if result["status"] == "success":
            self._cache[cache_key] = (time.monotonic(), dict(result))
        return result

