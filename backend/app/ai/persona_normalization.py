"""Persona and audience normalization utilities for MCF.

Normalizes internal planning prefixes, role wrappers, and research caveats
so audiences and personas are represented consistently, readably, and
without leaking internal planning disclaimers into creator-facing text,
while preserving uncertainty disclosures as clear notes or grounding basis.
"""

import re
from typing import Optional

_CAVEAT_SENTENCE_RE = re.compile(
    r"\b(?:"
    r"this problem statement is based on|"
    r"not a? validated customer[- ]research|"
    r"not a customer quote|"
    r"not a verbatim customer quote|"
    r"(?:intended\s+)?(?:initial\s+)?test\s+audience|"
    r"intended\s+audience(?:\s+selection)?|"
    r"documented\s+product\s+requirement|"
    r"internal (?:persona|research|test) (?:metadata|caveat|note)|"
    r"no verified differentiator|"
    r"leave differentiation unknown|"
    r"avoid (?:claiming )?competitive superiority|"
    r"avoid unsupported (?:financial )?claims|"
    r"until competitor research|"
    r"delivered in a [a-z]+ editorial tone|"
    r"for this test,?\s*prioritize"
    r")\b",
    re.I,
)

_PURE_DISCLAIMER_RE = re.compile(
    r"\b(?:"
    r"this problem statement is based on|"
    r"not a? validated customer[- ]research|"
    r"not a customer quote|"
    r"not a verbatim customer quote|"
    r"(?:intended\s+)?(?:initial\s+)?test\s+audience|"
    r"intended\s+audience(?:\s+selection)?|"
    r"documented\s+product\s+requirement|"
    r"internal (?:persona|research|test) (?:metadata|caveat|note)|"
    r"no verified differentiator|"
    r"leave differentiation unknown|"
    r"avoid (?:claiming )?competitive superiority|"
    r"avoid unsupported (?:financial )?claims|"
    r"until competitor research|"
    r"delivered in a [a-z]+ editorial tone"
    r")\b",
    re.I,
)


def has_research_caveat(text: Optional[str]) -> bool:
    """True if text mentions research caveats or initial test audience disclaimers."""
    if not text:
        return False
    return bool(_CAVEAT_SENTENCE_RE.search(text))


def normalize_persona(text: Optional[str]) -> str:
    """Normalize a raw persona or target audience string.

    Strips:
    - Metadata prefixes ('Primary:', 'Secondary:', 'Segment:', 'Role:', 'Persona:', 'Target audience:').
    - Role wrappers like 'Decision-Maker (...)', 'Practitioner / End-User (...)'.
    - Internal test instructions ('For this test, prioritize ...').
    - Research disclaimers/caveats ('This is the intended initial test audience...').
    """
    if not text:
        return ""
    # Strip parenthetical caveats
    text = re.sub(
        r"\s*\([^)]*(?:intended|not\s+a?\s*validated|customer[- ]research|test\s+audience|product\s+requirement)[^)]*\)",
        "",
        text,
        flags=re.I,
    )
    # Strip intra-sentence caveats e.g. "..., not a validated customer-research finding"
    text = re.sub(
        r"[,;\-—:]\s*(?:this\s+is|not\s+a?\s*validated|intended|documented\s+product).*$",
        "",
        text,
        flags=re.I,
    )
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    for s in sentences:
        cleaned_s = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", s, flags=re.I).strip()
        if cleaned_s and not _PURE_DISCLAIMER_RE.search(cleaned_s):
            kept.append(cleaned_s)
    candidate = kept[0] if kept else (sentences[0] if sentences else text)
    candidate = re.split(
        r"\b(?:this\s+is\s+(?:the\s+)?(?:intended|our|a)|not\s+a?\s*validated|intended\s+audience|documented\s+product\s+requirement)\b",
        candidate,
        flags=re.I,
    )[0].strip()

    # Strip prefixes and wrappers
    for _ in range(3):
        candidate = re.sub(
            r"^(?:primary|secondary|tertiary|segment|role|persona|target\s*audience|audience):\s*",
            "",
            candidate,
            flags=re.I,
        ).strip()
        m = re.match(
            r"^(?:decision-maker|practitioner(?:\s*/\s*end-user)?|daily user|team lead|budget-conscious evaluator)\s*\((.*?)\)$",
            candidate,
            re.I,
        )
        if m:
            candidate = m.group(1).strip()
        candidate = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", candidate, flags=re.I).strip()
        candidate = candidate.rstrip(". ,;—:-").strip()

    candidate = " ".join(candidate.split())
    if not candidate:
        return ""
    return candidate[:1].upper() + candidate[1:]


def strip_disclaimers(text: Optional[str]) -> str:
    """Strip research disclaimers, test instructions, and caveats from notes text."""
    if not text:
        return ""
    text = re.sub(
        r"\s*\([^)]*(?:intended|not\s+a?\s*validated|customer[- ]research|test\s+audience|product\s+requirement)[^)]*\)",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"[,;\-—:]\s*(?:this\s+is|not\s+a?\s*validated|intended|documented\s+product).*$",
        "",
        text,
        flags=re.I,
    )
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    for s in sentences:
        cleaned_s = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", s, flags=re.I).strip()
        if cleaned_s and not _PURE_DISCLAIMER_RE.search(cleaned_s):
            kept.append(cleaned_s)
    res = " ".join(kept) if kept else (sentences[0] if sentences else text)
    res = re.split(
        r"\b(?:this\s+is\s+(?:the\s+)?(?:intended|our|a)|not\s+a?\s*validated|intended\s+audience|documented\s+product\s+requirement)\b",
        res,
        flags=re.I,
    )[0].strip()
    res = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", res, flags=re.I).strip()
    res = re.sub(r"^(?:primary|role|persona|target\s*audience):\s*", "", res, flags=re.I).strip()
    return " ".join(res.split()).strip().rstrip(" .")


AUDIENCE_CAVEAT_LIMITATION = (
    "Audience grounding: Target audience is an intended initial test audience / documented product requirement, "
    "not a validated customer-research finding."
)
