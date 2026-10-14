"""Tests for GDELT DOC 2.0 Key Signals provider.

Covers:
- Successful retrieval and structured formatting
- Multi-source, single-source, and isolated mention evidence strength
- URL and title deduplication
- SSRF protection against loopback/private URLs
- Timeout and network error resilience
- Non-JSON / empty / malformed upstream responses
- Bounded query parameters
- Zero live external network requests (fully mocked via httpx)
"""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.services.gdelt_provider import (
    GDELTProvider,
    _parse_gdelt_seendate,
    _clean_title,
    _normalize_title_key,
    _normalize_url_key,
    evaluate_evidence_strength,
    parse_retry_after,
    RATE_LIMIT_FRIENDLY_MESSAGE,
    MIN_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    DEFAULT_BACKOFF_SECONDS,
)


@pytest.fixture(autouse=True)
def _reset_gdelt_state():
    GDELTProvider.reset_cooldown()
    GDELTProvider.clear_cache()
    yield
    GDELTProvider.reset_cooldown()
    GDELTProvider.clear_cache()


def test_parse_gdelt_seendate():
    assert _parse_gdelt_seendate("20261012T083000Z") == "2026-10-12T08:30:00+00:00"
    assert _parse_gdelt_seendate("invalid") is None
    assert _parse_gdelt_seendate(None) is None


def test_clean_title():
    assert _clean_title("New  Launch &amp; Update &#39;26   ") == "New Launch & Update '26"
    assert _clean_title("") == ""
    assert _clean_title(None) == ""


def test_evidence_strength_evaluation():
    # Empty
    empty_eval = evaluate_evidence_strength([])
    assert empty_eval["strength"] == "no_signals"

    # Single mention - must NOT be labeled as a trend
    from app.services.gdelt_provider import GDELTArticle
    single = [
        GDELTArticle(
            title="Competitor Launches AI Tool",
            source_url="https://techcrunch.com/article1",
            domain="techcrunch.com",
            published_at="2026-10-12T08:00:00Z",
            retrieved_at="2026-10-12T09:00:00Z",
            matching_query="FocusFlow",
        )
    ]
    single_eval = evaluate_evidence_strength(single)
    assert single_eval["strength"] == "isolated_mention"
    assert "Isolated Mention" in single_eval["label"]
    assert "not verified as an industry trend" in single_eval["summary"].lower()

    # Single source coverage (2 articles, same domain)
    single_source = [
        single[0],
        GDELTArticle(
            title="Competitor Second Story",
            source_url="https://techcrunch.com/article2",
            domain="techcrunch.com",
            published_at="2026-10-12T08:30:00Z",
            retrieved_at="2026-10-12T09:00:00Z",
            matching_query="FocusFlow",
        ),
    ]
    ss_eval = evaluate_evidence_strength(single_source)
    assert ss_eval["strength"] == "single_source_coverage"
    assert "single publisher" in ss_eval["summary"].lower()

    # Multi-source coverage (2 articles, different domains)
    multi_source = [
        single[0],
        GDELTArticle(
            title="Competitor Market Analysis",
            source_url="https://forbes.com/article3",
            domain="forbes.com",
            published_at="2026-10-12T08:45:00Z",
            retrieved_at="2026-10-12T09:00:00Z",
            matching_query="FocusFlow",
        ),
    ]
    ms_eval = evaluate_evidence_strength(multi_source)
    assert ms_eval["strength"] == "multi_source_coverage"
    assert "2 distinct news domains" in ms_eval["summary"]


@pytest.mark.asyncio
async def test_gdelt_search_success():
    mock_payload = {
        "articles": [
            {
                "url": "https://techcrunch.com/2026/10/competitor-launch",
                "title": "Competitor Launches New Productivity Suite",
                "seendate": "20261012T080000Z",
                "domain": "techcrunch.com",
                "language": "English",
                "sourcecountry": "United States",
            },
            {
                "url": "https://theverge.com/2026/10/productivity-update",
                "title": "How Focus Tools Are Evolving in 2026",
                "seendate": "20261011T120000Z",
                "domain": "theverge.com",
                "language": "English",
                "sourcecountry": "United States",
            },
        ]
    }

    provider = GDELTProvider(timeout_seconds=5.0)

    mock_resp = httpx.Response(200, json=mock_payload, request=httpx.Request("GET", "https://api.gdeltproject.org"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        res = await provider.search_articles("FocusFlow productivity", max_records=5)

    assert res["status"] == "success"
    assert res["total_found"] == 2
    assert len(res["articles"]) == 2
    assert res["articles"][0]["title"] == "Competitor Launches New Productivity Suite"
    assert res["articles"][0]["domain"] == "techcrunch.com"
    assert res["articles"][0]["published_at"] == "2026-10-12T08:00:00+00:00"
    assert res["evidence_evaluation"]["strength"] == "multi_source_coverage"


@pytest.mark.asyncio
async def test_gdelt_deduplication_and_ssrf_filtering():
    mock_payload = {
        "articles": [
            {
                "url": "https://example.com/story?utm_source=twitter",
                "title": "Duplicate Story Title",
                "seendate": "20261012T080000Z",
                "domain": "example.com",
            },
            {
                "url": "https://example.com/story?utm_source=facebook#section",
                "title": "Duplicate Story Title (Repeated)",
                "seendate": "20261012T080500Z",
                "domain": "example.com",
            },
            {
                "url": "http://127.0.0.1:8000/internal-leak",
                "title": "Malicious SSRF Title",
                "seendate": "20261012T081000Z",
                "domain": "127.0.0.1",
            },
            {
                "url": "https://example.net/story2",
                "title": "Duplicate Story Title",  # duplicate title
                "seendate": "20261012T081500Z",
                "domain": "example.net",
            },
            {
                "url": "https://example.org/unique",
                "title": "Completely Unique Story",
                "seendate": "20261012T082000Z",
                "domain": "example.org",
            },
        ]
    }

    provider = GDELTProvider(timeout_seconds=5.0)

    mock_resp = httpx.Response(200, json=mock_payload, request=httpx.Request("GET", "https://api.gdeltproject.org"))
    # Mock validate_public_url to check SSRF behavior predictably without relying on live DNS
    def mock_validate(url, allow_private=False):
        if "127.0.0.1" in url or "localhost" in url:
            from app.core.url_safety import UnsafeURLError
            raise UnsafeURLError("SSRF blocked")
        return url

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp), \
         patch("app.services.gdelt_provider.validate_public_url", side_effect=mock_validate):
        res = await provider.search_articles("Query", allow_private_urls=False)

    # 1st article kept; 2nd is duplicate URL; 3rd is SSRF blocked; 4th is duplicate title; 5th is kept.
    assert res["status"] == "success"
    assert res["total_found"] == 2
    assert [a["domain"] for a in res["articles"]] == ["example.com", "example.org"]


@pytest.mark.asyncio
async def test_gdelt_timeout_handling():
    provider = GDELTProvider(timeout_seconds=2.0)
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("timeout")):
        res = await provider.search_articles("Query")

    assert res["status"] == "error"
    assert "timed out" in res["error_message"]
    assert res["articles"] == []


@pytest.mark.asyncio
async def test_gdelt_network_error_handling():
    provider = GDELTProvider(timeout_seconds=2.0)
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("connection refused")):
        res = await provider.search_articles("Query")

    assert res["status"] == "error"
    assert "Failed to connect" in res["error_message"]
    assert res["articles"] == []


@pytest.mark.asyncio
async def test_gdelt_malformed_and_empty_responses():
    provider = GDELTProvider(timeout_seconds=2.0)

    # Empty articles list
    mock_resp_empty = httpx.Response(200, json={"articles": []}, request=httpx.Request("GET", "https://api.gdeltproject.org"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp_empty):
        res = await provider.search_articles("Query")
    assert res["status"] == "empty"
    assert res["total_found"] == 0

    # Plain text "No articles found"
    mock_resp_text = httpx.Response(200, text="No articles matched your query", request=httpx.Request("GET", "https://api.gdeltproject.org"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp_text):
        res = await provider.search_articles("Query")
    assert res["status"] == "empty"

    # Non-200 status code
    mock_resp_500 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("GET", "https://api.gdeltproject.org"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp_500):
        res = await provider.search_articles("Query")
    assert res["status"] == "error"
    assert "503" in res["error_message"]


@pytest.mark.asyncio
async def test_gdelt_api_search_and_ingest(authenticated_client):
    from tests.test_competitor_analysis import make_product, add_competitor

    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id, name="Zoho Books")

    mock_search = {
        "status": "success",
        "articles": [
            {
                "title": "Zoho Books Adds Automated GST Invoicing",
                "source_url": "https://example.com/zoho-gst",
                "domain": "example.com",
                "published_at": "2026-10-12T08:00:00+00:00",
                "retrieved_at": "2026-10-12T09:00:00+00:00",
                "matching_query": '"Zoho Books" accounting',
                "language": "English",
                "source_country": "India",
            }
        ],
        "evidence_evaluation": {
            "strength": "isolated_mention",
            "label": "Isolated Mention (Unverified)",
            "summary": "Single media mention identified on example.com. Not verified as an industry trend.",
            "limitations": "Single media mention; verify against primary docs.",
        },
        "matching_query": '"Zoho Books" accounting',
        "total_found": 1,
        "error_message": None,
    }

    # 1. Search signals through API
    with patch("app.services.gdelt_provider.GDELTProvider.search_articles", new_callable=AsyncMock, return_value=mock_search):
        res = await authenticated_client.get(f"/api/products/{product_id}/competitors/{c['id']}/signals")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert len(data["articles"]) == 1
    assert data["articles"][0]["title"] == "Zoho Books Adds Automated GST Invoicing"
    assert data["evidence_evaluation"]["strength"] == "isolated_mention"

    # 2. Ingest the signal as competitor evidence
    ingest_payload = {
        "title": data["articles"][0]["title"],
        "source_url": data["articles"][0]["source_url"],
        "domain": data["articles"][0]["domain"],
        "published_at": data["articles"][0]["published_at"],
        "matching_query": data["matching_query"],
        "limitations": data["evidence_evaluation"]["limitations"],
    }
    with patch("app.services.competitor_service.validate_public_url", side_effect=lambda u, **kw: u):
        ingest_res = await authenticated_client.post(
            f"/api/products/{product_id}/competitors/{c['id']}/signals/ingest",
            json=ingest_payload,
        )
    assert ingest_res.status_code == 201, ingest_res.text
    evidence = ingest_res.json()
    assert evidence["evidence_type"] == "market_signal"
    assert "Zoho Books Adds Automated GST Invoicing" in evidence["title"]
    assert evidence["status"] == "completed"

    # 3. Verify competitor analysis now incorporates the signal evidence
    analyze_res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")
    assert analyze_res.status_code == 200, analyze_res.text
    analysis = analyze_res.json()
    assert analysis["analysis_status"] == "analyzed"
    assert len(analysis["evidence"]) == 1
    assert analysis["evidence"][0]["evidence_type"] == "market_signal"


def test_parse_retry_after_bounds_and_formats():
    # Integer within range
    assert parse_retry_after("30") == 30.0
    # Clamped to minimum (5.0s)
    assert parse_retry_after("2") == MIN_BACKOFF_SECONDS
    # Clamped to maximum (60.0s)
    assert parse_retry_after("3600") == MAX_BACKOFF_SECONDS
    # Missing / None / invalid defaults to DEFAULT_BACKOFF_SECONDS (15.0s)
    assert parse_retry_after(None) == DEFAULT_BACKOFF_SECONDS
    assert parse_retry_after("") == DEFAULT_BACKOFF_SECONDS
    assert parse_retry_after("invalid-header") == DEFAULT_BACKOFF_SECONDS


@pytest.mark.asyncio
async def test_gdelt_429_sets_cooldown_and_returns_friendly_message():
    provider = GDELTProvider()
    assert provider.is_rate_limited() is False

    mock_resp = httpx.Response(
        status_code=429,
        headers={"Retry-After": "25"},
        content=b"Too Many Requests",
        request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        res = await provider.search_articles("FocusFlow")

    assert res["status"] == "rate_limited"
    assert res["error_message"] == RATE_LIMIT_FRIENDLY_MESSAGE
    assert res["retry_after"] == 25
    assert res["articles"] == []
    assert res["total_found"] == 0
    assert provider.is_rate_limited() is True
    assert provider.get_cooldown_remaining() > 0


@pytest.mark.asyncio
async def test_gdelt_cooldown_blocks_immediate_requests_without_http():
    provider = GDELTProvider()
    GDELTProvider.set_cooldown(30.0)
    assert provider.is_rate_limited() is True

    # HTTP client should NOT be called during cooldown
    mock_get = AsyncMock()
    with patch("httpx.AsyncClient.get", mock_get):
        res = await provider.search_articles("FocusFlow")

    assert res["status"] == "rate_limited"
    assert res["error_message"] == RATE_LIMIT_FRIENDLY_MESSAGE
    assert res["retry_after"] > 0
    assert mock_get.call_count == 0


@pytest.mark.asyncio
async def test_gdelt_caching_avoids_repeated_requests():
    provider = GDELTProvider()
    mock_payload = {
        "articles": [
            {
                "url": "https://techcrunch.com/article-1",
                "title": "FocusFlow New Feature",
                "seendate": "20261012T080000Z",
                "domain": "techcrunch.com",
            }
        ]
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=mock_payload,
        request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
        # First call: hits HTTP
        res1 = await provider.search_articles("FocusFlow")
        assert res1["status"] == "success"
        assert len(res1["articles"]) == 1
        assert res1["cached"] is False
        assert mock_get.call_count == 1

        # Second call with same query: returns from cache without HTTP request
        res2 = await provider.search_articles("FocusFlow")
        assert res2["status"] == "success"
        assert len(res2["articles"]) == 1
        assert res2["cached"] is True
        assert mock_get.call_count == 1  # Still 1!


@pytest.mark.asyncio
async def test_gdelt_recovery_after_cooldown_expires():
    provider = GDELTProvider()

    # 1. Trigger rate limit
    mock_429 = httpx.Response(
        status_code=429,
        headers={"Retry-After": "10"},
        content=b"Too Many Requests",
        request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_429):
        res1 = await provider.search_articles("FocusFlow")
    assert res1["status"] == "rate_limited"
    assert provider.is_rate_limited() is True

    # 2. Simulate cooldown expiry
    GDELTProvider.reset_cooldown()
    assert provider.is_rate_limited() is False

    # 3. Next call succeeds
    mock_200 = httpx.Response(
        status_code=200,
        json={"articles": [{"url": "https://example.com/ok", "title": "Recovery Story"}]},
        request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_200):
        res2 = await provider.search_articles("FocusFlow")
    assert res2["status"] == "success"
    assert len(res2["articles"]) == 1
    assert provider.is_rate_limited() is False


@pytest.mark.asyncio
async def test_gdelt_rate_limited_api_route(authenticated_client):
    from tests.test_competitor_analysis import make_product, add_competitor
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id, name="Zoho Books")

    mock_rate_limit_res = {
        "status": "rate_limited",
        "articles": [],
        "evidence_evaluation": evaluate_evidence_strength([]),
        "matching_query": '"Zoho Books"',
        "total_found": 0,
        "error_message": RATE_LIMIT_FRIENDLY_MESSAGE,
        "retry_after": 20,
        "cached": False,
    }

    with patch("app.services.gdelt_provider.GDELTProvider.search_articles", new_callable=AsyncMock, return_value=mock_rate_limit_res):
        res = await authenticated_client.get(f"/api/products/{product_id}/competitors/{c['id']}/signals")

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "rate_limited"
    assert data["error_message"] == RATE_LIMIT_FRIENDLY_MESSAGE
    assert data["retry_after"] == 20
    assert data["articles"] == []

