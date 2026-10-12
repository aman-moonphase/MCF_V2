"""Deterministic Demo Mode for LinkedIn Social Post generation.

Assembles the post from the CURRENT project's approved data only: the Product Profile (features,
audience, problem, value proposition, differentiators), the selected strategy pillar and messaging
direction, and the differentiator the service chose using competitor evidence. It is not a language
model: it does not research, reason, or follow free-text instructions, and it says so.

The selected pillar decides the angle of the post:
- problem        → leads with the documented burden, then introduces the product as the answer;
- value          → leads with the approved value proposition (the benefit);
- features       → explains the approved features;
- differentiator → leads with the documented differentiator;
- anything else  → a balanced introduction.
Connecting phrases are neutral; every product statement comes from the profile or strategy.
"""

import re
from typing import Dict, List, Optional

from ..generation_context import get_generation_context
from ..pillar_alignment import pillar_kind  # noqa: F401 (shared classifier)

DEMO_LIMITATION = ("Demo mode: this post was assembled deterministically from your approved profile and strategy. "
                   "It is not written by an AI model; edit it freely or connect Claude/OpenAI for real generation.")

# "…, so they spend less time on administrative work and chasing payments." → "administrative work and chasing payments"
_BURDEN = re.compile(r"\b(?:less time (?:on|spent on)|instead of|without having to|rather than|no more)\s+([^.;]+)", re.I)


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split()).strip()


def _sentence(text: Optional[str]) -> str:
    """One sentence: trimmed, capitalised, ending with exactly one full stop (or its own ?/!)."""
    text = _clean(text).rstrip(" .")
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text[-1] in "?!" else f"{text}."


def _inline(text: Optional[str]) -> str:
    """A phrase used mid-sentence: no trailing full stop, and a capitalised common word lower-cased
    ("Independent yoga teachers" → "independent yoga teachers"; "StudioDesk" and acronyms are kept)."""
    text = _clean(text).rstrip(" .")
    first = text.split(" ", 1)[0] if text else ""
    if first[:1].isupper() and first[1:].islower():
        text = first.lower() + text[len(first):]
    return text


def _join(items: List[str]) -> str:
    items = [_inline(i) for i in items if _clean(i)]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _tag(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    return "#" + "".join(w[:1].upper() + w[1:] for w in words[:3]) if words else ""


def build_demo_linkedin_post(prompt: str) -> dict:
    ctx = (get_generation_context() or {}).get("demo_input") or {}
    p: Dict = ctx.get("profile") or {}
    strategy: Dict = ctx.get("strategy") or {}
    pillar: Dict = ctx.get("pillar") or {}
    emphasis: Dict = ctx.get("emphasis") or {}
    source = (ctx.get("source_text") or "").lower()

    name = p.get("name") or ctx.get("product_name") or "Our product"
    audience = _inline(ctx.get("audience_persona") or strategy.get("primary_audience") or p.get("target_audience"))
    tone = (ctx.get("editorial_tone") or "professional").strip().lower()
    problem = _clean(p.get("problem_solved"))
    value = _clean(strategy.get("value_proposition") or p.get("value_proposition"))
    description = _clean(p.get("description"))
    features: List[str] = [_clean(f) for f in p.get("key_features") or [] if _clean(f)]
    differentiators: List[str] = [_clean(d) for d in p.get("differentiators") or [] if _clean(d)]
    lead = _clean(emphasis.get("text")) or (differentiators[0] if differentiators else "")
    kind = pillar_kind(pillar, p)
    burden_match = _BURDEN.search(problem) if problem else None
    burden = _inline(burden_match.group(1)) if burden_match else ""

    claims: List[dict] = []

    def cite(text: str, field: str) -> None:
        refs = [f"P:{field}"] + (["S1"] if text and text.lower().rstrip(".") in source else [])
        claims.append({"text": _sentence(text) if field != "key_features" else text, "kind": "product_fact", "refs": refs})

    paragraphs: List[str] = []
    if kind == "problem" and problem:
        if tone == "bold" and burden:
            hook = _sentence(f"Stop losing your week to {burden}")
        elif tone == "conversational" and burden:
            hook = _sentence(f"Ever wonder how much of your week goes to {burden}?")
        elif tone == "educational" and burden:
            hook = _sentence(f"Here is why so much of your week goes to {burden}")
        else:
            hook = (_sentence(f"How much of your week goes to {burden}?") if burden
                    else _sentence(problem if not problem.lower().startswith(name.lower()) else value or problem))
        framing = f"For {audience}, that is the problem {name} solves." if audience else f"That is the problem {name} solves."
        # The problem statement itself follows, unless it already is the hook.
        paragraphs.append(framing if hook == _sentence(problem) else f"{framing} {_sentence(problem)}")
        cite(problem, "problem_solved")
        if value:
            paragraphs.append(f"The aim is simple: {_inline(value)}.")
            cite(value, "value_proposition")
        if features:
            paragraphs.append(_sentence(f"It brings together {_join(features[:3])}"))
            for f in features[:3]:
                cite(f, "key_features")
    elif kind == "value" and value:
        hook = _sentence(value)
        cite(value, "value_proposition")
        if description:
            paragraphs.append(f"That is what {name} is for. {_sentence(description)}")
            cite(description, "description")
        if features:
            tail = f", so less of your week goes to {burden}" if burden else ""
            paragraphs.append(_sentence(f"{_join(features[:3])[:1].upper()}{_join(features[:3])[1:]} are built in{tail}"))
            for f in features[:3]:
                cite(f, "key_features")
            if burden:
                cite(problem, "problem_solved")
        if audience:
            paragraphs.append(_sentence(f"Made for {audience}"))
    elif kind == "features" and features:
        hook = _sentence(f"Here is how {name} works" + (f" for {audience}" if audience else ""))
        if description:
            paragraphs.append(_sentence(description))
            cite(description, "description")
        paragraphs.append("What it does:\n" + "\n".join(f"→ {f}" for f in features[:5]))
        for f in features[:5]:
            cite(f, "key_features")
        if value:
            paragraphs.append(f"All of it serves one aim: {_inline(value)}.")
            cite(value, "value_proposition")
    elif kind == "differentiator" and lead:
        hook = _sentence(lead)
        cite(lead, emphasis.get("field") or "differentiators")
        paragraphs.append(f"It is one of the things that makes {name} different.")
        if description:
            paragraphs.append(_sentence(description))
            cite(description, "description")
        others = [f for f in features if f.lower() not in lead.lower()][:3]
        if others:
            paragraphs.append(_sentence(f"Alongside it: {_join(others)}"))
            for f in others:
                cite(f, "key_features")
    else:
        kind = "general"
        hook = _sentence(value or problem or description or name)
        if description:
            paragraphs.append(_sentence(description))
            cite(description, "description")
        if features:
            paragraphs.append("What it does:\n" + "\n".join(f"→ {f}" for f in features[:3]))
            for f in features[:3]:
                cite(f, "key_features")
        if lead:
            paragraphs.append(_sentence(f"What makes {name} different is this: {_inline(lead)}"))
            cite(lead, emphasis.get("field") or "differentiators")

    if emphasis.get("competitor_refs") and kind in ("differentiator", "general") and lead:
        claims.append({"text": f"Leads with \"{_inline(lead)}\" because the supplied competitor evidence does not mention it.",
                       "kind": "competitor_context", "refs": emphasis["competitor_refs"]})
    body = "\n\n".join(x for x in paragraphs if x) or _sentence(f"{name} is our product")
    claims.append({"text": hook, "kind": "creative", "refs": []})
    if tone != "professional" or ctx.get("audience_persona"):
        claims.append({"text": f"Delivered in a {tone} editorial tone targeting {audience}.", "kind": "creative", "refs": []})

    candidates = [
        _sentence(value) if value else "",
        _sentence(f"How much of your week goes to {burden}?") if burden else "",
        _sentence(lead) if lead else "",
        _sentence(f"{name} is built for {audience}") if audience else "",
        _sentence(f"Here is how {name} works"),
        _sentence(f"A closer look at {name}"),
    ]
    alternatives: List[str] = []
    for c in candidates:
        if c and c.lower() != hook.lower() and c.lower() not in (a.lower() for a in alternatives):
            alternatives.append(c)
    alternatives = alternatives[:3]

    limitations = [DEMO_LIMITATION]
    if ctx.get("instructions"):
        limitations.append("Demo mode cannot interpret your campaign instructions; they are saved with the draft and "
                           "will be used by a real AI provider.")
    for field, label in (("value_proposition", "value proposition"), ("problem_solved", "problem"), ("key_features", "features")):
        if not p.get(field):
            limitations.append(f"The approved profile has no {label}, so the post does not mention one.")
    limitations += ctx.get("context_limitations") or []

    audience_tag = _tag(audience.split(" who ")[0]) if audience else ""
    hashtags = [t for t in dict.fromkeys([_tag(name), _tag(p.get("category") or ""), audience_tag]) if t]
    alignment = f"Serves the pillar \"{pillar.get('name')}\" ({kind} angle)"
    if tone != "professional":
        alignment += f" with a {tone} tone"
    if audience:
        alignment += f" targeting {audience}"
    if strategy.get("messaging_direction"):
        alignment += f" and follows the messaging direction: {_inline(strategy['messaging_direction'])}"
    if emphasis.get("competitor_refs") and kind in ("differentiator", "general"):
        alignment += f". Emphasises \"{_inline(lead)}\", which supplied competitor evidence does not mention"

    if tone == "conversational":
        cta = _sentence(f"Curious how {name} works for you? Drop a comment or say hi")
    elif tone == "educational":
        cta = _sentence(f"What is your biggest takeaway on this? Share your thoughts below")
    elif tone == "bold":
        cta = _sentence(f"Ready to stop settling? See what {name} can do for your workflow")
    else:
        cta = _sentence(f"Want to see how {name} would work for you? Comment or send us a message")

    return {
        "hook": hook,
        "alternative_hooks": alternatives,
        "body": body,
        "cta": cta,
        "hashtags": hashtags,
        "claims": claims,
        "pillar": pillar.get("name") or "",
        "strategy_alignment": _sentence(alignment),
        "limitations": limitations,
    }
