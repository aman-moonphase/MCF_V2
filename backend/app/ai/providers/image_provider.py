"""Image generation provider abstraction and deterministic Demo Mode implementation.

Provides BaseImageProvider, DemoImageProvider, and get_image_provider.
When AI_PROVIDER is 'demo' (or in test environments), DemoImageProvider deterministically
produces clean, production-styled SVG data URIs without any external network or API calls.
"""

from abc import ABC, abstractmethod
import base64
import hashlib
import html
import random
import re
import urllib.parse
from typing import Optional
import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.redaction import redact_payload


class ImageGenerationRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, description="Creative prompt or description")
    aspect_ratio: str = Field(default="16:9", description="Aspect ratio: '16:9' or '1:1'")
    style: str = Field(default="professional", description="Visual styling: professional, minimalist, bold, editorial")
    alt_text: Optional[str] = Field(default=None, description="Accessibility alt text")
    product_name: Optional[str] = Field(default=None, description="Product brand name")
    hook: Optional[str] = Field(default=None, description="Post hook opening headline")
    body: Optional[str] = Field(default=None, description="Post body text")
    pillar: Optional[str] = Field(default=None, description="Content pillar")
    target_audience: Optional[str] = Field(default=None, description="Target audience")


class ImageGenerationResult(BaseModel):
    image_url: str
    prompt: str
    alt_text: str
    aspect_ratio: str
    style: str
    provider: str
    is_demo: bool = False


NO_TEXT_DIRECTIVE = (
    "pristine visual background, empty copy space, strictly no text, no words, "
    "no letters, no lettering, no alphabet, no signs, no logos, no typography, "
    "no watermarks, no labels, no handwriting, no writing"
)


def sanitize_user_prompt(user_prompt: str) -> str:
    """Sanitize custom user prompts to prevent diffusion models from attempting to render text or logos.

    Strips quoted post copy, brand prefixes (e.g. 'for StudyNest:'), and explicit typography keywords.
    """
    cleaned = user_prompt.strip()
    # Strip quoted strings (often containing copied post hooks, quotes, or slogans)
    cleaned = re.sub(r"""(?i)["'][^"']*["']""", "", cleaned)
    # Strip explicit typography, text, words, lettering, and logo keywords
    cleaned = re.sub(
        r"""(?i)\b(high[\s-]contrast\s+)?(typography|lettering|letters|words|alphabet|calligraphy|text\s+overlay|headline|slogan|watermark|logo|logos|signs)\b""",
        "",
        cleaned,
    )
    # Strip brand mentions like "for StudyNest:" or "for BrandName:"
    cleaned = re.sub(r"""(?i)\bfor\s+[a-z0-9_-]+:?""", "", cleaned)
    # Clean up dangling commas and extra whitespace
    cleaned = re.sub(r"""\s*,\s*,\s*""", ", ", cleaned)
    cleaned = re.sub(r"""^[,\s.-]+|[,\s.-]+$""", "", cleaned)
    cleaned = re.sub(r"""\s{2,}""", " ", cleaned)
    return cleaned.strip()


class BaseImageProvider(ABC):
    STYLE_PROMPT_MODIFIERS = {
        "professional": "sleek professional corporate aesthetic, clean modern composition, high resolution, soft studio lighting",
        "minimalist": "minimalist graphic aesthetic, clean negative space, monochrome styling, subtle elegant contrast",
        "bold": "bold dynamic visual, high contrast deep violet and vibrant rose accents, striking lighting, energetic composition",
        "editorial": "editorial aesthetic, refined teal and emerald palette, magazine layout style, sophisticated mood",
    }

    def craft_prompt(self, request: ImageGenerationRequest, style_key: str) -> str:
        """Craft a clean visual background prompt free of text or pseudo-typography.

        Text, branding, and post hooks are rendered separately by MCF's composition layer,
        preventing diffusion models from producing garbled, distorted, or duplicated lettering.
        Brand names (e.g. StudyNest) and headlines are intentionally excluded from the prompt
        so diffusion models do not attempt to paint them into the background.
        """
        directive = NO_TEXT_DIRECTIVE
        if request.prompt and request.prompt.strip():
            cleaned = sanitize_user_prompt(request.prompt)
            if cleaned and len(cleaned) >= 10:
                lower = cleaned.lower()
                if "no text" not in lower and "no lettering" not in lower and "no words" not in lower:
                    return f"{cleaned}, {directive}"
                return cleaned
            # If the user prompt was only quotes or typography keywords stripped down,
            # fall through to automated scene generation rather than sending an empty prompt.

        pillar = request.pillar or "Productivity"
        audience = request.target_audience or "educators, students, and professionals"
        style_desc = self.STYLE_PROMPT_MODIFIERS.get(style_key, self.STYLE_PROMPT_MODIFIERS["professional"])

        return (
            f"Atmospheric environmental photography. {pillar} theme concept, "
            f"modern organized study and work environment, calm productive atmosphere. "
            f"Style: {style_desc}. Tone: tailored for {audience}. {directive}."
        )

    def craft_alt_text(self, request: ImageGenerationRequest, style_key: str) -> str:
        if request.alt_text and request.alt_text.strip():
            return request.alt_text.strip()
        product = request.product_name or "StudyNest"
        hook = (request.hook or "")[:100]
        pillar = request.pillar or "Professional Insights"
        return f"Creative visual for {product} highlighting '{hook}' ({pillar} theme)."

    @abstractmethod
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        """Generate an image asset from the provided request."""
        pass


class DemoImageProvider(BaseImageProvider):
    """Deterministic, offline image provider creating clean SVG card visual assets."""

    STYLE_PALETTES = {
        "professional": {
            "bg_gradient": ("#0f172a", "#1e293b", "#334155"),
            "accent": "#38bdf8",
            "accent_secondary": "#818cf8",
            "card_bg": "rgba(30, 41, 59, 0.7)",
            "border": "rgba(56, 189, 248, 0.3)",
            "text": "#f8fafc",
            "subtext": "#94a3b8",
        },
        "minimalist": {
            "bg_gradient": ("#09090b", "#18181b", "#27272a"),
            "accent": "#a1a1aa",
            "accent_secondary": "#e4e4e7",
            "card_bg": "rgba(24, 24, 27, 0.6)",
            "border": "rgba(228, 228, 231, 0.2)",
            "text": "#fafafa",
            "subtext": "#a1a1aa",
        },
        "bold": {
            "bg_gradient": ("#180828", "#2e1065", "#4c1d95"),
            "accent": "#f43f5e",
            "accent_secondary": "#fb7185",
            "card_bg": "rgba(76, 29, 149, 0.4)",
            "border": "rgba(244, 63, 94, 0.35)",
            "text": "#ffffff",
            "subtext": "#e9d5ff",
        },
        "editorial": {
            "bg_gradient": ("#042f2e", "#115e59", "#134e4a"),
            "accent": "#2dd4bf",
            "accent_secondary": "#5eead4",
            "card_bg": "rgba(19, 78, 74, 0.5)",
            "border": "rgba(45, 212, 191, 0.3)",
            "text": "#f0fdfa",
            "subtext": "#99f6e4",
        },
    }

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        aspect = "1:1" if request.aspect_ratio == "1:1" else "16:9"
        style_key = request.style.lower() if request.style and request.style.lower() in self.STYLE_PALETTES else "professional"
        palette = self.STYLE_PALETTES[style_key]

        product = request.product_name or "Multimodal Content Factory"
        hook = request.hook or "Transform ideas into grounded, high-impact social content."
        pillar = request.pillar or "Product Insights"
        audience = request.target_audience or "Professionals"

        crafted_prompt = request.prompt or (
            f"Modern branded LinkedIn visual for {product}: '{hook}' in a sleek {style_key} aesthetic "
            f"targeted at {audience}, high contrast typography and gradient backdrop."
        )

        crafted_alt = request.alt_text or (
            f"Social card for {product} highlighting '{hook[:100]}' with {pillar} theme."
        )

        svg = self._render_svg(aspect, palette, product, hook, pillar, style_key)
        # Encode as data URI
        encoded_svg = urllib.parse.quote(svg)
        image_url = f"data:image/svg+xml;utf-8,{encoded_svg}"

        return ImageGenerationResult(
            image_url=image_url,
            prompt=crafted_prompt,
            alt_text=crafted_alt,
            aspect_ratio=aspect,
            style=style_key,
            provider="demo",
            is_demo=True,
        )

    def _render_svg(self, aspect: str, palette: dict, product: str, hook: str, pillar: str, style_key: str) -> str:
        width = 1200
        height = 1200 if aspect == "1:1" else 675

        # Truncate and escape text for SVG
        clean_product = html.escape(product[:40])
        clean_pillar = html.escape(pillar[:30].upper())
        # Wrap hook text
        words = hook.split()
        lines = []
        curr = ""
        max_chars = 42 if aspect == "16:9" else 36
        for w in words:
            if len(curr) + len(w) + 1 <= max_chars:
                curr = f"{curr} {w}".strip()
            else:
                if curr:
                    lines.append(html.escape(curr))
                curr = w
                if len(lines) >= 3:
                    break
        if curr and len(lines) < 3:
            lines.append(html.escape(curr))
        if not lines:
            lines = [html.escape(hook[:max_chars])]

        hook_spans = "".join(
            f'<tspan x="100" dy="{54 if i > 0 else 0}">{line}</tspan>' for i, line in enumerate(lines)
        )

        bg1, bg2, bg3 = palette["bg_gradient"]
        accent = palette["accent"]
        accent2 = palette["accent_secondary"]
        card_bg = palette["card_bg"]
        border = palette["border"]
        text_color = palette["text"]
        subtext_color = palette["subtext"]

        y_offset = 240 if aspect == "16:9" else 380

        # Generate grid lines spanning canvas height and width
        h_lines = "\n    ".join(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}"/>' for y in range(120, height - 60, 120))
        v_lines = "\n    ".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}"/>' for x in range(200, width - 100, 200))

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{bg1}"/>
      <stop offset="50%" stop-color="{bg2}"/>
      <stop offset="100%" stop-color="{bg3}"/>
    </linearGradient>
    <linearGradient id="acc" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{accent}"/>
      <stop offset="100%" stop-color="{accent2}"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="60" result="blur"/>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="{width}" height="{height}" fill="url(#bg)"/>

  <!-- Atmospheric Glow Accents -->
  <circle cx="{width - 150}" cy="150" r="220" fill="{accent}" opacity="0.18" filter="url(#glow)"/>
  <circle cx="150" cy="{height - 100}" r="260" fill="{accent2}" opacity="0.12" filter="url(#glow)"/>

  <!-- Geometric Grid Accent -->
  <g opacity="0.08" stroke="{accent}" stroke-width="1">
    {h_lines}
    {v_lines}
  </g>

  <!-- Glass Card Container -->
  <rect x="60" y="60" width="{width - 120}" height="{height - 120}" rx="28" fill="{card_bg}" stroke="{border}" stroke-width="2"/>

  <!-- Brand Pill & Pillar Header -->
  <g transform="translate(100, 110)">
    <rect width="180" height="36" rx="18" fill="{accent}" opacity="0.15"/>
    <text x="90" y="23" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" font-weight="700" fill="{accent}" text-anchor="middle" letter-spacing="1.5">{clean_pillar}</text>
    <text x="200" y="23" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="16" font-weight="600" fill="{subtext_color}">·  {clean_product}</text>
  </g>

  <!-- Headline / Hook -->
  <text x="100" y="{y_offset}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="44" font-weight="800" fill="{text_color}" letter-spacing="-0.5">
    {hook_spans}
  </text>

  <!-- Decorative Accent Bar -->
  <rect x="100" y="{height - 150}" width="72" height="6" rx="3" fill="url(#acc)"/>

  <!-- Footer Tagline -->
  <text x="100" y="{height - 110}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" font-weight="500" fill="{subtext_color}" letter-spacing="1">
    MCF CREATIVE PREVIEW  ·  LINKEDIN SOCIAL POST  ·  {style_key.upper()}
  </text>
</svg>"""
        return svg


class PollinationsImageProvider(BaseImageProvider):
    """Real AI image generator using Pollinations API (https://gen.pollinations.ai/image/{prompt}).

    Authenticates strictly via backend-only Authorization: Bearer header.
    Never exposes API keys in URLs, frontend code, or logs.
    """

    DEFAULT_BASE_URL = "https://gen.pollinations.ai/image"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.POLLINATIONS_API_KEY
        self.model = model or settings.POLLINATIONS_MODEL or "flux"
        self.timeout = timeout or settings.IMAGE_TIMEOUT_SECONDS or 60.0
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if not self.api_key or not self.api_key.strip():
            raise ValueError(
                "Pollinations API key is not configured. Set POLLINATIONS_API_KEY in the environment or configuration."
            )

        aspect = "1:1" if request.aspect_ratio == "1:1" else "16:9"
        style_key = (
            request.style.lower()
            if request.style and request.style.lower() in self.STYLE_PROMPT_MODIFIERS
            else "professional"
        )

        prompt = self.craft_prompt(request, style_key)
        alt_text = self.craft_alt_text(request, style_key)

        width = 1200
        height = 1200 if aspect == "1:1" else 675

        encoded_prompt = urllib.parse.quote(prompt, safe="")
        url = f"{self.base_url}/{encoded_prompt}"

        params = {
            "width": str(width),
            "height": str(height),
            "model": self.model,
            "nologo": "true",
        }

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Accept": "image/*",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Pollinations image generation timed out after {self.timeout} seconds."
            ) from exc
        except httpx.RequestError as exc:
            sanitized = redact_payload(str(exc))
            raise RuntimeError(f"Pollinations network request failed: {sanitized}") from exc

        if response.status_code != 200:
            sanitized_body = redact_payload(response.text[:200]) if response.text else ""
            raise RuntimeError(
                f"Pollinations API error ({response.status_code}): {sanitized_body or 'Upstream generation failure'}"
            )

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"

        b64_img = base64.b64encode(response.content).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64_img}"

        return ImageGenerationResult(
            image_url=data_uri,
            prompt=prompt,
            alt_text=alt_text,
            aspect_ratio=aspect,
            style=style_key,
            provider="pollinations",
            is_demo=False,
        )


MAX_IMAGE_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB ceiling


def _is_valid_image_payload(content: bytes, content_type: str) -> bool:
    """Validate that binary payload contains genuine image magic bytes and is not HTML/error text."""
    if not content or len(content) < 16:
        return False
    # Check for HTML / Cloudflare error page text
    snippet = content[:200].lower()
    if b"<!doctype html" in snippet or b"<html" in snippet or b"<head" in snippet or b"error" in snippet[:50]:
        return False
    # Magic bytes for JPEG: FF D8 FF
    if content.startswith(b"\xff\xd8\xff"):
        return True
    # PNG: \x89PNG\r\n\x1a\n
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    # WebP: RIFF....WEBP
    if content.startswith(b"RIFF") and b"WEBP" in content[8:16]:
        return True
    # GIF: GIF87a or GIF89a
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return True
    return content_type.startswith("image/")


class PollinationsLegacyImageProvider(BaseImageProvider):
    """Legacy unauthenticated Pollinations image generator (https://image.pollinations.ai/prompt/{prompt}).

    Replicates the reference application / n8n node behavior:
    - No API key or Authorization header required.
    - Best-effort unauthenticated community service; no uptime, rate-limit, or zero-cost guarantees.
    - Validates image magic bytes, enforces a 10MB response size ceiling, and applies strict timeouts.
    """

    DEFAULT_BASE_URL = "https://image.pollinations.ai/prompt"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model or getattr(settings, "POLLINATIONS_MODEL", "flux") or "flux"
        self.timeout = timeout or getattr(settings, "IMAGE_TIMEOUT_SECONDS", 60.0) or 60.0
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        aspect = "1:1" if request.aspect_ratio == "1:1" else "16:9"
        style_key = (
            request.style.lower()
            if request.style and request.style.lower() in self.STYLE_PROMPT_MODIFIERS
            else "professional"
        )

        prompt = self.craft_prompt(request, style_key)
        alt_text = self.craft_alt_text(request, style_key)

        width = 1024 if aspect == "1:1" else 1280
        height = 1024 if aspect == "1:1" else 720
        seed = random.randint(10000, 999999)

        encoded_prompt = urllib.parse.quote(prompt, safe="")
        url = f"{self.base_url}/{encoded_prompt}"

        params = {
            "width": str(width),
            "height": str(height),
            "seed": str(seed),
            "model": self.model,
            "nologo": "true",
        }

        # Crucial: NO Authorization header in legacy mode!
        headers = {
            "Accept": "image/*",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"Legacy Pollinations generator timed out after {self.timeout}s. "
                "The unauthenticated legacy service may be experiencing high queue delays."
            ) from exc
        except httpx.RequestError as exc:
            sanitized = redact_payload(str(exc))
            raise RuntimeError(
                f"Legacy Pollinations connection failed: {sanitized}. "
                "The legacy unauthenticated endpoint may be unreachable or throttled."
            ) from exc

        if response.status_code != 200:
            sanitized_body = redact_payload(response.text[:200]) if response.text else ""
            raise RuntimeError(
                f"Legacy Pollinations returned HTTP {response.status_code}: {sanitized_body or 'Best-effort generation failed'}. "
                "Note: Legacy unauthenticated mode has no SLA and may be rate-limited."
            )

        # Enforce response-size limits
        if len(response.content) > MAX_IMAGE_RESPONSE_BYTES:
            raise RuntimeError(
                f"Legacy Pollinations returned an oversized payload ({len(response.content)} bytes, max is {MAX_IMAGE_RESPONSE_BYTES} bytes)."
            )

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"

        # Content validation: verify legitimate image magic bytes
        if not _is_valid_image_payload(response.content, content_type):
            raise RuntimeError(
                "Legacy Pollinations returned invalid or non-image content (such as an HTML error/challenge page). "
                "The legacy unauthenticated service may be unavailable or blocked."
            )

        b64_img = base64.b64encode(response.content).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64_img}"

        return ImageGenerationResult(
            image_url=data_uri,
            prompt=prompt,
            alt_text=alt_text,
            aspect_ratio=aspect,
            style=style_key,
            provider="pollinations_legacy",
            is_demo=False,
        )


class RealImageProviderStub(BaseImageProvider):
    """Placeholder compatible with real API providers (e.g. OpenAI / DALL-E)."""

    def __init__(self, provider_name: str, api_key: Optional[str] = None):
        self.provider_name = provider_name
        self.api_key = api_key

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if not self.api_key:
            raise ValueError(f"API key missing for image provider '{self.provider_name}'")
        raise NotImplementedError(f"Real image generation for '{self.provider_name}' is not enabled in this environment.")


def get_image_provider(provider_name: Optional[str] = None) -> BaseImageProvider:
    """Return the configured image provider. In demo mode or test, returns DemoImageProvider."""
    configured_name = provider_name or getattr(settings, "IMAGE_PROVIDER", "demo")
    name = (configured_name or "demo").strip().lower()

    if name in ("pollinations_legacy", "pollinations-legacy", "legacy"):
        return PollinationsLegacyImageProvider(
            model=settings.POLLINATIONS_MODEL,
            timeout=settings.IMAGE_TIMEOUT_SECONDS,
        )
    if name == "pollinations":
        return PollinationsImageProvider(
            api_key=settings.POLLINATIONS_API_KEY,
            model=settings.POLLINATIONS_MODEL,
            timeout=settings.IMAGE_TIMEOUT_SECONDS,
        )
    if name == "demo":
        return DemoImageProvider()
    if name == "openai":
        if not settings.OPENAI_API_KEY:
            return DemoImageProvider()
        return RealImageProviderStub("openai", settings.OPENAI_API_KEY)
    return DemoImageProvider()

