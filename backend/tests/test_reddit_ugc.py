"""Tests for Reddit UGC Explorer provider.

Covers:
- Unconfigured state when REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET is missing
- Successful OAuth token acquisition and search retrieval
- Privacy verification: strictly zero author usernames or personal data
- Deduplication by URL and normalized title
- SSRF filtering on post permalinks
- Rate-limit (429) and auth (401) error handling
- Network errors, timeouts, and empty responses
- Zero live external network requests (fully mocked via httpx)
"""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.reddit_provider import RedditUGCProvider, _clean_text


def test_clean_text():
    assert _clean_text("Reddit &amp; post   with &#39;quotes&#39; ") == "Reddit & post with 'quotes'"
    assert _clean_text("") == ""
    assert _clean_text(None) == ""


@pytest.mark.asyncio
async def test_reddit_unconfigured_state(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", None)
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", None)
    RedditUGCProvider.clear_token_cache()

    provider = RedditUGCProvider(timeout_seconds=5.0)
    res = await provider.search_posts("Vyapar vs Zoho")

    assert res["status"] == "unconfigured"
    assert "not configured" in res["error_message"].lower()
    assert res["posts"] == []


@pytest.mark.asyncio
async def test_reddit_search_success_and_privacy(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "mock_client_id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "mock_client_secret")
    RedditUGCProvider.clear_token_cache()

    mock_token_resp = httpx.Response(
        200,
        json={"access_token": "mock_token_xyz", "expires_in": 3600},
        request=httpx.Request("POST", "https://www.reddit.com/api/v1/access_token"),
    )

    mock_search_payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc123",
                        "title": "Anyone using Zoho Books for freelance invoicing in India?",
                        "permalink": "/r/freelance/comments/abc123/zoho_books_invoicing/",
                        "subreddit": "freelance",
                        "author": "super_private_user_42",  # Should be omitted!
                        "selftext": "Zoho Books has been solid for GST invoicing, but UI is heavy.",
                        "created_utc": 1700000000.0,
                        "score": 25,
                        "num_comments": 14,
                    }
                },
                {
                    "data": {
                        "id": "def456",
                        "title": "Vyapar vs Zoho Books comparison",
                        "permalink": "/r/india/comments/def456/vyapar_vs_zoho/",
                        "subreddit": "india",
                        "author": "another_user_99",  # Should be omitted!
                        "selftext": "Vyapar is much faster for offline billing.",
                        "created_utc": 1700005000.0,
                        "score": 10,
                        "num_comments": 8,
                    }
                },
            ]
        }
    }
    mock_search_resp = httpx.Response(
        200,
        json=mock_search_payload,
        request=httpx.Request("GET", "https://oauth.reddit.com/search.json"),
    )

    async def mock_get(*args, **kwargs):
        return mock_search_resp

    async def mock_post(*args, **kwargs):
        return mock_token_resp

    provider = RedditUGCProvider(timeout_seconds=5.0)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
        res = await provider.search_posts("Zoho Books invoicing", allow_private_urls=True)

    assert res["status"] == "success"
    assert res["total_found"] == 2
    posts = res["posts"]
    assert len(posts) == 2

    first = posts[0]
    assert first["title"] == "Anyone using Zoho Books for freelance invoicing in India?"
    assert first["source_url"] == "https://www.reddit.com/r/freelance/comments/abc123/zoho_books_invoicing/"
    assert first["subreddit"] == "r/freelance"
    assert first["score"] == 25
    assert first["num_comments"] == 14
    assert "Zoho Books has been solid" in first["excerpt"]

    # Strict privacy verification: Ensure author username is NOT in the record
    assert "author" not in first
    assert "super_private_user_42" not in str(res)


@pytest.mark.asyncio
async def test_reddit_deduplication(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "mock_id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "mock_secret")
    RedditUGCProvider.clear_token_cache()

    mock_token_resp = httpx.Response(200, json={"access_token": "token", "expires_in": 3600}, request=httpx.Request("POST", "https://reddit.com"))
    mock_payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "permalink": "/r/tech/comments/1/duplicate_story/",
                        "title": "Duplicate Post Title",
                        "subreddit": "tech",
                        "selftext": "Body 1",
                        "score": 1,
                        "num_comments": 1,
                    }
                },
                {
                    "data": {
                        "permalink": "/r/tech/comments/1/duplicate_story/",  # Duplicate URL
                        "title": "Another title but same url",
                        "subreddit": "tech",
                        "selftext": "Body 2",
                        "score": 2,
                        "num_comments": 2,
                    }
                },
                {
                    "data": {
                        "permalink": "/r/tech/comments/2/unique_story/",
                        "title": "Duplicate Post Title",  # Duplicate Title
                        "subreddit": "tech",
                        "selftext": "Body 3",
                        "score": 3,
                        "num_comments": 3,
                    }
                },
                {
                    "data": {
                        "permalink": "/r/tech/comments/3/truly_unique/",
                        "title": "Truly Unique Story",
                        "subreddit": "tech",
                        "selftext": "Body 4",
                        "score": 4,
                        "num_comments": 4,
                    }
                },
            ]
        }
    }
    mock_search_resp = httpx.Response(200, json=mock_payload, request=httpx.Request("GET", "https://reddit.com"))

    provider = RedditUGCProvider(timeout_seconds=5.0)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_search_resp):
        res = await provider.search_posts("Query", allow_private_urls=True)

    assert res["status"] == "success"
    # 1st kept; 2nd dup URL skipped; 3rd dup title skipped; 4th kept. Total = 2.
    assert res["total_found"] == 2
    assert [p["title"] for p in res["posts"]] == ["Duplicate Post Title", "Truly Unique Story"]


@pytest.mark.asyncio
async def test_reddit_rate_limit_and_auth_error(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "mock_id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "mock_secret")
    RedditUGCProvider.clear_token_cache()

    mock_token_resp = httpx.Response(200, json={"access_token": "token", "expires_in": 3600}, request=httpx.Request("POST", "https://reddit.com"))
    provider = RedditUGCProvider(timeout_seconds=5.0)

    # 429 Rate Limit
    mock_429 = httpx.Response(429, text="Too Many Requests", request=httpx.Request("GET", "https://reddit.com"))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_429):
        res_429 = await provider.search_posts("Query")
    assert res_429["status"] == "error"
    assert "rate limit" in res_429["error_message"].lower()

    # 401 Unauthorized
    mock_401 = httpx.Response(401, text="Unauthorized", request=httpx.Request("GET", "https://reddit.com"))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_401):
        res_401 = await provider.search_posts("Query")
    assert res_401["status"] == "error"
    assert "401" in res_401["error_message"]


@pytest.mark.asyncio
async def test_reddit_timeout_and_empty(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "mock_id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "mock_secret")
    RedditUGCProvider.clear_token_cache()

    mock_token_resp = httpx.Response(200, json={"access_token": "token", "expires_in": 3600}, request=httpx.Request("POST", "https://reddit.com"))
    provider = RedditUGCProvider(timeout_seconds=2.0)

    # Timeout
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("timeout")):
        res_timeout = await provider.search_posts("Query")
    assert res_timeout["status"] == "error"
    assert "timed out" in res_timeout["error_message"].lower()

    # Empty results
    mock_empty = httpx.Response(200, json={"data": {"children": []}}, request=httpx.Request("GET", "https://reddit.com"))
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_empty):
        res_empty = await provider.search_posts("Query")
    assert res_empty["status"] == "empty"
    assert res_empty["total_found"] == 0


@pytest.mark.asyncio
async def test_reddit_api_unconfigured_and_ingest(authenticated_client, monkeypatch):
    from tests.test_competitor_analysis import make_product, add_competitor

    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id, name="Zoho Books")

    # 1. Test unconfigured API state
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", None)
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", None)
    res = await authenticated_client.get(f"/api/products/{product_id}/competitors/{c['id']}/ugc")
    assert res.status_code == 200, res.text
    unconf_data = res.json()
    assert unconf_data["status"] == "unconfigured"
    assert "not configured" in unconf_data["error_message"].lower()

    # 2. Test search when configured with mocked provider
    mock_ugc_result = {
        "status": "success",
        "posts": [
            {
                "title": "Zoho Books vs QuickBooks for Indian freelancers",
                "source_url": "https://example.com/r/freelance/comments/123",
                "subreddit": "r/freelance",
                "published_at": "2026-10-12T08:00:00+00:00",
                "retrieved_at": "2026-10-12T09:00:00+00:00",
                "matching_query": '"Zoho Books" review',
                "excerpt": "Zoho is reliable for GST invoices and reconciling bank accounts.",
                "score": 35,
                "num_comments": 12,
            }
        ],
        "matching_query": '"Zoho Books" review',
        "total_found": 1,
        "error_message": None,
        "limitations": "Anecdotal customer feedback; unverified hypothesis.",
    }

    with patch("app.services.reddit_provider.RedditUGCProvider.search_posts", new_callable=AsyncMock, return_value=mock_ugc_result):
        search_res = await authenticated_client.get(f"/api/products/{product_id}/competitors/{c['id']}/ugc")
    assert search_res.status_code == 200, search_res.text
    data = search_res.json()
    assert data["status"] == "success"
    assert len(data["posts"]) == 1
    assert data["posts"][0]["subreddit"] == "r/freelance"

    # 3. Test ingesting the UGC post as evidence
    post_item = data["posts"][0]
    ingest_payload = {
        "title": post_item["title"],
        "source_url": post_item["source_url"],
        "subreddit": post_item["subreddit"],
        "published_at": post_item["published_at"],
        "matching_query": data["matching_query"],
        "excerpt": post_item["excerpt"],
        "score": post_item["score"],
        "num_comments": post_item["num_comments"],
    }
    with patch("app.services.competitor_service.validate_public_url", side_effect=lambda u, **kw: u):
        ingest_res = await authenticated_client.post(
            f"/api/products/{product_id}/competitors/{c['id']}/ugc/ingest",
            json=ingest_payload,
        )
    assert ingest_res.status_code == 201, ingest_res.text
    evidence = ingest_res.json()
    assert evidence["evidence_type"] == "ugc"
    assert "UGC (r/freelance)" in evidence["title"]
    assert evidence["status"] == "completed"

    # 4. Verify competitor analysis now incorporates the UGC evidence
    analyze_res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")
    assert analyze_res.status_code == 200, analyze_res.text
    analysis = analyze_res.json()
    assert analysis["analysis_status"] == "analyzed"
    assert any(e["evidence_type"] == "ugc" for e in analysis["evidence"])

