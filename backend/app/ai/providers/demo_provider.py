"""Deterministic Demo Mode provider.

Demo Mode lets MCF run end to end without an AI API key. It is NOT a language model and must
never pretend to be one. It reads the current project's data (via the generation context set by
the workflow nodes, or the prompt when called directly) and builds every stage's output from that
data alone. Its contract is DEMO_MODE_RULES below.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Type

from pydantic import BaseModel

from .base import BaseAIProvider
from ..content_types import CONTENT_TYPES, PROFILES, ContentTypeProfile, normalize_content_type
from ..generation_context import get_generation_context

# The Demo Mode rules (previously appended to every prompt, including prompts sent to real
# providers). They now live only here, with the deterministic implementation they describe.
DEMO_MODE_RULES = """
DEMO MODE — AVAILABLE DATA ONLY
1. AVAILABLE DATA IS THE SOURCE OF TRUTH: Demo Mode uses only the CURRENT project's data: the user's input,
   ingested document/URL text, retrieved chunks, and the choices approved in earlier stages.
2. DO NOT INVENT MISSING INFORMATION: no statistics, research findings, company facts, quotes, dates, names,
   or numerical claims that are not in the project's data.
3. GENERATE ONLY WHAT THE DATA SUPPORTS: when the source has few points, produce fewer specifics and say where
   the user should add detail, instead of padding.
4. NO FAKE EXTERNAL KNOWLEDGE and NO CROSS-PROJECT LEAKAGE.
5. BE HONEST ABOUT BEING A PLACEHOLDER: reasoning fields state that the output is a deterministic demo
   derived from the project's own text, not AI analysis or product intelligence.
"""

DEMO_NOTE = "(Demo mode: derived deterministically from this project's own text, not AI analysis.)"

_FALLBACK_TOPIC = "this project"

_FORMAT_LABELS = {
    "Video": "Short-form video",
    "Image": "Single image post",
    "Carousel": "Carousel",
    "Article": "Long-form article",
    "Newsletter": "Email newsletter",
    "Social Post": "Text social post",
}

_LENGTHS = {
    "Video": "60-90 seconds",
    "Image": "1 image with a short caption",
    "Carousel": "5-8 slides",
    "Article": "1,000-1,500 words",
    "Newsletter": "500-800 words",
    "Social Post": "150-250 words",
}

_VISUALS = {
    "Video": "Camera or screen footage that shows {subject}",
    "Image": "Visual element of the single image: {subject}",
    "Carousel": "Slide layout: bold headline about {subject} with one supporting line",
    "Article": "Written section; optional illustrative image of {subject}",
    "Newsletter": "Email body section about {subject}",
    "Social Post": "Text only; an optional supporting image of {subject}",
}

_LABEL_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z /&()'-]{1,40}):\s*(.+)$")
_AUDIENCE_LABELS = ("target users", "target user", "target audience", "audience", "ideal customer", "for whom", "users")
_DIFFERENTIATOR_LABELS = ("differentiator", "differentiators", "unique value", "usp", "why us", "positioning")
_CTA_LABELS = ("cta", "call to action")
_TOPIC_LABELS = ("product", "title", "idea", "topic", "name", "project", "subject", "brand")


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _cap(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _shorten(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-— ")


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [_clean(p).rstrip(".") for p in parts if _clean(p)]


def _split_items(body: str) -> List[str]:
    items = [re.sub(r"^(and|or)\s+", "", i.strip(), flags=re.I) for i in re.split(r"[,;]", body)]
    return [_cap(_clean(i)) for i in items if i.strip()]


@dataclass
class _DemoProject:
    source: str
    content_type: Optional[str]
    topic: str
    descriptor: str
    audience: str
    differentiator: Optional[str]
    cta: str
    points: List[str]
    ctx: Mapping[str, Any] = field(default_factory=dict)

    @property
    def profile(self) -> Optional[ContentTypeProfile]:
        return PROFILES.get(self.content_type) if self.content_type else None

    @property
    def type_label(self) -> str:
        return self.content_type or "Content"

    @property
    def format_label(self) -> str:
        return _FORMAT_LABELS.get(self.content_type, "Post")

    @property
    def unit(self) -> str:
        return self.profile.unit if self.profile else "section"

    def platforms(self) -> List[str]:
        selected = [p.get("platform") for p in (self.ctx.get("selected_platforms") or []) if p.get("platform")]
        if selected:
            return selected
        if self.profile:
            return list(self.profile.default_platforms)
        return ["LinkedIn", "X (Twitter)", "Blog"]

    def point(self, index: int) -> Optional[str]:
        return self.points[index] if index < len(self.points) else None


def _parse_source_from_prompt(prompt: str) -> str:
    match = re.search(r"Source (?:Material|Topic):[ \t]*(.*?)(?:\n\n|\Z)", prompt or "", re.S)
    if not match:
        return ""
    lines = [
        line for line in match.group(1).strip().splitlines()
        if not re.search(r"approved the content type|approved content type|target content type", line, re.I)
    ]
    return "\n".join(lines).strip()


def _parse_type_from_prompt(prompt: str) -> Optional[str]:
    patterns = (
        r"HARD CONSTRAINT:\s*([A-Za-z ]+)",
        r"Approved Content Type:\s*([A-Za-z ]+)",
        r"approved the Content Type:\s*\"?([A-Za-z ]+?)\"?(?:[.\n]|$)",
        r"Target Content Type:\s*([A-Za-z ]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt or "")
        if match:
            name = normalize_content_type(match.group(1))
            if name:
                return name
    return None


def _extract_topic(source: str) -> tuple[str, str]:
    """Return (topic, descriptor) from the first sentence of the source."""
    sentences = _sentences(source)
    if not sentences:
        return _FALLBACK_TOPIC, ""
    first = sentences[0]
    label = _LABEL_PATTERN.match(first)
    if label and label.group(1).strip().lower() in _TOPIC_LABELS:
        first = label.group(2).strip()
    head, descriptor = first, ""
    for separator in (" - ", " — ", " – ", ": ", ", "):
        if separator in first:
            candidate, rest = first.split(separator, 1)
            if 1 <= len(candidate.split()) <= 8:
                head, descriptor = candidate, rest
                break
    topic = _shorten(head, 80) or _FALLBACK_TOPIC
    return topic, _shorten(descriptor or first, 200)


def _extract_labelled(source: str) -> Dict[str, str]:
    labelled: Dict[str, str] = {}
    for sentence in _sentences(source):
        match = _LABEL_PATTERN.match(sentence)
        if match:
            labelled.setdefault(match.group(1).strip().lower(), match.group(2).strip())
    return labelled


def _extract_points(source: str, topic: str) -> List[str]:
    points: List[str] = []
    sentences = _sentences(source)
    for index, sentence in enumerate(sentences):
        match = _LABEL_PATTERN.match(sentence)
        body = match.group(2) if match else sentence
        label = match.group(1).strip().lower() if match else ""
        if label in _TOPIC_LABELS or (index == 0 and not match):
            continue
        items = _split_items(body)
        if match and len(items) >= 3:
            points.extend(items)
        else:
            points.append(_cap(sentence))
    seen, unique = set(), []
    for p in points:
        p = _shorten(p, 160)
        key = p.lower()
        if p and key not in seen and key != topic.lower():
            seen.add(key)
            unique.append(p)
    return unique


def _build_project(prompt: str) -> _DemoProject:
    ctx = get_generation_context() or {}
    source = ctx.get("input_text") or ""
    if not source.strip():
        source = _parse_source_from_prompt(prompt)
    content_type = normalize_content_type(ctx.get("approved_content_type")) or _parse_type_from_prompt(prompt)

    topic, descriptor = _extract_topic(source)
    labelled = _extract_labelled(source)
    audience = next((labelled[k] for k in _AUDIENCE_LABELS if k in labelled), None)
    if not audience:
        match = re.search(r"\bfor ([^.,;]{3,80})", descriptor)
        audience = match.group(1).strip() if match else f"People interested in {topic}"
    differentiator = next((labelled[k] for k in _DIFFERENTIATOR_LABELS if k in labelled), None)
    cta = next((labelled[k] for k in _CTA_LABELS if k in labelled), None) or f"Learn more about {topic}"

    return _DemoProject(
        source=source,
        content_type=content_type,
        topic=topic,
        descriptor=descriptor or topic,
        audience=_shorten(audience, 160),
        differentiator=_shorten(differentiator, 200) if differentiator else None,
        cta=_shorten(cta, 160),
        points=_extract_points(source, topic),
        ctx=ctx,
    )


def _missing_detail(p: _DemoProject) -> str:
    return f"Add a specific detail about {p.topic} from your source material here"


# ─── Stage builders ───────────────────────────────────────────────────────────

def _recommend_type(p: _DemoProject) -> str:
    text = p.source.lower()
    cues = [
        ("Video", ("video", "demo reel", "walkthrough", "tutorial")),
        ("Newsletter", ("newsletter", "subscribers", "waitlist", "email")),
        ("Article", ("article", "blog", "guide", "whitepaper")),
        ("Carousel", ("carousel", "slides", "step-by-step", "steps")),
        ("Image", ("infographic", "image", "poster")),
    ]
    for name, words in cues:
        if any(word in text for word in words):
            return name
    return "Carousel" if len(p.points) >= 4 else "Social Post"


def _content_type_output(p: _DemoProject) -> dict:
    recommended = _recommend_type(p)
    signals = p.points[:3] or [p.descriptor]
    return {
        "recommendation": {
            "recommendedType": recommended,
            "alternatives": [t for t in CONTENT_TYPES if t != recommended][:3],
            "reasoning": (
                f"{DEMO_NOTE} The source describes {p.topic} with {len(p.points)} distinct point(s), "
                f"which fits the structure of a {recommended}."
            ),
            "sourceSignals": signals,
        }
    }


def _content_plan_output(p: _DemoProject) -> dict:
    return {
        "summary": f"A content plan for {p.topic}: {p.descriptor}",
        "audience": p.audience,
        "key_points": p.points[:5] or [p.descriptor],
        "suggested_angles": [f"How {p.topic} works", f"The problem {p.topic} solves", f"Getting started with {p.topic}"],
    }


def _opportunities_output(p: _DemoProject) -> dict:
    content_type = p.content_type or _recommend_type(p)
    platforms = p.platforms()
    focus = [
        (f"{content_type}: What {p.topic} is and who it is for", p.descriptor),
        (f"{content_type}: {p.point(0) or 'The core idea of ' + p.topic}", p.point(0) or p.descriptor),
        (f"{content_type}: {p.topic} in practice", p.point(1) or p.descriptor),
    ]
    opportunities = []
    for index, (title, angle) in enumerate(focus):
        platform = platforms[index % len(platforms)]
        key_points = p.points[index:index + 4] or [p.descriptor]
        opportunities.append({
            "id": f"opt-{index + 1}",
            "content_type": content_type,
            "platform": platform,
            "title": _shorten(title, 140),
            "summary": f"A {content_type.lower()} for {platform} about {p.topic}, focused on: {angle}.",
            "whyInteresting": f"{DEMO_NOTE} It is built around a point stated in the source: {angle}.",
            "keyPoints": key_points,
            "potentialAudience": p.audience,
            "estimatedValue": "Not estimated in demo mode",
        })
    return {"opportunities": opportunities}


def _platforms_output(p: _DemoProject) -> dict:
    platforms = (list(p.profile.default_platforms) if p.profile else ["LinkedIn", "X (Twitter)", "Blog"])[:3]
    recommendations = []
    for index, platform in enumerate(platforms):
        recommendations.append({
            "id": f"plat-{index + 1}",
            "projectId": "project",
            "platform": platform,
            "suitability": 90 - index * 10,
            "reasoning": (
                f"{DEMO_NOTE} Demo ranking, not a measured score: {platform} supports the "
                f"{p.format_label.lower()} format for reaching {p.audience}."
            ),
            "recommendedFormat": f"{p.format_label} on {platform}",
            "recommendedLength": _LENGTHS.get(p.content_type, "Short"),
            "audience": p.audience,
            "tone": "Clear, practical, and specific to the source",
            "priority": "Recommended" if index < 2 else "Optional",
        })
    return {"recommendations": recommendations}


def _angles_output(p: _DemoProject) -> dict:
    platforms = p.platforms()
    specs = [
        ("Educational", f"How {p.topic} works", p.point(0) or p.descriptor),
        ("Problem / Solution", f"The problem {p.topic} solves", p.differentiator or p.point(1) or p.descriptor),
        ("Blueprint", f"Getting started with {p.topic}", p.point(2) or p.descriptor),
    ]
    angles = []
    for index, (angle, title, hook_basis) in enumerate(specs):
        angles.append({
            "id": f"ang-{index + 1}",
            "projectId": "project",
            "title": _shorten(title, 120),
            "angle": angle,
            "hook": _shorten(f"{_cap(hook_basis)}.", 200),
            "description": f"A {angle.lower()} take on {p.topic} for {p.audience}.",
            "targetAudience": p.audience,
            "corePromise": _shorten(f"Understand {p.topic}: {hook_basis}", 200),
            "differentiation": p.differentiator or "Stays specific to what the source says about the subject.",
            "supportingPoints": p.points[index:index + 4] or [p.descriptor],
            "recommendedPlatforms": platforms[:2],
        })
    return {"angles": angles}


def _strategy_output(p: _DemoProject) -> dict:
    platforms = p.platforms()
    angle = p.ctx.get("selected_angle") or {}
    hook = angle.get("hook") or _cap(p.point(0) or p.descriptor)
    structure = " → ".join(
        [f"Hook {p.unit}"] + [f"{_cap(p.unit)} {i + 2}: {pt}" for i, pt in enumerate(p.points[:4])] + [f"Call-to-action {p.unit}"]
    )
    return {
        "strategy": {
            "id": "strategy-1",
            "projectId": "project",
            "objective": f"Introduce {p.topic} to {p.audience} through a {p.format_label.lower()}.",
            "targetAudience": p.audience,
            "coreMessage": _cap(p.descriptor),
            "valueProposition": p.differentiator or _cap(p.point(0) or p.descriptor),
            "tone": "Clear, practical, and specific to the source",
            "format": p.format_label,
            "hookStrategy": f"Open with: {hook}",
            "keyTalkingPoints": p.points[:5] or [p.descriptor],
            "callToAction": p.cta,
            "contentStructure": structure,
            "platformAdaptations": [
                {"platform": platform, "format": f"{p.format_label} on {platform}",
                 "notes": f"Adapt length and tone to {platform} conventions; keep the subject on {p.topic}."}
                for platform in platforms[:3]
            ],
        }
    }


def _storyboard_units(p: _DemoProject) -> List[dict]:
    content_type = p.content_type
    unit = p.unit
    transition = (p.profile.allowed_transitions[0] if p.profile else "None")
    visual = _VISUALS.get(content_type, "Supporting visual for {subject}")
    durations = content_type == "Video"

    if content_type == "Image":
        specs = [
            ("Headline", "State the main message", _cap(p.descriptor)),
            ("Main visual", "Show the subject", f"The main visual focuses on {p.topic}."),
            ("Supporting text", "Add one supporting point", _cap(p.point(0) or _missing_detail(p))),
            ("Caption", "Give context and the call to action", f"{_cap(p.descriptor)}. {p.cta}."),
        ]
    else:
        point_count = 3 if content_type in ("Social Post", "Newsletter") else 5
        body_points = p.points[:point_count]
        while len(body_points) < 2:
            body_points.append(_missing_detail(p))
        opening = "Subject line and opening" if content_type == "Newsletter" else (
            "Introduction" if content_type == "Article" else "Hook")
        intro = f"{_cap(p.topic)}: {p.descriptor}." if p.descriptor.lower() != p.topic.lower() else f"Introducing {p.topic}."
        specs = [(opening, "Grab attention and state the subject", intro)]
        specs += [
            (_shorten(pt, 60), f"Explain one point from the source about {p.topic}", f"{_cap(pt)}.")
            for pt in body_points
        ]
        specs.append(("Call to action", "Tell the audience what to do next", f"{p.cta}."))

    units = []
    for index, (title, purpose, narration) in enumerate(specs):
        units.append({
            "id": f"{unit}-{index + 1}",
            "order": index + 1,
            "title": title,
            "purpose": purpose,
            "narration": narration,
            "visualDirection": visual.format(subject=_shorten(title, 60)),
            "onScreenText": _shorten(narration, 120),
            "transition": "None" if index == len(specs) - 1 else transition,
            "estimatedDuration": ("5 seconds" if index in (0, len(specs) - 1) else "10 seconds") if durations else "N/A",
        })
    return units


def _storyboard_output(p: _DemoProject) -> dict:
    return {
        "storyboard": {
            "id": "sb-1",
            "projectId": "project",
            "title": f"{p.topic} — {p.type_label} storyboard",
            "objective": f"Present {p.topic} to {p.audience} as a {p.format_label.lower()}.",
            "status": "Draft",
            "scenes": _storyboard_units(p),
        }
    }


def _script_output(p: _DemoProject) -> dict:
    storyboard = p.ctx.get("approved_storyboard") or {}
    scenes = storyboard.get("scenes") or _storyboard_units(p)
    platforms = p.platforms()
    sections = []
    for index, scene in enumerate(scenes):
        narration = scene.get("narration") or scene.get("title") or _missing_detail(p)
        sections.append({
            "id": f"section-{index + 1}",
            "order": scene.get("order") or index + 1,
            "title": scene.get("title") or f"{_cap(p.unit)} {index + 1}",
            "narration": narration,
            "visualNotes": scene.get("visualDirection") or _VISUALS.get(p.content_type, "Supporting visual for {subject}").format(subject=p.topic),
            "onScreenText": scene.get("onScreenText") or _shorten(narration, 120),
            "estimatedDuration": scene.get("estimatedDuration") or "N/A",
        })
    words = sum(len(s["narration"].split()) for s in sections)
    if p.content_type == "Video":
        total = sum(int(m.group(1)) for s in sections for m in [re.match(r"(\d+)", s["estimatedDuration"])] if m)
        duration = f"{total} seconds" if total else "N/A"
    else:
        duration = f"About {max(1, round(words / 200))} min read"
    return {
        "script": {
            "id": "script-1",
            "projectId": "project",
            "title": f"{p.topic} — {p.type_label} script",
            "platform": platforms[0],
            "format": p.format_label,
            "hook": sections[0]["narration"] if sections else _cap(p.descriptor),
            "conclusion": _cap(p.descriptor),
            "callToAction": p.cta,
            "estimatedDuration": duration,
            "status": "Draft",
            "sections": sections,
        }
    }


_BUILDERS: Dict[str, Callable[[_DemoProject], dict]] = {
    "ContentTypeOutput": _content_type_output,
    "ContentPlanOutput": _content_plan_output,
    "ContentSelectionOutput": _opportunities_output,
    "PlatformStrategyOutput": _platforms_output,
    "TopicAngleOutput": _angles_output,
    "ContentStrategyOutput": _strategy_output,
    "StoryboardOutput": _storyboard_output,
    "ScriptOutput": _script_output,
}


class DemoProvider(BaseAIProvider):
    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any:
        from .demo_competitor import build_demo_comparison, build_demo_competitor_analysis
        from .demo_product import build_demo_profile, build_demo_questions
        from .demo_strategy import build_demo_strategy
        from .demo_generation import build_demo_linkedin_post

        product_builders = {
            "ProductProfileDraft": build_demo_profile,
            "ClarificationQuestionsOutput": build_demo_questions,
            "CompetitorAnalysisOutput": build_demo_competitor_analysis,
            "ComparisonOutput": build_demo_comparison,
            "PromotionStrategyOutput": build_demo_strategy,
            "LinkedInPostOutput": build_demo_linkedin_post,
        }
        if schema.__name__ == "CompetitorSuggestionsOutput":
            # Demo Mode never invents competitor companies.
            raise ValueError("Demo Mode cannot suggest competitors; add them manually or name them in your sources.")
        if schema.__name__ in product_builders:
            return schema.model_validate(product_builders[schema.__name__](prompt))
        builder = _BUILDERS.get(schema.__name__)
        if builder is None:
            raise ValueError(f"DemoProvider has no deterministic output for schema '{schema.__name__}'.")
        return schema.model_validate(builder(_build_project(prompt)))

    async def generate_text(self, prompt: str) -> str:
        p = _build_project(prompt)
        points = "\n".join(f"- {pt}" for pt in p.points[:5]) or "- (The source contains no further detail.)"
        return (
            f"{DEMO_NOTE}\n"
            f"Subject: {p.topic}\n"
            f"Description: {p.descriptor}\n"
            f"Audience: {p.audience}\n"
            f"Points stated in the source:\n{points}"
        )
