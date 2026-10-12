"""Tests for Image Generation and Creative Preview vertical slice.

Verifies:
- Successful generation in Demo Mode (deterministic SVG data URL, zero external API calls).
- Custom prompt, style, and aspect ratio support (16:9 and 1:1).
- Version association (tracks post versions, detects version mismatch when post is edited).
- Preservation of human-review boundary and post approval state.
- Updating prompt and alt-text metadata.
- Deleting creative image asset.
- Error handling when post does not exist yet.
- Tenant isolation and ownership security.
"""

import base64
import urllib.parse
from unittest.mock import AsyncMock, patch
from uuid import UUID
import httpx
import pytest
from sqlalchemy import select

from app.ai.providers.image_provider import (
    ImageGenerationRequest,
    PollinationsImageProvider,
    PollinationsLegacyImageProvider,
    get_image_provider,
)
from app.core.config import settings
from app.models.content_image import ContentImage
from app.models.generated_content import GeneratedContent
from tests.test_generate_content import gen_url, generate, ready_project
from tests.test_promotion_strategy import other_client  # noqa: F401


def image_url(project_id: UUID) -> str:
    return f"/api/projects/{project_id}/generated-content/image"


async def evaluate_post(client, project_id: UUID, version: int = 1):
    res = await client.post(f"/api/projects/{project_id}/evaluation", json={"version": version})
    assert res.status_code == 200, res.text
    return res.json()


async def approve_post(client, project_id: UUID, version: int = 1):
    res = await client.post(f"/api/projects/{project_id}/generated-content/approve", json={"version": version})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_generate_image_success_for_post(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    post_res = await generate(authenticated_client, project_id)
    assert post_res["draft"]["version"] == 1
    assert post_res["draft"].get("image") is None

    # Generate image
    res = await authenticated_client.post(image_url(project_id), json={})
    assert res.status_code == 200, res.text
    data = res.json()

    draft = data["draft"]
    assert draft is not None
    image = draft["image"]
    assert image is not None
    assert image["image_url"].startswith("data:image/svg+xml")
    assert image["content_version"] == 1
    assert image["version_matches_post"] is True
    assert image["aspect_ratio"] == "16:9"
    assert image["style"] == "professional"
    assert image["provider"] == "demo"
    assert image["is_demo"] is True
    assert image["status"] == "generated"
    assert "LedgerLeaf" in image["prompt"] or "LedgerLeaf" in image["alt_text"]


@pytest.mark.asyncio
async def test_custom_prompt_style_and_aspect_ratio(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    res = await authenticated_client.post(
        image_url(project_id),
        json={
            "prompt": "Vibrant social graphic with financial charts and modern gradient",
            "aspect_ratio": "1:1",
            "style": "bold",
            "alt_text": "Social banner for LedgerLeaf expense tracking",
        },
    )
    assert res.status_code == 200, res.text
    image = res.json()["draft"]["image"]
    assert image["prompt"] == "Vibrant social graphic with financial charts and modern gradient"
    assert image["aspect_ratio"] == "1:1"
    assert image["style"] == "bold"
    assert image["alt_text"] == "Social banner for LedgerLeaf expense tracking"


@pytest.mark.asyncio
async def test_image_mutation_rejected_on_approved_post(authenticated_client, db_session):
    """Mutating creative image assets on an approved post is blocked with 409 Conflict.
    Post approval status and content are strictly preserved."""
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await evaluate_post(authenticated_client, project_id, version=1)
    approved = await approve_post(authenticated_client, project_id, version=1)
    assert approved["draft"]["status"] == "approved"
    assert approved["draft"]["approved_version"] == 1

    # Attempting to generate an image on the approved post is refused with 409
    img_res = await authenticated_client.post(image_url(project_id), json={})
    assert img_res.status_code == 409, img_res.text
    assert "approved" in img_res.json()["detail"].lower()
    assert "draft" in img_res.json()["detail"].lower()

    # Attempting to update image metadata on approved post is refused with 409
    patch_res = await authenticated_client.patch(image_url(project_id), json={"prompt": "Try modify"})
    assert patch_res.status_code == 409, patch_res.text
    assert "approved" in patch_res.json()["detail"].lower()

    # Attempting to delete image on approved post is refused with 409
    del_res = await authenticated_client.delete(image_url(project_id))
    assert del_res.status_code == 409, del_res.text
    assert "approved" in del_res.json()["detail"].lower()

    # Verify post in DB remains approved, approved_version is still 1
    db_draft = (await db_session.execute(
        select(GeneratedContent).where(GeneratedContent.project_id == project_id)
    )).scalar_one()
    assert db_draft.status == "approved"
    assert db_draft.approved_version == 1


@pytest.mark.asyncio
async def test_image_version_association_with_post_edits(authenticated_client):
    """Image is associated with post version. When post is edited, version mismatch is detected."""
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    # Generate image for version 1
    await authenticated_client.post(image_url(project_id), json={})

    # Edit post by hand to version 2
    edit_res = await authenticated_client.patch(
        gen_url(project_id),
        json={"cta": "Book a demo today to see LedgerLeaf in action.", "version": 1},
    )
    assert edit_res.status_code == 200, edit_res.text
    draft_v2 = edit_res.json()["draft"]
    assert draft_v2["version"] == 2

    # The existing image belongs to version 1: version_matches_post is False
    assert draft_v2["image"] is not None
    assert draft_v2["image"]["content_version"] == 1
    assert draft_v2["image"]["version_matches_post"] is False

    # Regenerate image for the edited version 2
    re_img_res = await authenticated_client.post(image_url(project_id), json={})
    assert re_img_res.status_code == 200, re_img_res.text
    re_image = re_img_res.json()["draft"]["image"]
    assert re_image["content_version"] == 2
    assert re_image["version_matches_post"] is True


@pytest.mark.asyncio
async def test_update_image_metadata(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.post(image_url(project_id), json={})

    # Update prompt and alt text
    patch_res = await authenticated_client.patch(
        image_url(project_id),
        json={
            "prompt": "Updated headline graphic with verified citations",
            "alt_text": "Updated accessibility description",
            "style": "editorial",
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    image = patch_res.json()["draft"]["image"]
    assert image["prompt"] == "Updated headline graphic with verified citations"
    assert image["alt_text"] == "Updated accessibility description"
    assert image["style"] == "editorial"
    assert image["status"] == "saved"


@pytest.mark.asyncio
async def test_delete_image(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.post(image_url(project_id), json={})

    # Delete image
    del_res = await authenticated_client.delete(image_url(project_id))
    assert del_res.status_code == 200, del_res.text
    assert del_res.json()["draft"]["image"] is None


@pytest.mark.asyncio
async def test_cannot_generate_image_without_post(authenticated_client):
    # Create project without generating a post
    from tests.test_promotion_strategy import make_product
    project_id, _ = await make_product(authenticated_client)

    res = await authenticated_client.post(image_url(project_id), json={})
    assert res.status_code == 404, res.text
    assert "no generated post" in res.json()["detail"].lower() or "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_image_ownership_isolation(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.post(image_url(project_id), json={})

    # Another user tries to generate or update image
    res1 = await other_client.post(image_url(project_id), json={})
    assert res1.status_code == 404

    res2 = await other_client.patch(image_url(project_id), json={"prompt": "Hacked"})
    assert res2.status_code == 404

    res3 = await other_client.delete(image_url(project_id))
    assert res3.status_code == 404


@pytest.mark.asyncio
async def test_square_1_to_1_image_dimensions_and_metadata_update(authenticated_client):
    """Selecting 1:1 produces genuine square SVG dimensions (width=1200, height=1200)
    and updating metadata immediately re-renders the image_url."""
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    # 1. Generate default image (16:9)
    res1 = await authenticated_client.post(image_url(project_id), json={})
    assert res1.status_code == 200
    img1 = res1.json()["draft"]["image"]
    assert img1["aspect_ratio"] == "16:9"
    svg1 = urllib.parse.unquote(img1["image_url"].split(",", 1)[1])
    assert 'width="1200"' in svg1
    assert 'height="675"' in svg1
    assert 'viewBox="0 0 1200 675"' in svg1

    # 2. Update to 1:1 aspect ratio
    patch_res = await authenticated_client.patch(
        image_url(project_id),
        json={"aspect_ratio": "1:1", "style": "bold"},
    )
    assert patch_res.status_code == 200
    img2 = patch_res.json()["draft"]["image"]
    assert img2["aspect_ratio"] == "1:1"
    assert img2["style"] == "bold"
    svg2 = urllib.parse.unquote(img2["image_url"].split(",", 1)[1])
    assert 'width="1200"' in svg2
    assert 'height="1200"' in svg2
    assert 'viewBox="0 0 1200 1200"' in svg2


@pytest.mark.asyncio
async def test_product_name_consistently_used_not_project_title(authenticated_client):
    """Image generation uses the product name (e.g. StudyNest) rather than the project title."""
    project_id, _, _ = await ready_project(authenticated_client)
    # The ready project product is LedgerLeaf
    await generate(authenticated_client, project_id)
    res = await authenticated_client.post(image_url(project_id), json={})
    assert res.status_code == 200
    img = res.json()["draft"]["image"]
    assert "LedgerLeaf" in img["prompt"]
    assert "LedgerLeaf" in img["alt_text"]
    svg = urllib.parse.unquote(img["image_url"].split(",", 1)[1])
    assert "LedgerLeaf" in svg


@pytest.mark.asyncio
async def test_pollinations_provider_direct_mocked_success():
    """PollinationsImageProvider sends Authorization Bearer, URL-encoded prompt, correct dimensions,
    and returns base64 image data URI without making real external calls."""
    fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIFfakeimagedata"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_image_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://gen.pollinations.ai/image/test"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        provider = PollinationsImageProvider(
            api_key="secret-pollinations-test-key",
            model="flux",
            timeout=30.0,
        )

        req = ImageGenerationRequest(
            prompt="High quality visual of financial dashboard",
            aspect_ratio="1:1",
            style="bold",
            alt_text="A financial chart",
            product_name="LedgerLeaf",
        )

        result = await provider.generate_image(req)

        assert mock_get.called
        call_args, call_kwargs = mock_get.call_args
        called_url = call_args[0]
        called_params = call_kwargs["params"]
        called_headers = call_kwargs["headers"]

        # Endpoint structure
        assert called_url.startswith("https://gen.pollinations.ai/image/")
        assert "High%20quality%20visual" in called_url
        # Authorization strictly through Bearer header
        assert called_headers["Authorization"] == "Bearer secret-pollinations-test-key"
        # Secret is NOT in the URL or query params
        assert "secret-pollinations-test-key" not in called_url
        assert "secret-pollinations-test-key" not in str(called_params)
        # Dimensions & parameters
        assert called_params["width"] == "1200"
        assert called_params["height"] == "1200"  # 1:1
        assert called_params["model"] == "flux"
        assert called_params["nologo"] == "true"

        # Result verification
        assert result.provider == "pollinations"
        assert result.is_demo is False
        assert result.aspect_ratio == "1:1"
        assert result.style == "bold"
        assert result.image_url.startswith("data:image/jpeg;base64,")
        b64_part = result.image_url.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert decoded == fake_image_bytes


@pytest.mark.asyncio
async def test_pollinations_provider_missing_key_raises_error(monkeypatch):
    """PollinationsImageProvider requires explicit API key."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", None)
    provider = PollinationsImageProvider(api_key=None)
    req = ImageGenerationRequest(prompt="Test prompt")
    with pytest.raises(ValueError, match="POLLINATIONS_API_KEY"):
        await provider.generate_image(req)


@pytest.mark.asyncio
async def test_pollinations_provider_timeout_raises_timeout_error():
    """PollinationsImageProvider converts httpx.TimeoutException to TimeoutError."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Read timed out")
        provider = PollinationsImageProvider(api_key="mock-key", timeout=10.0)
        req = ImageGenerationRequest(prompt="Test prompt")
        with pytest.raises(TimeoutError, match="timed out"):
            await provider.generate_image(req)


@pytest.mark.asyncio
async def test_pollinations_provider_upstream_error_raises_runtime_error():
    """Upstream errors from Pollinations raise RuntimeError without leaking sensitive keys."""
    mock_response = httpx.Response(
        status_code=500,
        text="Internal Server Error from upstream provider",
        request=httpx.Request("GET", "https://gen.pollinations.ai/image/test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        provider = PollinationsImageProvider(api_key="mock-secret-key-12345")
        req = ImageGenerationRequest(prompt="Test prompt")
        with pytest.raises(RuntimeError) as exc_info:
            await provider.generate_image(req)
        assert "500" in str(exc_info.value)
        assert "mock-secret-key-12345" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_api_pollinations_generation_success_and_persistence(authenticated_client, monkeypatch):
    """Full API slice for Pollinations image generation with mocked HTTP response.
    Verifies base64 persistence across reloads, provider metadata, and human review preservation."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", "mock-secret-key")

    fake_bytes = b"\xff\xd8\xff\xe0mockjpegdata"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://gen.pollinations.ai/image/test"),
    )

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        # Request generation with explicit pollinations provider
        res = await authenticated_client.post(
            image_url(project_id),
            json={
                "provider": "pollinations",
                "aspect_ratio": "16:9",
                "style": "editorial",
                "prompt": "Custom editorial graphic for LedgerLeaf launch",
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        draft = data["draft"]
        assert draft is not None
        image = draft["image"]
        assert image is not None
        assert image["provider"] == "pollinations"
        assert image["is_demo"] is False
        assert image["style"] == "editorial"
        assert image["aspect_ratio"] == "16:9"
        assert image["image_url"].startswith("data:image/jpeg;base64,")
        assert draft["status"] == "draft"  # Review boundary preserved!

        # Verify Authorization header was sent with Bearer
        assert mock_get.called
        headers_sent = mock_get.call_args[1]["headers"]
        assert headers_sent["Authorization"] == "Bearer mock-secret-key"

    # Persistence test: reloading the generation state returns the saved Pollinations asset
    reload_res = await authenticated_client.get(f"/api/projects/{project_id}/generated-content")
    assert reload_res.status_code == 200
    reloaded_img = reload_res.json()["draft"]["image"]
    assert reloaded_img["provider"] == "pollinations"
    assert reloaded_img["is_demo"] is False
    assert reloaded_img["image_url"] == image["image_url"]


@pytest.mark.asyncio
async def test_api_pollinations_missing_api_key_returns_400(authenticated_client, monkeypatch):
    """If POLLINATIONS_API_KEY is not configured, requesting pollinations provider returns 400 Bad Request."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", None)

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    res = await authenticated_client.post(
        image_url(project_id),
        json={"provider": "pollinations"},
    )
    assert res.status_code == 400, res.text
    assert "POLLINATIONS_API_KEY" in res.json()["detail"]


@pytest.mark.asyncio
async def test_api_pollinations_upstream_timeout_returns_504(authenticated_client, monkeypatch):
    """If Pollinations generation times out, returns 504 Gateway Timeout."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", "mock-key")

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connection timed out after 60s")

        res = await authenticated_client.post(
            image_url(project_id),
            json={"provider": "pollinations"},
        )
        assert res.status_code == 504, res.text
        assert "timed out" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_pollinations_upstream_failure_returns_502(authenticated_client, monkeypatch):
    """If Pollinations generation fails upstream (e.g. 502/500), returns 502 Bad Gateway without leaking keys."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", "mock-super-secret-key")

    mock_error_resp = httpx.Response(
        status_code=503,
        text="Service Temporarily Unavailable",
        request=httpx.Request("GET", "https://gen.pollinations.ai/image/test"),
    )

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_error_resp

        res = await authenticated_client.post(
            image_url(project_id),
            json={"provider": "pollinations"},
        )
        assert res.status_code == 502, res.text
        assert "mock-super-secret-key" not in res.text


@pytest.mark.asyncio
async def test_pollinations_legacy_provider_direct_mocked_success():
    """PollinationsLegacyImageProvider uses reference image.pollinations.ai endpoint,
    omits Authorization header, sends random seed, and produces valid base64 image data URI."""
    fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIFfakelegacydata"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_image_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        provider = PollinationsLegacyImageProvider(model="flux", timeout=30.0)
        req = ImageGenerationRequest(
            prompt="Vintage desk with notebook and coffee",
            aspect_ratio="1:1",
            style="minimalist",
            product_name="StudyNest",
        )

        result = await provider.generate_image(req)

        assert mock_get.called
        call_args, call_kwargs = mock_get.call_args
        called_url = call_args[0]
        called_params = call_kwargs["params"]
        called_headers = call_kwargs["headers"]

        # Uses legacy reference domain
        assert called_url.startswith("https://image.pollinations.ai/prompt/")
        # No Authorization header in legacy mode
        assert "Authorization" not in called_headers
        # Parameters
        assert called_params["width"] == "1024"  # 1:1 in legacy mode
        assert called_params["height"] == "1024"
        assert "seed" in called_params
        assert called_params["model"] == "flux"
        assert called_params["nologo"] == "true"

        # Result verification
        assert result.provider == "pollinations_legacy"
        assert result.is_demo is False
        assert result.aspect_ratio == "1:1"
        assert result.image_url.startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_pollinations_legacy_provider_rejects_html_error_page():
    """Legacy provider rejects HTML challenge or error pages returned under status 200."""
    html_page = b"<!DOCTYPE html><html><head><title>Cloudflare DDoS</title></head><body>Challenge</body></html>"
    mock_response = httpx.Response(
        status_code=200,
        content=html_page,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        provider = PollinationsLegacyImageProvider()
        req = ImageGenerationRequest(prompt="Test prompt")

        with pytest.raises(RuntimeError, match="invalid or non-image content"):
            await provider.generate_image(req)


@pytest.mark.asyncio
async def test_pollinations_legacy_provider_rejects_oversized_payload():
    """Legacy provider enforces a response-size ceiling (10 MB)."""
    oversized = b"x" * (11 * 1024 * 1024)
    mock_response = httpx.Response(
        status_code=200,
        content=oversized,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        provider = PollinationsLegacyImageProvider()
        req = ImageGenerationRequest(prompt="Test prompt")

        with pytest.raises(RuntimeError, match="oversized payload"):
            await provider.generate_image(req)


@pytest.mark.asyncio
async def test_pollinations_legacy_provider_timeout_raises_timeout_error():
    """Legacy provider converts httpx.TimeoutException to TimeoutError with helpful message."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Read timed out")
        provider = PollinationsLegacyImageProvider(timeout=15.0)
        req = ImageGenerationRequest(prompt="Test prompt")

        with pytest.raises(TimeoutError, match="timed out"):
            await provider.generate_image(req)


@pytest.mark.asyncio
async def test_api_pollinations_legacy_generation_and_persistence(authenticated_client):
    """Full API slice for legacy Pollinations generation:
    - Works with zero API key.
    - Persists provider='pollinations_legacy' and is_demo=False across reloads.
    - Preserves post draft status and review boundary."""
    fake_bytes = b"\xff\xd8\xff\xe0mocklegacyjpeg"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await authenticated_client.post(
            image_url(project_id),
            json={
                "provider": "pollinations_legacy",
                "aspect_ratio": "1:1",
                "style": "bold",
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        draft = data["draft"]
        assert draft is not None
        image = draft["image"]
        assert image is not None
        assert image["provider"] == "pollinations_legacy"
        assert image["is_demo"] is False
        assert image["aspect_ratio"] == "1:1"
        assert image["image_url"].startswith("data:image/jpeg;base64,")
        assert draft["status"] == "draft"  # Review boundary intact

        # Verify no Authorization header was sent to legacy service
        assert mock_get.called
        headers_sent = mock_get.call_args[1]["headers"]
        assert "Authorization" not in headers_sent

    # Reload and test persistence
    reload_res = await authenticated_client.get(f"/api/projects/{project_id}/generated-content")
    assert reload_res.status_code == 200
    reloaded_img = reload_res.json()["draft"]["image"]
    assert reloaded_img["provider"] == "pollinations_legacy"
    assert reloaded_img["is_demo"] is False
    assert reloaded_img["image_url"] == image["image_url"]


@pytest.mark.asyncio
async def test_provider_separation_no_silent_fallback(authenticated_client, monkeypatch):
    """Authenticated and legacy providers are strictly separated.
    If authenticated pollinations is selected without a key, it returns 400 Bad Request
    and does NOT silently fall back to legacy mode."""
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", None)

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    # 1. Requesting authenticated provider without key fails explicitly with 400
    auth_res = await authenticated_client.post(
        image_url(project_id),
        json={"provider": "pollinations"},
    )
    assert auth_res.status_code == 400
    assert "POLLINATIONS_API_KEY" in auth_res.json()["detail"]

    # 2. Requesting legacy provider succeeds without key
    fake_bytes = b"\xff\xd8\xff\xe0mocklegacyjpeg"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        legacy_res = await authenticated_client.post(
            image_url(project_id),
            json={"provider": "pollinations_legacy"},
        )
        assert legacy_res.status_code == 200
        assert legacy_res.json()["draft"]["image"]["provider"] == "pollinations_legacy"


@pytest.mark.asyncio
async def test_craft_prompt_clean_visual_directives_and_no_text():
    """craft_prompt instructs the image generator to render clean visual backgrounds without text,
    lettering, words, logos, watermarks, or pseudo-typography, and never passes hook in quotes."""
    provider = PollinationsImageProvider(api_key="mock-key")

    req = ImageGenerationRequest(
        product_name="StudyNest",
        pillar="Study Tips",
        hook="Stop losing 2 hours every evening to lesson planning.",
        target_audience="Teachers and educators",
        style="editorial",
    )

    prompt = provider.craft_prompt(req, "editorial")

    # Prompt explicitly forbids text, lettering, logos, watermarks, and typography
    assert "no text" in prompt.lower()
    assert "no lettering" in prompt.lower()
    assert "no words" in prompt.lower()
    assert "no logos" in prompt.lower()
    assert "no watermarks" in prompt.lower()
    assert "no signs" in prompt.lower()
    assert "no typography" in prompt.lower()

    # The brand name must NOT be sent to the diffusion model (it causes the model to draw the brand text)
    assert "studynest" not in prompt.lower()

    # The raw hook must NOT be enclosed in quotes as text to be rendered into the image
    assert "'Stop losing 2 hours every evening to lesson planning.'" not in prompt
    assert '"Stop losing 2 hours every evening to lesson planning."' not in prompt

    # Custom prompt also receives the no-text directive if not already specified
    custom_req = ImageGenerationRequest(
        prompt="A serene Japanese Zen garden with smooth stones and bamboo",
        product_name="StudyNest",
    )
    custom_prompt = provider.craft_prompt(custom_req, "minimalist")
    assert "serene japanese zen garden" in custom_prompt.lower()
    assert "no text" in custom_prompt.lower()

    # If custom prompt already has no text instruction, don't duplicate
    already_clean = ImageGenerationRequest(
        prompt="Cozy desk at sunset, absolutely no text",
    )
    result = provider.craft_prompt(already_clean, "professional")
    assert result == "Cozy desk at sunset, absolutely no text"


@pytest.mark.asyncio
async def test_pollinations_and_legacy_send_clean_no_text_prompt_in_url():
    """Both Pollinations and Legacy providers send clean no-text background prompts in their requests."""
    fake_bytes = b"\xff\xd8\xff\xe0mockcleanimage"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    req = ImageGenerationRequest(
        product_name="StudyNest",
        pillar="Organization",
        hook="Save hours on grading every week.",
        target_audience="High school teachers",
        style="professional",
    )

    # 1. Authenticated provider
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        auth_provider = PollinationsImageProvider(api_key="mock-key")
        await auth_provider.generate_image(req)

        called_url = mock_get.call_args[0][0]
        # URL-encoded prompt contains no-text constraints
        assert "no%20text" in called_url.lower() or "no%20lettering" in called_url.lower()
        # Does NOT have brand name or hook quoted for the model to spell
        assert "studynest" not in called_url.lower()
        assert "%27save%20hours" not in called_url.lower()

    # 2. Legacy provider
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        legacy_provider = PollinationsLegacyImageProvider()
        await legacy_provider.generate_image(req)

        called_url = mock_get.call_args[0][0]
        assert "no%20text" in called_url.lower() or "no%20lettering" in called_url.lower()
        assert "studynest" not in called_url.lower()
        assert "%27save%20hours" not in called_url.lower()


@pytest.mark.asyncio
async def test_sanitize_user_prompt_strips_quotes_brand_and_typography():
    """sanitize_user_prompt strips quoted strings, brand prefixes, and typography keywords."""
    from app.ai.providers.image_provider import sanitize_user_prompt

    legacy_prompt = (
        "Modern branded LinkedIn visual for StudyNest: 'It helps students organize their study sessions, "
        "manage assignment deadlines, and keep revision notes in one place.' in a sleek professional aesthetic "
        "targeted at College students who want to organize their studies, high contrast typography and gradient backdrop."
    )

    cleaned = sanitize_user_prompt(legacy_prompt)

    # 1. Quoted hook copy must be stripped
    assert "it helps students organize" not in cleaned.lower()
    assert "'" not in cleaned
    assert '"' not in cleaned

    # 2. Brand prefix must be stripped
    assert "for studynest:" not in cleaned.lower()

    # 3. Typography keyword must be stripped
    assert "typography" not in cleaned.lower()

    # 4. Core visual descriptors are preserved
    assert "modern branded linkedin visual" in cleaned.lower()
    assert "gradient backdrop" in cleaned.lower()


@pytest.mark.asyncio
async def test_craft_prompt_sanitizes_stale_legacy_prompt_override():
    """Even if an old prompt containing quotes and typography is supplied, craft_prompt sanitizes it."""
    provider = PollinationsImageProvider(api_key="mock-key")

    legacy_prompt = (
        "Modern branded LinkedIn visual for StudyNest: 'It helps students organize their study sessions' "
        "in a sleek professional aesthetic, high contrast typography and gradient backdrop."
    )
    req = ImageGenerationRequest(
        prompt=legacy_prompt,
        product_name="StudyNest",
    )

    result = provider.craft_prompt(req, "professional")

    # Stale positive typography request and quoted text stripped
    assert "it helps students organize" not in result.lower()
    assert "high contrast typography" not in result.lower()
    assert "for studynest" not in result.lower()

    # Pristine background directive added (including no typography constraint)
    assert "pristine visual background" in result.lower()
    assert "strictly no text" in result.lower()
    assert "no typography" in result.lower()


@pytest.mark.asyncio
async def test_regeneration_with_null_prompt_auto_crafts_fresh_prompt(authenticated_client):
    """Regenerating an existing image with prompt=None creates a fresh auto-crafted prompt
    and updates the image record with latest updated_at priority."""
    fake_bytes = b"\xff\xd8\xff\xe0mockcleanimage"
    mock_response = httpx.Response(
        status_code=200,
        content=fake_bytes,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://image.pollinations.ai/prompt/test"),
    )

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        # 1. First generation with custom override
        res1 = await authenticated_client.post(
            image_url(project_id),
            json={
                "provider": "pollinations_legacy",
                "prompt": "Custom legacy manual prompt override",
            },
        )
        assert res1.status_code == 200
        img1 = res1.json()["draft"]["image"]
        assert "Custom legacy manual prompt override" in img1["prompt"]

        # 2. Regeneration with prompt=null (simulates frontend clicking Regenerate without custom text)
        res2 = await authenticated_client.post(
            image_url(project_id),
            json={
                "provider": "pollinations_legacy",
                "prompt": None,
                "style": "bold",
                "aspect_ratio": "1:1",
            },
        )
        assert res2.status_code == 200
        img2 = res2.json()["draft"]["image"]

        # Verifies the fresh auto-crafted prompt was used, not the old prompt
        assert "Custom legacy manual prompt override" not in img2["prompt"]
        assert "Atmospheric environmental photography" in img2["prompt"]
        assert "strictly no text" in img2["prompt"]
        assert img2["aspect_ratio"] == "1:1"
        assert img2["style"] == "bold"
