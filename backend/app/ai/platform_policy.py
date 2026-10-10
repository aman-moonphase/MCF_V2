"""Centralized, configurable output policy for generated content.

The MVP of the product workflow produces exactly ONE output: a LinkedIn Social Post. The six
content types still exist (app/ai/content_types.py) and legacy projects keep their behaviour, but
only the types listed in GENERATION_SUPPORTED_TYPES can go through Generate Content.
"""

from dataclasses import dataclass
from typing import Dict, Optional

MVP_CONTENT_TYPE = "Social Post"
MVP_PLATFORM_KEY = "linkedin"
GENERATION_SUPPORTED_TYPES: frozenset[str] = frozenset({MVP_CONTENT_TYPE})


@dataclass(frozen=True)
class PlatformPolicy:
    key: str
    name: str
    content_type: str
    max_chars: int  # whole post: hook + body + CTA + hashtags
    hook_max_chars: int  # roughly what shows before LinkedIn's "…see more"
    max_hashtags: int
    alternative_hooks: int


def platform_policy(key: str = MVP_PLATFORM_KEY) -> PlatformPolicy:
    from app.core.config import settings

    policies: Dict[str, PlatformPolicy] = {
        "linkedin": PlatformPolicy(
            key="linkedin", name="LinkedIn", content_type=MVP_CONTENT_TYPE,
            max_chars=settings.LINKEDIN_POST_MAX_CHARS, hook_max_chars=settings.LINKEDIN_HOOK_MAX_CHARS,
            max_hashtags=5, alternative_hooks=3,
        ),
    }
    return policies[key]


def generation_support(content_type: Optional[str]) -> Optional[str]:
    """None when the type can be generated; otherwise a user-facing reason."""
    if content_type in GENERATION_SUPPORTED_TYPES:
        return None
    return (f"Generate Content currently produces only a LinkedIn {MVP_CONTENT_TYPE}. The approved content type is "
            f"'{content_type}'. Choose '{MVP_CONTENT_TYPE}' in the Content Type stage to generate in this version.")


MVP_STRATEGY_NOTE = (f"MVP output constraint: this version can only generate a LinkedIn {MVP_CONTENT_TYPE}. "
                     f"content_direction.primary_content_type must be '{MVP_CONTENT_TYPE}' and LinkedIn must be the "
                     "primary channel. Another type that would suit the product better may be listed as an alternative.")


def apply_mvp_content_type(strategy: dict) -> dict:
    """Steer a generated Promotion Strategy to the one type the MVP can generate.

    A different recommended type is never dropped silently: it becomes the first alternative and the
    change is stated in `limitations`. LinkedIn becomes the primary channel.
    """
    s = dict(strategy)
    cd = dict(s.get("content_direction") or {})
    original = cd.get("primary_content_type")
    if original and original != MVP_CONTENT_TYPE:
        cd["primary_content_type"] = MVP_CONTENT_TYPE
        cd["alternatives"] = [t for t in dict.fromkeys([original, *(cd.get("alternatives") or [])]) if t != MVP_CONTENT_TYPE][:2]
        cd["reason"] = (f"{cd.get('reason', '').strip()} This version generates LinkedIn {MVP_CONTENT_TYPE}s only, so "
                        f"{original} is kept as an alternative for later.").strip()
        s["roadmap"] = [{**r, "format": MVP_CONTENT_TYPE} for r in s.get("roadmap") or []]
        s["channels"] = [{**c, "formats": [MVP_CONTENT_TYPE if f == original else f for f in c.get("formats") or []]}
                         for c in s.get("channels") or []]
        cadence = dict(s.get("cadence") or {})
        if original.lower() in (cadence.get("frequency") or "").lower():
            cadence["frequency"] = "2-3 posts per week"
        s["cadence"] = cadence
        s["limitations"] = [*(s.get("limitations") or []),
                            f"The analysis pointed to {original}; this MVP generates LinkedIn {MVP_CONTENT_TYPE}s only, "
                            f"so {MVP_CONTENT_TYPE} is the primary type and {original} is kept as an alternative."]
    s["content_direction"] = cd

    channels = list(s.get("channels") or [])
    linkedin = [c for c in channels if "linkedin" in (c.get("channel") or "").lower()]
    if not linkedin:
        channels.insert(0, {"channel": "LinkedIn", "priority": "primary", "formats": [MVP_CONTENT_TYPE],
                            "rationale": "LinkedIn is the one channel this version generates for. Untested hypothesis.",
                            "grounding": {"basis": "hypothesis", "refs": [], "confidence": "low"}})
    else:
        channels.remove(linkedin[0])
        channels.insert(0, linkedin[0])
    s["channels"] = [{**c, "priority": "primary" if i == 0 else "secondary"} for i, c in enumerate(channels)]
    return s
