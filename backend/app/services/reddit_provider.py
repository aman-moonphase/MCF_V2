"""Reddit UGC (User Generated Content) Explorer Provider.

Searches public discussions on Reddit using the official Reddit OAuth2 Data API
(client_credentials grant) for product and competitor mentions, customer sentiment,
and user feedback.

Features:
- Backend-only OAuth configuration via REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT.
- In-memory token caching with proactive expiration buffer.
- Honest unconfigured / missing credentials state handling.
- Privacy-first: strictly avoids collecting author usernames or personal identification.
- Bounded result limits (max 10 items) and strict request timeouts (10 seconds).
- Deduplication by canonical URL and normalized title.
- SSRF protection via validate_public_url.
- Explicit rate-limit (429), auth error (401), and upstream failure handling.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.url_safety import UnsafeURLError, validate_public_url

logger = logging.getLogger(__name__)

REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_SEARCH_URL = "https://oauth.reddit.com/search.json"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESULTS_LIMIT = 10


@dataclass
class RedditPost:
    title: str
    source_url: str
    subreddit: str
    published_at: Optional[str]
    retrieved_at: str
    matching_query: str
    excerpt: str
    score: int
    num_comments: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean_text(text: Optional[str]) -> str:
    """Clean whitespace and HTML entities from post text/title."""
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = (
        cleaned.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _normalize_url_key(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except Exception:
        return url.strip().lower()


class RedditUGCProvider:
    """Client for Reddit Data API using OAuth2 client credentials."""

    _cached_token: Optional[str] = None
    _token_expiry: float = 0.0

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds

    @classmethod
    def is_configured(cls) -> bool:
        """Whether Reddit API credentials are configured in the backend."""
        client_id = (settings.REDDIT_CLIENT_ID or "").strip()
        client_secret = (settings.REDDIT_CLIENT_SECRET or "").strip()
        return bool(client_id and client_secret)

    @classmethod
    def clear_token_cache(cls) -> None:
        """Clear cached OAuth token (useful for tests or token invalidation)."""
        cls._cached_token = None
        cls._token_expiry = 0.0

    async def _get_access_token(self) -> Optional[str]:
        """Obtain or return a cached OAuth bearer token."""
        now = time.time()
        if self._cached_token and now < self._token_expiry - 60.0:
            return self._cached_token

        client_id = (settings.REDDIT_CLIENT_ID or "").strip()
        client_secret = (settings.REDDIT_CLIENT_SECRET or "").strip()
        if not client_id or not client_secret:
            return None

        headers = {
            "User-Agent": settings.REDDIT_USER_AGENT,
        }
        data = {"grant_type": "client_credentials"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                res = await client.post(
                    REDDIT_AUTH_URL,
                    auth=(client_id, client_secret),
                    data=data,
                    headers=headers,
                )
        except Exception as e:
            logger.warning("Failed to obtain Reddit OAuth access token: %s", e)
            return None

        if res.status_code != 200:
            logger.warning("Reddit OAuth endpoint returned HTTP %d: %s", res.status_code, res.text[:200])
            return None

        try:
            payload = res.json()
            token = payload.get("access_token")
            expires_in = int(payload.get("expires_in", 3600))
            if token:
                RedditUGCProvider._cached_token = token
                RedditUGCProvider._token_expiry = now + expires_in
                return token
        except Exception as e:
            logger.warning("Error parsing Reddit OAuth token response: %s", e)

        return None

    async def search_posts(
        self,
        query: str,
        max_results: int = 10,
        allow_private_urls: bool = False,
    ) -> Dict[str, Any]:
        """Search public Reddit discussions for product or competitor mentions.

        Returns a dictionary with:
        - status: "success" | "empty" | "unconfigured" | "error"
        - posts: List[Dict[str, Any]]
        - matching_query: str
        - total_found: int
        - error_message: Optional[str]
        - limitations: Optional[str]
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "status": "empty",
                "posts": [],
                "matching_query": "",
                "total_found": 0,
                "error_message": "Query cannot be empty.",
                "limitations": None,
            }

        if not self.is_configured():
            return {
                "status": "unconfigured",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": (
                    "Reddit Data API is not configured. To enable UGC Explorer, configure "
                    "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in your backend environment."
                ),
                "limitations": "UGC Explorer requires valid Reddit API credentials.",
            }

        token = await self._get_access_token()
        if not token:
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": (
                    "Reddit authentication failed. Verify REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET."
                ),
                "limitations": None,
            }

        bounded_limit = max(1, min(max_results, MAX_RESULTS_LIMIT))
        params = {
            "q": clean_query,
            "sort": "relevance",
            "limit": str(bounded_limit),
            "type": "link",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": settings.REDDIT_USER_AGENT,
        }

        retrieved_at = datetime.now(timezone.utc).isoformat()

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                res = await client.get(REDDIT_OAUTH_SEARCH_URL, params=params, headers=headers)
        except httpx.TimeoutException:
            logger.warning("Reddit API request timed out after %.1fs", self.timeout_seconds)
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": f"Reddit request timed out after {self.timeout_seconds} seconds.",
                "limitations": None,
            }
        except httpx.RequestError as e:
            logger.warning("Reddit API network error: %s", e)
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": f"Failed to connect to Reddit API: {e}",
                "limitations": None,
            }

        if res.status_code == 429:
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": "Reddit API rate limit exceeded. Please wait a moment before trying again.",
                "limitations": None,
            }

        if res.status_code == 401:
            self.clear_token_cache()
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": "Reddit API unauthorized (401). Access token expired or invalid.",
                "limitations": None,
            }

        if res.status_code != 200:
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": f"Reddit API returned HTTP {res.status_code}.",
                "limitations": None,
            }

        try:
            data = res.json()
        except Exception:
            return {
                "status": "error",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": "Failed to parse Reddit API response.",
                "limitations": None,
            }

        children = (
            data.get("data", {}).get("children", [])
            if isinstance(data, dict)
            else []
        )
        if not children or not isinstance(children, list):
            return {
                "status": "empty",
                "posts": [],
                "matching_query": clean_query,
                "total_found": 0,
                "error_message": None,
                "limitations": "No public Reddit posts matched this query.",
            }

        deduped_posts: List[RedditPost] = []
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()

        for item in children:
            if not isinstance(item, dict):
                continue
            post_data = item.get("data")
            if not isinstance(post_data, dict):
                continue

            raw_permalink = post_data.get("permalink")
            if not raw_permalink:
                continue

            canonical_url = f"https://www.reddit.com{raw_permalink}"

            # SSRF validation on canonical public URL
            try:
                validated_url = validate_public_url(canonical_url, allow_private=allow_private_urls)
            except UnsafeURLError:
                continue

            url_key = _normalize_url_key(validated_url)
            if url_key in seen_urls:
                continue

            raw_title = post_data.get("title")
            title = _clean_text(raw_title)
            if not title:
                continue

            title_key = _normalize_title_key(title)
            if title_key in seen_titles:
                continue

            seen_urls.add(url_key)
            seen_titles.add(title_key)

            subreddit_raw = post_data.get("subreddit") or "reddit"
            subreddit = f"r/{subreddit_raw}"

            created_utc = post_data.get("created_utc")
            published_at = None
            if created_utc:
                try:
                    published_at = datetime.fromtimestamp(float(created_utc), timezone.utc).isoformat()
                except Exception:
                    pass

            selftext = _clean_text(post_data.get("selftext"))
            # Bounded excerpt length to prevent bloating
            excerpt = selftext[:1200] if selftext else "(Link / Discussion post)"

            post = RedditPost(
                title=title[:255],
                source_url=validated_url,
                subreddit=subreddit,
                published_at=published_at,
                retrieved_at=retrieved_at,
                matching_query=clean_query,
                excerpt=excerpt,
                score=int(post_data.get("score") or 0),
                num_comments=int(post_data.get("num_comments") or 0),
            )
            deduped_posts.append(post)

        return {
            "status": "success" if deduped_posts else "empty",
            "posts": [p.to_dict() for p in deduped_posts],
            "matching_query": clean_query,
            "total_found": len(deduped_posts),
            "error_message": None,
            "limitations": (
                "Reddit discussions reflect subjective user feedback and anecdotal experiences. "
                "Observations are treated as unverified customer hypotheses until supported by evidence."
            ),
        }
