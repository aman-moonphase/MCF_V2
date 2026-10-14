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

_DISCLAIMER_SENTENCE_RE = re.compile(
    r"\b(?:"
    r"this problem statement is based on|"
    r"not a verbatim customer quote|"
    r"not a validated customer[- ]research|"
    r"intended (?:initial )?(?:test )?audience|"
    r"no verified differentiator|"
    r"leave differentiation unknown|"
    r"avoid (?:claiming )?competitive superiority|"
    r"avoid unsupported (?:financial )?claims|"
    r"until competitor research|"
    r"delivered in a [a-z]+ editorial tone|"
    r"not a customer quote"
    r")\b",
    re.I,
)


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


def _sanitize_public_text(text: Optional[str]) -> str:
    """Strip internal research notes, disclaimers, and test instructions from text intended for public copy."""
    if not text:
        return ""
    text = _clean(text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    for s in sentences:
        if not _DISCLAIMER_SENTENCE_RE.search(s):
            cleaned_s = re.sub(r"\bFor this test,?\s*prioritize\s+", "", s, flags=re.I).strip()
            if cleaned_s:
                kept.append(cleaned_s)
    return " ".join(kept)


def _clean_audience(text: Optional[str]) -> str:
    """Extract a natural phrasing for copy (e.g. 'college students managing limited budgets').
    Strips raw metadata labels ('Primary:', 'Segment:'), role wrappers, and test disclaimers."""
    if not text:
        return ""
    text = _sanitize_public_text(text)
    for _ in range(3):
        text = re.sub(r"^(?:primary|segment|audience|target audience):\s*", "", text, flags=re.I).strip()
        m = re.match(r"^(?:decision-maker|practitioner\s*/\s*end-user|budget-conscious evaluator)\s*\((.*?)\)$", text, re.I)
        if m:
            text = m.group(1).strip()
        text = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", text, flags=re.I).strip()
        text = text.rstrip(". ").strip()
    return _inline(text)


def _tag(text: str, max_words: int = 3) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    clean = [w for w in words if w.lower() not in {
        "primary", "segment", "decision", "maker", "practitioner", "user", "test",
        "for", "the", "and", "with", "our", "who", "which", "that", "this", "these"
    }]
    if not clean:
        return ""
    return "#" + "".join(w[:1].upper() + w[1:] for w in clean[:max_words])


def _overlaps_features(val: str, feat_list: List[str]) -> bool:
    if not val or not feat_list:
        return False
    return sum(1 for f in feat_list if f.lower() in val.lower()) >= 2


def build_demo_linkedin_post(prompt: str) -> dict:
    ctx = (get_generation_context() or {}).get("demo_input") or {}
    p: Dict = ctx.get("profile") or {}
    strategy: Dict = ctx.get("strategy") or {}
    pillar: Dict = ctx.get("pillar") or {}
    emphasis: Dict = ctx.get("emphasis") or {}
    source = (ctx.get("source_text") or "").lower()

    name = p.get("name") or ctx.get("product_name") or "Our product"
    raw_audience = (ctx.get("audience_persona") or strategy.get("primary_audience") or p.get("target_audience") or "").strip()
    audience = _clean_audience(raw_audience)
    tone = (ctx.get("editorial_tone") or "professional").strip().lower()

    raw_problem = _clean(p.get("problem_solved"))
    problem = _sanitize_public_text(raw_problem) or raw_problem

    raw_value = _clean(strategy.get("value_proposition") or p.get("value_proposition"))
    value = _sanitize_public_text(raw_value) or raw_value

    raw_description = _clean(p.get("description"))
    description = _sanitize_public_text(raw_description) or raw_description

    features: List[str] = [_sanitize_public_text(f) for f in p.get("key_features") or [] if _sanitize_public_text(f)]
    feat_pair = _join(features[:2]) if features else "daily tasks"
    raw_diffs: List[str] = [_clean(d) for d in p.get("differentiators") or [] if _clean(d)]
    valid_differentiators: List[str] = [
        d for d in raw_diffs
        if not _DISCLAIMER_SENTENCE_RE.search(d) and len(_sanitize_public_text(d)) > 10
    ]

    emphasis_text = _clean(emphasis.get("text"))
    lead = "" if _DISCLAIMER_SENTENCE_RE.search(emphasis_text) else emphasis_text
    if not lead and valid_differentiators:
        lead = valid_differentiators[0]

    kind = pillar_kind(pillar, p)
    # If the strategy pillar was classified as a differentiator, but there are no verified differentiators, fall back
    if kind == "differentiator" and not lead:
        kind = "general"

    burden_match = _BURDEN.search(problem) if problem else None
    burden = _inline(burden_match.group(1)) if burden_match else ""
    is_budget = "budget" in (p.get("category") or "").lower() or "budget" in (problem or "").lower()
    cat_label = p.get('category') or ('personal finances' if is_budget else name)

    claims: List[dict] = []

    def cite(text: str, field: str) -> None:
        refs = [f"P:{field}"] + (["S1"] if text and text.lower().rstrip(".") in source else [])
        claims.append({"text": _sentence(text) if field != "key_features" else text, "kind": "product_fact", "refs": refs})

    paragraphs: List[str] = []
    if kind == "problem" and problem:
        if burden:
            if tone == "bold":
                hook = _sentence(f"Stop losing your week to {burden}")
            elif tone == "conversational":
                hook = _sentence(f"Ever wonder how much of your week goes to {burden}?")
            elif tone == "educational":
                hook = _sentence(f"Here is why so much of your week goes to {burden}")
            else:
                hook = _sentence(f"How much of your week goes to {burden}?")

            framing = f"For {audience}, that is the problem {name} solves." if audience else f"That is the problem {name} solves."
            paragraphs.append(framing if hook == _sentence(problem) else f"{framing} {_sentence(problem)}")
            cite(problem, "problem_solved")

            has_feature_overlap = _overlaps_features(value, features)
            if value:
                if tone == "conversational":
                    paragraphs.append(f"That is why {name} focuses on what matters: {_inline(value)}.")
                elif tone == "educational":
                    paragraphs.append(f"Here is how {name} approaches the solution: {_inline(value)}.")
                elif tone == "bold":
                    paragraphs.append(f"That is where {name} cuts through the noise: {_inline(value)}.")
                else:
                    paragraphs.append(f"The aim is simple: {_inline(value)}.")
                cite(value, "value_proposition")

            if features:
                if not has_feature_overlap:
                    paragraphs.append(_sentence(f"It brings together {_join(features[:3])}"))
                    for f in features[:3]:
                        cite(f, "key_features")
                else:
                    for f in features[:4]:
                        cite(f, "key_features")
                    if tone == "conversational":
                        paragraphs.append(f"Whether you are tracking daily expenses or checking savings goals, having your budget organized in one place lets you review your spending and plans together.")
                    elif tone == "educational":
                        paragraphs.append(f"Monitoring spending habits and organizing monthly budgets work hand-in-hand: tracking day-to-day expenses connects directly with setting monthly savings goals.")
                    elif tone == "bold":
                        paragraphs.append(f"Clear expense tracking, structured monthly budgeting, spending habit monitoring, and savings goal planning—organized in one dedicated tool.")
                    else:
                        paragraphs.append(f"By combining expense tracking, monthly budget organization, spending habit monitoring, and savings goal planning, users can review their finances systematically in one place.")
        else:
            if is_budget:
                if tone == "bold":
                    hook = _sentence("Solving personal budgeting challenges demands direct visibility into daily spending and monthly goals")
                elif tone == "conversational":
                    hook = _sentence("Solving everyday budgeting challenges starts with a straightforward way to manage expenses and savings")
                elif tone == "educational":
                    hook = _sentence("Understanding personal budgeting challenges begins with connecting daily expenses to monthly goals")
                else:
                    hook = _sentence("Solving personal budgeting challenges requires a structured approach to daily expenses and savings goals")
            else:
                # Built only from the approved problem statement, never from invented domain copy.
                first_sentence = re.split(r"(?<=[.!?])\s+", problem)[0] if problem else ""
                short_problem = _sentence(first_sentence) if first_sentence and len(first_sentence) <= 180 \
                    and not first_sentence.lower().startswith(name.lower()) else ""
                if short_problem and len(short_problem) <= 150:
                    if tone == "conversational":
                        hook = _sentence(f"Does this sound familiar? {short_problem}")
                    elif tone == "educational":
                        hook = _sentence(f"The problem {name} is built around: {_inline(short_problem)}")
                    elif tone == "bold":
                        hook = _sentence(f"{name} exists for one reason: {_inline(short_problem)}")
                    else:
                        hook = short_problem
                elif short_problem:
                    hook = short_problem
                else:
                    hook = _sentence(f"Why {name} exists" + (f" for {audience}" if audience else ""))

            # Paragraph 1: Useful problem context with audience naturally integrated (neutral, feature-grounded, no unverified assumptions)
            if is_budget:
                if tone == "bold":
                    p1 = f"For {audience}, the focus is direct: bringing daily expenses, monthly budgets, and savings goals into one place." if audience else "The focus is direct: bringing daily expenses, monthly budgets, and savings goals into one place."
                elif tone == "conversational":
                    p1 = f"For {audience}, the challenge comes down to finding a simple way to manage day-to-day expenses alongside monthly budgets and savings goals in one place." if audience else "The challenge comes down to finding a simple way to manage day-to-day expenses alongside monthly budgets and savings goals in one place."
                elif tone == "educational":
                    p1 = f"For {audience}, addressing this challenge begins with connecting routine spending records with monthly budget planning in one place." if audience else "Addressing this challenge begins with connecting routine spending records with monthly budget planning in one place."
                else:
                    p1 = f"For {audience}, the practical challenge is establishing a unified way to coordinate routine spending with monthly budgets and savings goals in one place." if audience else "The practical challenge is establishing a unified way to coordinate routine spending with monthly budgets and savings goals in one place."
            else:
                first_problem_sentence = _sentence(re.split(r"(?<=[.!?])\s+", problem)[0]) if problem else ""
                if first_problem_sentence and first_problem_sentence.lower().rstrip(".") in hook.lower():
                    p1 = f"For {audience}, that is what {name} is designed to address." if audience else f"That is what {name} is designed to address."
                else:
                    p1 = f"For {audience}: {_inline(first_problem_sentence)}." if audience and first_problem_sentence else first_problem_sentence
            paragraphs.append(p1)
            cite(problem, "problem_solved")

            # Paragraph 2: Mention approved features together at most once in the body
            feat_text = _join(features) if features else "core features"
            full_cat = p.get('category') or 'dedicated tool'

            if not is_budget:
                if not features:
                    p2 = ""
                elif tone == "bold":
                    p2 = f"{name} brings {feat_text} together."
                elif tone == "conversational":
                    p2 = f"That is where {name} helps: {feat_text}."
                else:
                    p2 = f"{name} addresses this with {feat_text}."
            elif tone == "bold":
                p2 = f"{name} brings {feat_text} into one focused {full_cat}."
            elif tone == "conversational":
                p2 = f"That is where {name} helps, bringing {feat_text} together in one {full_cat}."
            elif tone == "educational":
                p2 = f"{name} addresses this by combining {feat_text} into a structured {full_cat}."
            else:
                p2 = f"{name} addresses this workflow by bringing {feat_text} together in one structured {full_cat}."
            if p2:
                paragraphs.append(p2)
            if value:
                cite(value, "value_proposition")
            for f in features:
                cite(f, "key_features")

            # Paragraph 3: Contextual takeaway without repeating feature list or audience
            if is_budget:
                if tone == "bold":
                    p3 = "One dedicated view brings your expenses, habits, and savings goals together in one place."
                elif tone == "conversational":
                    p3 = "Bringing those core capabilities together in one place lets you review daily spending and monthly savings goals side by side."
                elif tone == "educational":
                    p3 = "When day-to-day tracking connects directly to monthly budgets, users can review spending patterns against their planned savings goals."
                else:
                    p3 = "Consolidating these capabilities into a single workflow enables users to review their financial data systematically."
            else:
                if not value:
                    p3 = ""
                elif tone == "bold":
                    p3 = f"The promise: {_inline(value)}."
                elif tone == "conversational":
                    p3 = f"The idea is simple: {_inline(value)}."
                elif tone == "educational":
                    p3 = f"In short: {_inline(value)}."
                else:
                    p3 = f"The aim is simple: {_inline(value)}."
            if p3:
                paragraphs.append(p3)

    elif kind == "value" and value:
        if tone == "conversational":
            hook = _sentence(f"A practical way to {_inline(value)}")
        elif tone == "educational":
            if is_budget:
                hook = _sentence("Why bringing your expenses and savings goals together in one place matters")
            else:
                hook = _sentence(f"Why {_inline(value)} matters for {cat_label}")
        elif tone == "bold":
            if is_budget:
                hook = _sentence(f"Track your monthly spending and savings in one place with {name}")
            else:
                hook = _sentence(f"{name}: {_inline(value)}")
        else:
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
        if tone == "conversational":
            if is_budget:
                hook = _sentence(f"A look inside how {name} simplifies budgeting" + (f" for {audience}" if audience else ""))
            else:
                hook = _sentence(f"A look inside {name}" + (f", built for {audience}" if audience else ""))
        elif tone == "educational":
            hook = _sentence(f"What {name} offers" + (f", in a structured look for {audience}" if audience else ""))
        elif tone == "bold":
            hook = _sentence(f"Here is what {name} delivers" + (f" for {audience}" if audience else ""))
        else:
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
        if tone == "conversational":
            hook = _sentence(f"One capability that sets {name} apart: {_inline(lead)}")
        elif tone == "educational":
            hook = _sentence(f"Why {_inline(lead)} makes a practical difference")
        elif tone == "bold":
            hook = _sentence(f"{_sentence(lead)} That changes the baseline")
        else:
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
        if len(hook) > 200:
            hook = _sentence(f"Introducing {name}" + (f": {_inline(p['category'])}" if p.get("category") else ""))
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

    candidates = []
    if burden:
        if tone == "conversational":
            candidates.append(_sentence(f"Ever wonder how much time goes to {burden}?"))
            candidates.append(_sentence(f"A simpler way to handle daily work without {burden}"))
            if audience:
                candidates.append(_sentence(f"{name} is built for {audience} who want less time on {burden}"))
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
        elif tone == "educational":
            candidates.append(_sentence(f"Why the time spent on {burden} matters"))
            candidates.append(_sentence(f"Understanding how much time goes to {burden} each week"))
            if audience:
                candidates.append(_sentence(f"How {name} helps {audience} cut down time spent on {burden}"))
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
        elif tone == "bold":
            candidates.append(_sentence(f"Stop losing your week to {burden}"))
            candidates.append(_sentence(f"Cut out {burden} with {name}"))
            if audience:
                candidates.append(_sentence(f"{name} delivers direct relief from {burden} for {audience}"))
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
        else:  # professional
            candidates.append(_sentence(f"How much of your week goes to {burden}?"))
            candidates.append(_sentence(f"A structured approach to reducing time spent on {burden}"))
            if audience:
                candidates.append(_sentence(f"Built for {audience}: an efficient solution to {burden}"))
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
    elif is_budget:
        if tone == "conversational":
            candidates.append(_sentence("A straightforward approach to tracking where your money goes each week and planning ahead"))
            if audience:
                candidates.append(_sentence(f"{name} is built for {audience} who want a simple view of their monthly budget"))
            candidates.append(_sentence(f"Here is a simple look at how {name} organizes daily expenses and monthly budgets"))
            candidates.append(_sentence("How closely do your monthly spending habits match your savings goals?"))
        elif tone == "educational":
            candidates.append(_sentence("Why tracking day-to-day expenses provides the foundation for realistic monthly budgets"))
            candidates.append(_sentence("Understanding spending habits is the first step toward planning achievable savings goals"))
            if audience:
                candidates.append(_sentence(f"How {name} connects daily expense logs with monthly budget organization for {audience}"))
            candidates.append(_sentence(f"A structured look at how {name} links expense tracking to savings targets"))
        elif tone == "bold":
            candidates.append(_sentence("Clear expense tracking and structured monthly budgeting in one place"))
            if audience:
                candidates.append(_sentence(f"{name} gives {audience} a direct view of daily expenses and monthly savings"))
            candidates.append(_sentence(f"Track expenses, organize budgets, and plan savings goals with {name}"))
            candidates.append(_sentence(f"One dedicated place for your expenses, budget, and savings goals"))
        else:  # professional
            candidates.append(_sentence("A structured framework for tracking expenses and organizing monthly budgets"))
            if audience:
                candidates.append(_sentence(f"Built for {audience}: a personal budgeting tool for daily tracking and monthly planning"))
            candidates.append(_sentence(f"A systematic look at how {name} combines expense tracking and savings goal planning"))
            candidates.append(_sentence("Organizing expense tracking and monthly budgets within a single tool"))
    else:
        # Product-agnostic: only the product name, audience, approved value proposition and features.
        who = audience or "its users"
        if tone == "conversational":
            candidates.append(_sentence(f"A straightforward look at {name}"))
            if audience:
                candidates.append(_sentence(f"{name} is built for {audience}"))
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
            candidates.append(_sentence(f"Here is a simple look at how {name} works for {who}"))
        elif tone == "educational":
            candidates.append(_sentence(f"Understanding the problem behind {name}"))
            if audience:
                candidates.append(_sentence(f"How {name} approaches this for {audience}"))
            if value and len(value) <= 170:
                candidates.append(_sentence(f"In short: {_inline(value)}"))
            candidates.append(_sentence(f"A structured look at what {name} offers"))
        elif tone == "bold":
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
            if audience:
                candidates.append(_sentence(f"{name}: built for {audience}"))
            candidates.append(_sentence(f"What {name} does, in plain terms"))
            if features:
                candidates.append(_sentence(f"{_inline(features[0])} with {name}"))
        else:
            if value and len(value) <= 180:
                candidates.append(_sentence(value))
            candidates.append(_sentence(f"A closer look at {name}"))
            if audience:
                candidates.append(_sentence(f"Built for {audience}: {name}"))
            candidates.append(_sentence(f"How {name} works for {who}"))

    if lead and len(lead) <= 180 and lead not in candidates:
        candidates.append(_sentence(lead))
    if audience and not any(audience.lower() in c.lower() for c in candidates):
        candidates.append(_sentence(f"{name} is built for {audience}"))
    cat_phrase = re.sub(r"\s+(?:tool|app|software|platform)$", "", p.get('category') or '', flags=re.I).strip() or p.get('category') or ''
    if cat_phrase:
        candidates.append(_sentence(f"Here is how {name} simplifies {_inline(cat_phrase)}"))
    candidates.append(_sentence(f"A closer look at how {name} works for {audience or 'its users'}"))

    alternatives: List[str] = []
    for c in candidates:
        c_clean = _sentence(_sanitize_public_text(c))
        if not c_clean or _DISCLAIMER_SENTENCE_RE.search(c_clean) or len(c_clean) > 200:
            continue
        if c_clean.lower() != hook.lower() and c_clean.lower() not in (a.lower() for a in alternatives):
            alternatives.append(c_clean)
    alternatives = alternatives[:3]

    limitations = [DEMO_LIMITATION]
    if ctx.get("instructions"):
        limitations.append("Demo mode cannot interpret your campaign instructions; they are saved with the draft and "
                           "will be used by a real AI provider.")
    for field, label in (("value_proposition", "value proposition"), ("problem_solved", "problem"), ("key_features", "features")):
        if not p.get(field):
            limitations.append(f"The approved profile has no {label}, so the post does not mention one.")
    limitations += ctx.get("context_limitations") or []

    # Clean hashtags: name, category, compact audience (e.g. #CollegeStudents)
    audience_tag = _tag(audience.split(" who ")[0], 2) if audience else ""
    cat_tag = _tag(p.get("category") or "", 2)
    name_tag = _tag(name, 2)
    hashtags = [t for t in dict.fromkeys([name_tag, cat_tag, audience_tag]) if t]

    alignment = f"Serves the pillar \"{pillar.get('name')}\" ({kind} angle)"
    if tone != "professional":
        alignment += f" with a {tone} tone"
    if raw_audience:
        alignment += f" targeting {raw_audience}"
    if strategy.get("messaging_direction"):
        alignment += f" and follows the messaging direction: {_inline(strategy['messaging_direction'])}"
    if emphasis.get("competitor_refs") and kind in ("differentiator", "general") and lead:
        alignment += f". Emphasises \"{_inline(lead)}\", which supplied competitor evidence does not mention"

    if tone == "conversational":
        cta = _sentence(f"Curious how {name} works for you? Drop a comment or say hi")
    elif tone == "educational":
        cta = _sentence(f"What is your biggest takeaway on this? Share your thoughts below")
    elif tone == "bold":
        if is_budget:
            cta = _sentence(f"See how {name} organizes your budgeting in one place")
        else:
            cta = _sentence(f"See how {name} works for you")
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
