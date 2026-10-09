"""The approved Content Type is a hard workflow constraint.

This module is the single place that knows the six supported content types, how each one is
structured, and how to detect generated output that drifts into a different format. It is used
for prompt construction (so models are told the constraint) and for validation (so output that
breaks the constraint is rejected and regenerated, never silently accepted).
"""

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

CONTENT_TYPES: tuple[str, ...] = ("Video", "Image", "Carousel", "Article", "Newsletter", "Social Post")


@dataclass(frozen=True)
class ContentTypeProfile:
    name: str
    unit: str  # what one structural element is called (scene, slide, section, ...)
    structure: str  # prompt guidance describing the deliverable
    default_platforms: tuple[str, ...]  # used by the deterministic demo provider
    format_patterns: tuple[str, ...]  # regexes that identify this format in a "format" field
    allowed_transitions: tuple[str, ...]  # transition vocabulary for storyboard units


PROFILES: dict[str, ContentTypeProfile] = {
    "Video": ContentTypeProfile(
        name="Video",
        unit="scene",
        structure=(
            "A video. Structure it as ordered scenes, each with spoken narration, visual direction, "
            "on-screen text, a cut or transition, and an estimated duration in seconds."
        ),
        default_platforms=("YouTube", "LinkedIn", "Instagram"),
        format_patterns=(r"\bvideos?\b", r"\breels?\b", r"\bvlogs?\b", r"\bwebinars?\b", r"\blive ?streams?\b",
                         r"\byoutube shorts?\b", r"\bscreen ?recordings?\b", r"\bclips?\b"),
        allowed_transitions=("Cut", "Fade", "Dissolve", "Zoom", "Pan", "Jump cut", "None"),
    ),
    "Image": ContentTypeProfile(
        name="Image",
        unit="element",
        structure=(
            "A single static image with a caption. Structure it as the elements of ONE image "
            "(headline text, main visual, supporting text, caption). No motion, no slides, no scenes."
        ),
        default_platforms=("Instagram", "LinkedIn", "Pinterest"),
        format_patterns=(r"\bimages?\b", r"\binfographics?\b", r"\bphotos?\b", r"\bsingle[- ]image\b",
                         r"\bquote cards?\b", r"\bposters?\b", r"\bmemes?\b"),
        allowed_transitions=("None",),
    ),
    "Carousel": ContentTypeProfile(
        name="Carousel",
        unit="slide",
        structure=(
            "A swipeable multi-slide carousel post. Structure it as ordered slides (typically 5-10), each "
            "with on-slide text and a visual layout. Slides are swiped, not played: no video, no voice-over timing."
        ),
        default_platforms=("LinkedIn", "Instagram"),
        format_patterns=(r"\bcarousels?\b", r"\bslides?\b", r"\bslide ?decks?\b", r"\bswipe\b",
                         r"\bdocument posts?\b"),
        allowed_transitions=("Swipe", "None"),
    ),
    "Article": ContentTypeProfile(
        name="Article",
        unit="section",
        structure=(
            "A long-form written article or blog post. Structure it as titled sections of written paragraphs. "
            "No video scenes and no slides."
        ),
        default_platforms=("Blog", "LinkedIn", "Medium"),
        format_patterns=(r"\barticles?\b", r"\bblogs?\b", r"\bblog posts?\b", r"\bessays?\b",
                         r"\bwhite ?papers?\b", r"\blong[- ]form (written|post|article)s?\b"),
        allowed_transitions=("None", "Section break"),
    ),
    "Newsletter": ContentTypeProfile(
        name="Newsletter",
        unit="section",
        structure=(
            "An email newsletter. Structure it as email sections (subject line, opening, body sections, "
            "call to action). It is delivered by email, not as a video or slides."
        ),
        default_platforms=("Email", "LinkedIn Newsletter"),
        format_patterns=(r"\bnewsletters?\b", r"\be-?mails?\b", r"\bdigests?\b"),
        allowed_transitions=("None", "Section break"),
    ),
    "Social Post": ContentTypeProfile(
        name="Social Post",
        unit="section",
        structure=(
            "A single text-first social media post (for example a LinkedIn or X post, or a short thread). "
            "Structure it as hook, body, and call to action. No slides and no video scenes; an image is optional "
            "and secondary to the text."
        ),
        default_platforms=("LinkedIn", "X (Twitter)"),
        format_patterns=(r"\bsocial(?: media)? posts?\b", r"\btext posts?\b", r"\btext-only\b", r"\bthreads?\b",
                         r"\btweets?\b", r"\bstatus updates?\b", r"\bshort posts?\b"),
        allowed_transitions=("None", "Line break"),
    ),
}

# Transition words that only make sense for one family of formats.
_VIDEO_TRANSITIONS = re.compile(r"\b(cut|cuts|fade|fades|dissolve|wipe|zoom|pan|jump[- ]cut|crossfade|b-roll)\b", re.I)
_CAROUSEL_TRANSITIONS = re.compile(r"\bswipe", re.I)


def normalize_content_type(value: Optional[str]) -> Optional[str]:
    """Return the canonical content type name, or None if `value` is not one of the six."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split()).lower()
    for name in CONTENT_TYPES:
        if cleaned == name.lower():
            return name
    return None


def require_content_type(value: Optional[str]) -> str:
    name = normalize_content_type(value)
    if name is None:
        raise ValueError(f"'{value}' is not a supported content type. Supported: {', '.join(CONTENT_TYPES)}.")
    return name


def get_profile(content_type: Optional[str]) -> Optional[ContentTypeProfile]:
    name = normalize_content_type(content_type)
    return PROFILES.get(name) if name else None


def matched_types(text: Optional[str]) -> list[str]:
    """Content types whose format vocabulary appears in `text`."""
    if not text:
        return []
    return [
        name for name, profile in PROFILES.items()
        if any(re.search(pattern, text, re.I) for pattern in profile.format_patterns)
    ]


def format_conflicts(approved: str, text: Optional[str]) -> list[str]:
    """Other content types that `text` describes, unless it also clearly describes `approved`.

    "LinkedIn Carousel" is fine for Carousel; "Long-form video" is a conflict for Carousel;
    "Image carousel" is fine for Carousel because the approved type is named explicitly.
    """
    found = matched_types(text)
    if not found or approved in found:
        return []
    return found


def constraint_block(approved: Optional[str]) -> str:
    """Prompt text stating the approved content type as a hard constraint."""
    profile = get_profile(approved)
    if profile is None:
        return (
            "No content type has been approved yet. Choose formats only from: "
            f"{', '.join(CONTENT_TYPES)}."
        )
    others = ", ".join(t for t in CONTENT_TYPES if t != profile.name)
    return (
        f"APPROVED CONTENT TYPE — HARD CONSTRAINT: {profile.name}\n"
        f"The user approved \"{profile.name}\" as the only deliverable format for this project.\n"
        f"- Deliverable: {profile.structure}\n"
        f"- Every field that names a format (content_type, recommendedFormat, format, platform adaptations) "
        f"must describe a {profile.name}.\n"
        f"- Do NOT propose or structure the output as any other content type ({others}).\n"
        f"- Storyboard/script units are {profile.unit}s; allowed transitions: {', '.join(profile.allowed_transitions)}."
    )


# ─── Output validation ────────────────────────────────────────────────────────

def _conflict_message(where: str, value: str, approved: str, conflicts: Sequence[str]) -> str:
    return (
        f"{where} describes '{value}' ({', '.join(conflicts)}), which is incompatible with the approved "
        f"content type '{approved}'."
    )


def check_opportunities(approved: Optional[str], opportunities: Iterable[dict]) -> Optional[str]:
    if not approved:
        return None
    for opp in opportunities:
        if normalize_content_type(opp.get("content_type")) != approved:
            return (
                f"Generated opportunity {opp.get('id')} has content_type {opp.get('content_type')}, "
                f"but {approved} was approved."
            )
    return None


def check_platform_recommendations(approved: Optional[str], recommendations: Iterable[dict]) -> Optional[str]:
    if not approved:
        return None
    for rec in recommendations:
        value = rec.get("recommendedFormat") or ""
        conflicts = format_conflicts(approved, value)
        if conflicts:
            return _conflict_message(f"Platform recommendation '{rec.get('platform')}'", value, approved, conflicts)
    return None


def check_topic_angles(approved: Optional[str], angles: Iterable[dict]) -> Optional[str]:
    if not approved:
        return None
    for angle in angles:
        value = angle.get("angle") or ""
        conflicts = format_conflicts(approved, value)
        if conflicts:
            return _conflict_message(f"Topic angle '{angle.get('id')}'", value, approved, conflicts)
    return None


def check_strategy(approved: Optional[str], strategy: dict) -> Optional[str]:
    if not approved:
        return None
    value = strategy.get("format") or ""
    conflicts = format_conflicts(approved, value)
    if conflicts:
        return _conflict_message("Content strategy format", value, approved, conflicts)
    for adaptation in strategy.get("platformAdaptations") or []:
        value = adaptation.get("format") or ""
        conflicts = format_conflicts(approved, value)
        if conflicts:
            return _conflict_message(
                f"Platform adaptation for '{adaptation.get('platform')}'", value, approved, conflicts
            )
    return None


def check_storyboard(approved: Optional[str], storyboard: dict) -> Optional[str]:
    if not approved:
        return None
    for scene in storyboard.get("scenes") or []:
        transition = scene.get("transition") or ""
        if approved != "Video" and _VIDEO_TRANSITIONS.search(transition):
            return (
                f"Storyboard {PROFILES[approved].unit} {scene.get('order')} uses the video transition "
                f"'{transition}', which is incompatible with the approved content type '{approved}'."
            )
        if approved != "Carousel" and _CAROUSEL_TRANSITIONS.search(transition):
            return (
                f"Storyboard {PROFILES[approved].unit} {scene.get('order')} uses the carousel transition "
                f"'{transition}', which is incompatible with the approved content type '{approved}'."
            )
    return None


def check_script(approved: Optional[str], script: dict) -> Optional[str]:
    if not approved:
        return None
    value = script.get("format") or ""
    conflicts = format_conflicts(approved, value)
    if conflicts:
        return _conflict_message("Script format", value, approved, conflicts)
    return None
