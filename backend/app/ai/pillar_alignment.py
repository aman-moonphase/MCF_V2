"""Does a post reflect its selected content pillar? (generation-time check, not the Evaluate phase)

1. Literal: a word of the pillar's name appears in the post (the original check — kept).
2. Substance: otherwise, the post must carry what the pillar is ABOUT, taken from the approved strategy
   pillar and Product Profile, so a grounded paraphrase passes:
   - problem        → the opening frames a problem AND the post covers the approved problem's own terms;
   - value          → the post paraphrases the approved value proposition;
   - features       → the post covers at least two approved features (or the only one);
   - differentiator → the opening carries an approved differentiator;
   - general        → the post overlaps the pillar's description.
   Product name and audience words never count as evidence: every post about the product contains them.
Without pillar details (older callers) only the literal check applies, so nothing becomes more lenient.
"""

import re
from typing import Dict, List, Optional, Set, Tuple

_STOP = {"with", "from", "that", "this", "your", "their", "into", "about", "have", "will", "they", "them", "what",
         "when", "which", "where", "more", "than", "also", "only", "just", "make", "makes", "does", "helps", "help",
         "less", "listed", "profile", "approved", "product", "show", "shows", "their", "every", "each", "like"}
_STEM = 5

# Problem framing in the opening: a pain, a burden, a documented need, a challenge, or a question about it.
_PROBLEM_CUE = re.compile(
    r"\b(?:instead of|how much (?:time|of your)|how many hours|spend(?:ing)? (?:hours|too much)|los(?:e|ing) (?:time|hours)|"
    r"struggl\w*|juggl\w*|wast\w*|chasing|hassle|burden\w*|frustrat\w*|stress\w*|tired of|by hand|manual\w*|"
    r"no one else|fall(?:s|ing)? behind|slip(?:s|ping)?|overwhelm\w*|scatter\w*|pain\w*|"
    r"need\w*|problem\w*|challeng\w*|hurdle\w*|solv\w*)\b", re.I)


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split()).strip()


def stems(text: Optional[str]) -> Set[str]:
    return {w[:_STEM] for w in re.findall(r"[a-z][a-z-]{3,}", (text or "").lower()) if w not in _STOP}


def _covers(phrase: str, text_stems: Set[str], ratio: float = 0.6) -> bool:
    s = stems(phrase)
    return bool(s) and len(s & text_stems) / len(s) >= ratio


def pillar_kind(pillar: Dict, profile: Dict) -> str:
    """Which part of the approved profile a strategy pillar is about: problem | differentiator | value | features | general."""
    name = (pillar.get("name") or "").lower()
    relation = " ".join([pillar.get("relation_to_product") or "", pillar.get("purpose") or ""]).lower()
    problem = _clean(profile.get("problem_solved")).lower().rstrip(".")
    value = _clean(profile.get("value_proposition")).lower().rstrip(".")
    if "problem" in name or (problem and problem in relation):
        return "problem"
    for d in profile.get("differentiators") or []:
        d = _clean(d).lower().rstrip(".")
        if d and (d in relation or (name and name in d)):
            return "differentiator"
    if value and value in relation or any(w in name for w in ("time", "benefit", "value")):
        return "value"
    if "how it works" in name or "feature" in relation or any(
            _clean(f).lower() in relation for f in profile.get("key_features") or [] if f):
        return "features"
    return "general"


def _excluded(profile: Dict) -> Set[str]:
    return stems(" ".join([profile.get("name") or "", profile.get("target_audience") or ""]))


def pillar_alignment(post_text: str, lead_text: str, pillar_name: str, pillar: Optional[Dict] = None,
                     profile: Optional[Dict] = None) -> Tuple[bool, str]:
    """(aligned, how). `lead_text` is the hook plus the first body paragraph."""
    lowered = (post_text or "").lower()
    name_words = [w for w in re.findall(r"[a-z][a-z-]{3,}", (pillar_name or "").lower()) if w not in _STOP]
    if not name_words or any(w[:_STEM] in lowered for w in name_words):
        return True, "literal"
    if not pillar or not profile:
        return False, "no pillar details"

    post_stems, lead_stems = stems(post_text), stems(lead_text)
    excluded = _excluded(profile)
    kind = pillar_kind({**pillar, "name": pillar_name}, profile)
    if kind == "problem":
        problem_terms = stems(profile.get("problem_solved")) - excluded
        overlap = problem_terms & post_stems
        return bool(_PROBLEM_CUE.search(lead_text or "")) and len(overlap) >= 2, "problem"
    if kind == "value":
        return _covers(_clean(profile.get("value_proposition")), post_stems), "value"
    if kind == "features":
        features: List[str] = [f for f in profile.get("key_features") or [] if _clean(f)]
        covered = sum(_covers(f, post_stems) for f in features)
        return covered >= min(2, len(features)) and covered > 0, "features"
    if kind == "differentiator":
        return any(_covers(d, lead_stems) for d in profile.get("differentiators") or [] if _clean(d)), "differentiator"
    description = stems(" ".join([pillar.get("relation_to_product") or "", pillar.get("purpose") or ""])) - excluded
    return len(description & post_stems) >= 2, "general"


def pillar_context(pillar: Optional[Dict], profile: Optional[Dict]) -> Dict:
    """What the validator needs about the pillar and profile (no sources, no competitor data)."""
    p = profile or {}
    return {
        "pillar_detail": {k: (pillar or {}).get(k) for k in ("name", "purpose", "relation_to_product")} if pillar else None,
        "profile_core": {k: p.get(k) for k in ("name", "target_audience", "problem_solved", "value_proposition",
                                               "key_features", "differentiators")} if p else None,
    }


def first_paragraph(body: str) -> str:
    """The opening line of the body (posts use single or double line breaks)."""
    return next((part.strip() for part in re.split(r"\n", body or "") if part.strip()), "")


def lead(hook: str, body: str) -> str:
    return f"{hook or ''}\n{first_paragraph(body)}"
