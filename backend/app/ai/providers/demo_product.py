"""Deterministic Demo Mode for Product Understanding.

Extracts a Product Profile only from what the current project's source text states (labelled
lines such as "Features: ...", "Target users: ...", "Pricing: ...", and the opening sentence).
Anything not stated stays empty, so the workflow asks the owner instead of inventing it.
"""

import re
from typing import Dict, List, Optional

from ..generation_context import get_generation_context
from ..product_schemas import LIST_FIELDS, MAX_QUESTIONS
from .demo_provider import _LABEL_PATTERN, _clean, _parse_source_from_prompt, _sentences, _shorten, _split_items

# label keywords → profile field (a label matches if it contains the keyword)
_LABEL_MAP = [
    ("key_features", ("feature", "capabilit")),
    ("key_benefits", ("benefit",)),
    ("differentiators", ("differentiator", "unique", "usp", "why us")),
    ("use_cases", ("use case",)),
    ("value_proposition", ("value proposition", "tagline", "promise")),
    ("positioning", ("positioning",)),
    ("business_model", ("pricing", "price", "business model", "plans", "revenue model")),
    ("known_competitors", ("competitor", "alternative")),
    ("constraints", ("constraint", "limitation", "requirement", "compliance")),
    ("market_geography", ("market", "geograph", "region", "countr")),
    ("primary_users", ("primary user", "used by")),
    ("target_audience", ("target user", "target audience", "audience", "ideal customer", "customer")),
    ("problem_solved", ("problem", "pain", "challenge")),
    ("category", ("category", "industry")),
    ("description", ("description", "overview", "about")),
    ("name", ("product", "name", "brand")),
]
_PROBLEM_CUES = re.compile(r"\b(hate|struggl\w*|wast\w*|overlook\w*|manual\w*|frustrat\w*|difficult|hard to|pain\w*|tedious|error-prone|miss\w*)\b", re.I)
_URL = re.compile(r"(https?://[^\s,)]+|www\.[^\s,)]+)", re.I)


def _labelled(source: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for sentence in _sentences(source):
        match = _LABEL_PATTERN.match(sentence)
        if not match:
            continue
        label, body = match.group(1).strip().lower(), match.group(2).strip()
        for field, keywords in _LABEL_MAP:
            if any(k in label for k in keywords) and field not in found:
                found[field] = body
                break
    return found


def _opening(source: str) -> tuple[Optional[str], str, str]:
    """(name, description, descriptor) from the first sentence."""
    sentences = _sentences(source)
    if not sentences:
        return None, "", ""
    first = sentences[0]
    label = _LABEL_PATTERN.match(first)
    if label and label.group(1).strip().lower() in ("product", "name", "brand", "product name"):
        first = label.group(2).strip()
    for separator in (" - ", " — ", " – ", ": "):
        if separator in first:
            head, rest = first.split(separator, 1)
            if 1 <= len(head.split()) <= 4 and head[:1].isupper():
                return head.strip(), f"{head.strip()} is {rest.strip()}.", rest.strip()
    return None, f"{first}.", first


def build_demo_profile(prompt: str) -> dict:
    ctx = get_generation_context() or {}
    source = (ctx.get("input_text") or "").strip() or _parse_source_from_prompt(prompt)
    labelled = _labelled(source)
    name, description, descriptor = _opening(source)

    profile: Dict[str, object] = {}
    for field, body in labelled.items():
        profile[field] = _split_items(body) if field in LIST_FIELDS else _shorten(body, 300)

    if name and not profile.get("name"):
        profile["name"] = name
    if isinstance(profile.get("name"), str):
        profile["name"] = re.split(r" - | — | – ", profile["name"])[0].strip()
    if description and not profile.get("description"):
        profile["description"] = _shorten(description, 300)
    if not profile.get("category") and descriptor:
        m = re.match(r"^(?:an?|the)\s+(.+?)\s+(?:for|that|which|to|built|designed|helping)\b", descriptor, re.I)
        if m:
            profile["category"] = _clean(m.group(1))
    if not profile.get("target_audience") and descriptor:
        m = re.search(r"\bfor ([^.,;]{3,100}?)(?=\s+(?:that|which|who|to|with|by|so)\b|[.,;]|$)", descriptor)
        if m:
            profile["target_audience"] = _clean(m.group(1))
    if not profile.get("market_geography") and descriptor:
        m = re.search(r"\bin ((?:[A-Z][a-zA-Z]+)(?: [A-Z][a-zA-Z]+)*)\s*\.?$", descriptor)
        if m:
            profile["market_geography"] = m.group(1)
    if not profile.get("problem_solved"):
        for sentence in _sentences(source)[1:]:
            if _PROBLEM_CUES.search(sentence) and not _LABEL_PATTERN.match(sentence):
                profile["problem_solved"] = _shorten(sentence, 300)
                break
    url = _URL.search(source)
    if url and not profile.get("website_url"):
        profile["website_url"] = url.group(1).rstrip(".")

    # The owner's answers are authoritative for the fields they target.
    for item in ctx.get("clarifications") or []:
        answer = _clean(item.get("answer") or "")
        if not answer:
            continue
        for field in item.get("fields") or []:
            profile[field] = _split_items(answer) if field in LIST_FIELDS else answer
    return profile


_QUESTION_TEMPLATES = {
    "name": ("What is the product called?", "Every later stage refers to the product by name."),
    "target_audience": (
        "Who is the primary customer for {name} — which role, business type, or segment buys it?",
        "Strategy, channels, and competitor research all depend on knowing exactly who buys the product.",
    ),
    "problem_solved": (
        "What specific problem does {name} solve for its users, in their own words?",
        "Content and positioning lead with the problem the audience already feels.",
    ),
    "key_features": (
        "What are the 3–5 core features of {name}?",
        "Features are what content demonstrates and what competitors are compared on.",
    ),
    "value_proposition": (
        "In one sentence, why should a customer choose {name} over how they handle this today?",
        "The value proposition becomes the core message of the promotion strategy.",
    ),
    "category": (
        "Which product category would customers search for when looking for {name}?",
        "The category defines which competitors and channels to analyse.",
    ),
    "description": ("How would you describe {name} in one or two sentences?", "A clear description anchors every later stage."),
    "business_model": (
        "How is {name} sold — free, subscription, one-time purchase, or something else?",
        "Pricing model shapes the call to action and which competitors are comparable.",
    ),
    "differentiators": (
        "What makes {name} different from the alternatives your customers use today?",
        "Differentiators decide which angles the strategy can credibly own.",
    ),
}


def build_demo_questions(prompt: str) -> dict:
    ctx = get_generation_context() or {}
    profile = ctx.get("profile") or {}
    name = profile.get("name") or "the product"
    questions: List[dict] = []
    for field in (ctx.get("askable_fields") or [])[:MAX_QUESTIONS]:
        template = _QUESTION_TEMPLATES.get(field)
        if template:
            questions.append({"question": template[0].format(name=name), "why_it_matters": template[1], "fields": [field]})
    return {"questions": questions}
