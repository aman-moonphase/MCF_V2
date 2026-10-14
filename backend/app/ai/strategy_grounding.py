"""Deterministic checks applied to every Promotion Strategy, whatever the provider.

- References must exist (competitor evidence labels from the comparison, or profile fields).
- A competitor-based basis without a valid competitor reference is downgraded to "hypothesis".
- With limited competitor evidence, competitor-based bases become hypotheses and confidence is capped.
- Sentences with figures that appear nowhere in the inputs are removed (no invented statistics,
  engagement numbers, or predicted results). Cadence and roadmap timing are exempt: they are
  recommendations, and cadence is always labelled a hypothesis without performance data.
- Every roadmap item must use the primary content type (the MVP produces ONE type).
- Alternatives are distinct from the primary type and at most two.
"""

import re
from typing import List

from .competitor_grounding import has_unsupported_numbers
from .content_types import format_conflicts
from .persona_normalization import AUDIENCE_CAVEAT_LIMITATION, has_research_caveat, normalize_persona

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_COMPETITOR_BASES = ("competitor_observed", "evidence_inferred")
_ORDER = {"low": 0, "medium": 1, "high": 2}


def _clean_text(text: str, corpus: str, removed: List[str]) -> str:
    kept = []
    for sentence in _SENTENCE.split(text or ""):
        if sentence.strip() and has_unsupported_numbers(sentence, corpus):
            removed.append(sentence.strip())
        elif sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept)


def _clean_list(items: List[str], corpus: str, removed: List[str]) -> List[str]:
    return [t for t in (_clean_text(i, corpus, removed) for i in items or []) if t]


def _ground(g: dict, allowed: set, limited: bool) -> dict:
    refs = [r for r in dict.fromkeys(g.get("refs") or []) if r in allowed]
    basis = g.get("basis") or "hypothesis"
    confidence = g.get("confidence") or "medium"
    competitor_refs = [r for r in refs if not r.startswith("profile:")]
    if basis in _COMPETITOR_BASES and (limited or not competitor_refs):
        basis = "hypothesis"
    if basis == "competitor_observed" and not competitor_refs:
        basis = "hypothesis"
    if basis == "hypothesis" and _ORDER[confidence] > _ORDER["medium"]:
        confidence = "medium"
    if limited and _ORDER[confidence] > _ORDER["medium"]:
        confidence = "medium"
    return {"basis": basis, "refs": refs, "confidence": confidence}


def ground_strategy(output: dict, allowed_refs: List[str], corpus: str, limited: bool) -> dict:
    allowed = set(allowed_refs)
    removed: List[str] = []
    s = {k: v for k, v in output.items()}

    es = dict(s["executive_summary"])
    for key in ("positioning", "main_opportunity", "primary_recommendation"):
        es[key] = _clean_text(es.get(key, ""), corpus, removed)
    es["grounding"] = _ground(es["grounding"], allowed, limited)
    s["executive_summary"] = es

    au = dict(s["audience"])
    raw_primary_aud = au.get("primary_audience", "")
    has_caveat = has_research_caveat(raw_primary_aud) or any(
        "intended initial test audience" in l or "not a validated customer-research" in l
        for l in (s.get("limitations") or [])
    )
    cleaned_primary_aud = normalize_persona(raw_primary_aud) or raw_primary_aud
    au["primary_audience"] = _clean_text(cleaned_primary_aud, corpus, removed)
    for key in ("value_proposition", "messaging_direction"):
        au[key] = _clean_text(au.get(key, ""), corpus, removed)
    for key in ("problems_and_needs", "differentiators"):
        au[key] = _clean_list(au.get(key) or [], corpus, removed)
    au["grounding"] = _ground(au["grounding"], allowed, limited)
    if has_caveat and au["grounding"]["confidence"] == "high":
        au["grounding"]["confidence"] = "medium"
    s["audience"] = au

    def clean_items(items, text_keys, list_keys=()):
        out = []
        for item in items or []:
            item = dict(item)
            for k in text_keys:
                item[k] = _clean_text(item.get(k, ""), corpus, removed)
            for k in list_keys:
                item[k] = _clean_list(item.get(k) or [], corpus, removed)
            item["grounding"] = _ground(item["grounding"], allowed, limited)
            if all(item.get(k) for k in text_keys[:1]):
                out.append(item)
        return out

    s["content_pillars"] = clean_items(s.get("content_pillars"), ("name", "purpose", "relation_to_product"))
    s["channels"] = clean_items(s.get("channels"), ("channel", "rationale"), ("formats",))
    s["measurement"] = clean_items(s.get("measurement"), ("indicator", "what_to_measure", "why"))

    cd = dict(s["content_direction"])
    primary = cd["primary_content_type"]
    cd["alternatives"] = [a for a in dict.fromkeys(cd.get("alternatives") or []) if a != primary][:2]
    cd["reason"] = _clean_text(cd.get("reason", ""), corpus, removed)
    cd["subject_areas"] = _clean_list(cd.get("subject_areas") or [], corpus, removed)
    cd["messaging_angles"] = _clean_list(cd.get("messaging_angles") or [], corpus, removed)
    cd["grounding"] = _ground(cd["grounding"], allowed, limited)
    s["content_direction"] = cd

    cad = dict(s["cadence"])
    cad["is_hypothesis"] = True  # no measured performance data exists in MCF yet
    cad["grounding"] = {**_ground(cad["grounding"], allowed, limited), "basis": "hypothesis"}
    if cad["grounding"]["confidence"] == "high":
        cad["grounding"]["confidence"] = "medium"
    s["cadence"] = cad

    roadmap, adjusted = [], 0
    for item in sorted(s.get("roadmap") or [], key=lambda i: i.get("sequence", 0)):
        item = dict(item)
        for k in ("objective", "topic", "success_evaluation"):
            item[k] = _clean_text(item.get(k, ""), corpus, removed)
        raw_item_aud = item.get("audience") or au["primary_audience"]
        if has_research_caveat(raw_item_aud):
            has_caveat = True
        clean_item_aud = normalize_persona(raw_item_aud) or raw_item_aud
        item["audience"] = _clean_text(clean_item_aud, corpus, removed)
        if not item.get("format") or format_conflicts(primary, item["format"]):
            item["format"] = primary
            adjusted += 1
        item["grounding"] = _ground(item["grounding"], allowed, limited)
        if item["topic"]:
            roadmap.append(item)
    for index, item in enumerate(roadmap, start=1):
        item["sequence"] = index
    s["roadmap"] = roadmap

    limitations = [l.strip() for l in s.get("limitations") or [] if l and l.strip()]
    if limited:
        limitations.insert(0, "Competitor Analysis was approved with limited evidence. Competitor-based recommendations "
                              "are treated as hypotheses and confidence is capped.")
    if has_caveat and AUDIENCE_CAVEAT_LIMITATION not in limitations:
        limitations.append(AUDIENCE_CAVEAT_LIMITATION)
    if adjusted:
        limitations.append(f"Roadmap formats were aligned to the single MVP content type ({primary}).")
    if removed:
        limitations.append("Some generated statements were removed because they contained figures not found in the "
                           "product profile or competitor evidence (no invented statistics or predicted results).")
    limitations.append("No measured performance data exists yet: cadence and targets are recommendations to test, not proven results.")
    s["limitations"] = list(dict.fromkeys(limitations))
    return s
