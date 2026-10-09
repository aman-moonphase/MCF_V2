"""Product Understanding stage: learn a structured Product Profile from the project's own sources."""

import json
import re
from typing import Any, Dict, List

from ..product_schemas import (
    CRITICAL_FIELDS, LIST_FIELDS, MAX_QUESTIONS, PROFILE_FIELDS, SECONDARY_ASKABLE_FIELDS,
    ClarificationQuestionsOutput, ProductProfileDraft, ProductUnderstandingState,
)
from ..prompts import build_stage_prompt, bullet_list
from ..providers.factory import get_configured_provider as get_provider
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure

STAGE = "product-understanding"


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"unknown", "n/a", "not specified", "none", "null"}
    if isinstance(value, list):
        return not any(not is_empty(v) for v in value)
    return False


def clean_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise placeholders like 'unknown' to empty so missing data is never shown as data."""
    cleaned: Dict[str, Any] = {}
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        if field in LIST_FIELDS:
            cleaned[field] = [v.strip() for v in (value or []) if isinstance(v, str) and not is_empty(v)]
        else:
            cleaned[field] = None if is_empty(value) else str(value).strip()
    return cleaned


def merge_profiles(new: Dict[str, Any], current: Dict[str, Any] | None, edited_fields: List[str]) -> Dict[str, Any]:
    """Preserve existing information: user edits always win, and a refresh never blanks a known field."""
    if not current:
        return new
    merged = dict(new)
    for field in PROFILE_FIELDS:
        if field in edited_fields or (is_empty(new.get(field)) and not is_empty(current.get(field))):
            merged[field] = current.get(field)
    return merged


def _context(state: ProductUnderstandingState) -> list:
    grounding = (state.get("grounding_context") or {}).get("text", "")
    clarifications = state.get("clarifications") or []
    answers = "\n".join(f"- Q: {c['question']}\n  A: {c['answer']}" for c in clarifications if c.get("answer"))
    current = state.get("current_profile")
    current_json = json.dumps({f: current.get(f) for f in PROFILE_FIELDS}, ensure_ascii=False, indent=1) if current else None
    return [
        ("Source Material", state.get("input_text")),
        ("Retrieved Source Excerpts (RAG, current project only)", grounding),
        ("Answers from the product owner (authoritative)", answers or None),
        ("Current Product Profile (keep what is still supported)", current_json),
    ]


async def analyze_sources(state: ProductUnderstandingState) -> Dict[str, Any]:
    if not (state.get("input_text") or "").strip():
        return {"error": "No product sources are available for this project. Add a source first."}

    provider = get_provider()
    prompt = build_stage_prompt(
        "Product Source Analysis",
        _context(state),
        "Read the product sources and summarise what they actually say about the product: what it is, who it is "
        "for, the problem, features, benefits, differentiators, market, pricing, and any named alternatives. "
        "Quote facts only from the sources and say explicitly which of these topics the sources do not cover.",
    )
    try:
        return {"intent": await call_text(provider, prompt, state, STAGE)}
    except Exception as e:
        return {"error": f"Failed to analyze product sources: {str(e)}"}


async def build_profile(state: ProductUnderstandingState) -> Dict[str, Any]:
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}

    provider = get_provider()
    prompt = build_stage_prompt(
        "Build Product Profile",
        [*_context(state), ("Source Analysis", state.get("intent"))],
        f"""
Build a structured Product Profile for THIS product only.
- Use only information present in the sources or in the product owner's answers.
- If something is not stated, leave it null (or an empty list). Never guess, and never invent statistics,
  customer numbers, pricing, research, company claims, or performance numbers.
- `known_competitors` lists only competitors or alternatives explicitly named in the sources/answers.
- Keep list items short and concrete (one feature, benefit, or use case per item).
- When the owner's answers fill a field, use them; keep everything from the current profile that is still supported.
{retry_feedback(state)}
""",
    )
    try:
        draft: ProductProfileDraft = await call_structured(provider, prompt, ProductProfileDraft, state, STAGE)
        profile = merge_profiles(clean_profile(draft.model_dump()), state.get("current_profile"), state.get("edited_fields") or [])
        return {"profile": profile, "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to build product profile", e)


def identify_gaps(state: ProductUnderstandingState) -> Dict[str, Any]:
    """Deterministic: which fields are missing, and which of those are worth asking about."""
    profile = state.get("profile") or {}
    missing = [f for f in PROFILE_FIELDS if is_empty(profile.get(f))]
    already_asked = set(state.get("asked_fields") or [])
    critical = [f for f in CRITICAL_FIELDS if f in missing and f not in already_asked]
    askable = critical + [f for f in SECONDARY_ASKABLE_FIELDS if f in missing and f not in already_asked] if critical else []
    return {"missing_fields": missing, "askable_fields": askable}


async def generate_questions(state: ProductUnderstandingState) -> Dict[str, Any]:
    askable = state.get("askable_fields") or []
    if not askable:
        return {"questions": [], "error": None}
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}

    provider = get_provider()
    profile = state.get("profile") or {}
    prompt = build_stage_prompt(
        "Clarification Questions",
        [
            ("Source Material", state.get("input_text")),
            ("Product Profile so far", json.dumps(profile, ensure_ascii=False, indent=1)),
        ],
        f"""
The sources do not cover these profile fields (most important first):
{bullet_list(askable)}

Write at most {MAX_QUESTIONS} clarification questions for the product owner — fewer is better.
- Ask only what materially improves product strategy and competitor analysis.
- Each question targets one or more of the fields above (use those exact field names in `fields`).
- Never ask about anything the sources already answer, and never ask cosmetic questions (brand colours, fonts, logos).
- Make each question specific to this product; offer concrete options from the sources when that helps.
- `why_it_matters` explains in one sentence how the answer will be used.
{retry_feedback(state)}
""",
    )
    try:
        result: ClarificationQuestionsOutput = await call_structured(provider, prompt, ClarificationQuestionsOutput, state, STAGE)
        return {"questions": [q.model_dump() for q in result.questions], "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate clarification questions", e)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def validate_understanding(state: ProductUnderstandingState) -> Dict[str, Any]:
    """Keep only useful questions: valid target fields, not already covered, no duplicates, at most 5."""
    if state.get("error"):
        return state
    profile = state.get("profile")
    if not profile:
        return validation_failure(state, "No product profile was produced")

    askable = set(state.get("askable_fields") or [])
    seen, kept = set(), []
    for q in state.get("questions") or []:
        fields = [f for f in q.get("fields") or [] if f in askable]
        text = (q.get("question") or "").strip()
        key = _normalise(text)
        if not fields or not text or key in seen or not (q.get("why_it_matters") or "").strip():
            continue
        seen.add(key)
        kept.append({"question": text, "why_it_matters": q["why_it_matters"].strip(), "fields": fields})
    return {"questions": kept[:MAX_QUESTIONS]}
