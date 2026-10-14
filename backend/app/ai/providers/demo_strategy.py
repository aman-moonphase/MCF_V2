"""Deterministic Demo Mode for Promotion Strategy.

Built only from the current Product's approved Product Profile and its competitor analyses /
comparison. Recommendations that do not follow from that data are labelled hypotheses. No
competitors, research, statistics, prices, or performance figures are introduced.
"""

import re
from typing import Dict, List, Optional

from ..content_types import PROFILES
from ..generation_context import get_generation_context
from ..persona_normalization import AUDIENCE_CAVEAT_LIMITATION, has_research_caveat, normalize_persona

_CADENCE = {
    "Social Post": "2-3 posts per week",
    "Carousel": "1-2 carousels per week",
    "Article": "1 article every week or two",
    "Newsletter": "1 issue every two weeks",
    "Video": "1 short video per week",
    "Image": "2-3 image posts per week",
}


def _g(basis: str, refs: Optional[List[str]] = None, confidence: str = "medium") -> dict:
    return {"basis": basis, "refs": refs or [], "confidence": confidence}


def _profile_refs(profile: dict, *fields: str) -> List[str]:
    return [f"profile:{f}" for f in fields if profile.get(f)]


def _heading(differentiator: str, features: List[str]) -> str:
    """A concise, never mid-word heading for a differentiator: the product feature it names ("Offline attendance
    check-in"), else its opening clause. The full text stays in the pillar description."""
    text = differentiator.strip().rstrip(".")
    for feature in sorted(features, key=len, reverse=True):
        if feature and feature.lower() in text.lower():
            return feature
    clause = re.split(r"\s+(?:helps?|lets?|allows?|so|which|that|because|to)\s+|[,;:\u2014\u2013]|\s-\s", text, maxsplit=1)[0]
    if len(clause) <= 60:
        return clause
    return clause[:60].rsplit(" ", 1)[0]


def _weekly_plan(cadence: str):
    """For a cadence like "2-3 posts per week": ("1-2", "posts", "2-3 posts"), or None when the
    cadence is one item per week or less. The roadmap lists one main post per week; the rest follow its pillar."""
    m = re.match(r"^(\d+)(?:-(\d+))?\s+(?:[a-z]+\s+)?([a-z]+)\s+per week", cadence.strip(), re.I)
    if not m:
        return None
    low, high, unit = int(m.group(1)), int(m.group(2) or m.group(1)), m.group(3)
    if high <= 1:
        return None
    extra_low, extra_high = low - 1, high - 1
    if extra_low == extra_high:
        extra = str(extra_high)
    elif extra_low <= 0:
        extra = f"up to {extra_high}"
    else:
        extra = f"{extra_low}-{extra_high}"
    noun = unit if extra_high > 1 else unit.rstrip("s")
    return extra, noun, (f"{low}-{high}" if low != high else str(low)) + f" {unit}"


def _competitor_channels(competitors: List[dict]) -> Dict[str, List[str]]:
    """channel name → prefixed evidence refs, from analysed promotion_channels findings."""
    found: Dict[str, List[str]] = {}
    for c in competitors:
        for f in (c.get("analysis") or {}).get("promotion_channels") or []:
            for platform in ("LinkedIn", "Instagram", "YouTube", "X (Twitter)", "Facebook", "TikTok", "Email newsletter", "Blog"):
                if platform.lower().split(" ")[0] in f["statement"].lower():
                    found.setdefault(platform, []).extend(f"{c['label']}:{r}" for r in f["refs"])
    return found


def build_demo_strategy(prompt: str) -> dict:
    ctx = (get_generation_context() or {}).get("demo_input") or {}
    p = ctx.get("product") or {}
    comparison = ctx.get("comparison") or {}
    competitors = ctx.get("competitors") or []
    limited = bool(ctx.get("limited"))

    name = p.get("name") or "the product"
    raw_audience = p.get("target_audience") or "the target audience described in the profile"
    audience = normalize_persona(raw_audience) or raw_audience
    has_caveat = has_research_caveat(raw_audience)
    features = p.get("key_features") or []
    diffs = p.get("differentiators") or []
    problem = p.get("problem_solved")
    value = p.get("value_proposition") or p.get("description") or f"What {name} offers"

    differences = comparison.get("differences") or []
    opportunities = comparison.get("positioning_opportunities") or []
    gaps = comparison.get("messaging_gaps") or []
    # An inference from "not mentioned in any supplied evidence" is drawn from all of that evidence.
    all_refs = [f"{c['label']}:{r}" for c in competitors for r in ((c.get("analysis") or {}).get("references") or {})]
    # The service passes the one type the MVP can generate; without it the demo picks by feature count.
    content_type = ctx.get("mvp_content_type") or ("Carousel" if len(features) >= 4 else "Social Post")
    platforms = list(PROFILES[content_type].default_platforms)
    observed_channels = {} if limited else _competitor_channels(competitors)

    # Executive summary
    if opportunities and not limited:
        opportunity = opportunities[0]["suggestion"]
        opp_grounding = _g("evidence_inferred", [r for f in differences for r in f["refs"]] or opportunities[0]["refs"] or all_refs)
    elif diffs and p.get("value_proposition"):
        opportunity = (f"Lead with \"{p['value_proposition'].rstrip('.')}\" and use {_heading(diffs[0], features)} as the "
                       "differentiator that supports it.")
        opp_grounding = _g("product_profile", _profile_refs(p, "value_proposition", "differentiators"))
    elif diffs:
        opportunity = f"Use {_heading(diffs[0], features)} to differentiate {name}."
        opp_grounding = _g("product_profile", _profile_refs(p, "differentiators"))
    else:
        opportunity = f"Build awareness of {name} with {audience}."
        opp_grounding = _g("hypothesis", confidence="low")

    lead = diffs[0] if diffs else (features[0] if features else value)
    lead_heading = _heading(lead, features)
    # Balanced pillars, in roadmap order: the problem, the time-saving benefit (value proposition), the features,
    # then the differentiator(s). Headings are concise; full profile text is kept in relation_to_product.
    pillars, objectives = [], []
    if problem:
        pillars.append({"name": "The problem we solve", "purpose": "Show the audience we understand their situation.",
                        "relation_to_product": problem, "grounding": _g("product_profile", _profile_refs(p, "problem_solved"))})
        objectives.append("Introduce the product and the problem")
    if p.get("value_proposition"):
        # Only claim a TIME benefit when the approved value proposition is about time; otherwise name it neutrally.
        benefit_name = ("The time it gives back"
                        if re.search(r"\b(?:time|faster|quick\w*|minutes?|hours?|speed\w*|save[sd]?|effortless\w*)\b", p["value_proposition"], re.I)
                        else "The benefit it delivers")
        pillars.append({"name": benefit_name, "purpose": f"Show the benefit: {p['value_proposition']}",
                        "relation_to_product": f"The approved value proposition: {p['value_proposition']}",
                        "grounding": _g("product_profile", _profile_refs(p, "value_proposition"))})
        objectives.append("Show the core benefit")
    if features:
        pillars.append({"name": "How it works", "purpose": "Demonstrate concrete features.",
                        "relation_to_product": "; ".join(features[:4]), "grounding": _g("product_profile", _profile_refs(p, "key_features"))})
        objectives.append("Show how it works")
    for d in diffs[:2]:
        not_mentioned = any(d.lower() in f["statement"].lower() for f in differences)
        pillars.append({
            "name": _heading(d, features), "purpose": f"Own a differentiator of {name}.",
            "relation_to_product": f"{d.rstrip('.')}. Listed as a differentiator in the profile."
                                   + (" Supplied competitor evidence does not mention it." if not_mentioned and not limited else ""),
            "grounding": _g("evidence_inferred", all_refs, "medium") if not_mentioned and not limited
            else _g("product_profile", _profile_refs(p, "differentiators")),
        })
        objectives.append("Establish the main differentiator")
    if gaps and not limited:
        objectives.append("Answer what competitors talk about")
        pillars.append({"name": "Answering competitor messages", "purpose": "Address themes competitors use that our messaging does not yet cover.",
                        "relation_to_product": gaps[0]["statement"], "grounding": _g("competitor_observed", gaps[0]["refs"])})
    if not pillars:
        objectives.append("Introduce the product")
        pillars.append({"name": f"Introducing {name}", "purpose": "Explain what the product is.",
                        "relation_to_product": value, "grounding": _g("hypothesis", confidence="low")})

    channels = []
    for i, platform in enumerate(platforms[:2]):
        refs = observed_channels.get(platform, [])
        channels.append({
            "channel": platform, "priority": "primary" if i == 0 else "secondary",
            "rationale": (f"Supports the {content_type.lower()} format. Competitor evidence references {platform} "
                          "(presence only — no performance data)." if refs
                          else f"Supports the {content_type.lower()} format for reaching {audience}. Untested hypothesis."),
            "formats": [content_type],
            "grounding": _g("competitor_observed", refs) if refs else _g("hypothesis", confidence="low"),
        })
    for platform, refs in observed_channels.items():
        if platform not in platforms[:2] and len(channels) < 4:
            channels.append({"channel": platform, "priority": "secondary",
                             "rationale": f"Competitor evidence references {platform}; worth investigating before investing.",
                             "formats": [], "grounding": _g("competitor_observed", refs, "low")})

    angles = ([f"Lead with: {p['value_proposition']}"] if p.get("value_proposition") else [])
    angles += ([f"Answer the problem: {problem}"] if problem else [])
    angles += [f"Differentiate with: {d}" for d in diffs[:1]] or ([f"Lead with: {lead}"] if not angles else [])
    cadence = _CADENCE[content_type]
    roadmap_topics = [pl["name"] for pl in pillars][:4]
    weekly = _weekly_plan(cadence)
    roadmap = [
        {"sequence": i + 1, "timing": f"Week {i + 1} · main post" if weekly else f"Week {i + 1}",
         "objective": objectives[i], "topic": topic,
         "channel": channels[0]["channel"], "format": content_type, "audience": audience,
         "success_evaluation": "Compare saves, comments and profile/site visits with the previous step to see which theme resonates.",
         "grounding": _g("hypothesis", confidence="low")}
        for i, topic in enumerate(roadmap_topics)
    ]

    limitations = []
    if limited:
        limitations.append("Competitor evidence was limited, so channel and differentiation choices rely on the Product Profile.")
    if has_caveat:
        limitations.append(AUDIENCE_CAVEAT_LIMITATION)
    limitations += comparison.get("evidence_needed") or []
    missing = [f for f in ("value_proposition", "problem_solved", "target_audience") if not p.get(f)]
    if missing:
        limitations.append("The Product Profile is missing: " + ", ".join(m.replace("_", " ") for m in missing) + ".")

    return {
        "executive_summary": {
            "positioning": f"{name}: {value}",
            "main_opportunity": opportunity,
            "primary_recommendation": (
                f"Start with {content_type} content on {channels[0]['channel']}, led by \"{p['value_proposition'].rstrip('.')}\" and "
                f"rotating through the pillars: {', '.join(pl['name'] for pl in pillars)}."
                if p.get("value_proposition") else
                f"Start with {content_type} content on {channels[0]['channel']}, built around \"{lead_heading}\"."),
            "grounding": opp_grounding,
        },
        "audience": {
            "primary_audience": audience,
            "problems_and_needs": [problem] if problem else [],
            "value_proposition": value,
            "differentiators": diffs,
            "messaging_direction": (
                (f"Lead with \"{p['value_proposition'].rstrip('.')}\". " if p.get("value_proposition") else "")
                + (f"Differentiate with what supplied competitor evidence does not mention: {differences[0]['statement']}"
                   if differences and not limited else f"Differentiate with: {lead}")),
            "grounding": _g("evidence_inferred", [r for f in differences for r in f["refs"]] or all_refs) if differences and not limited
            else _g("product_profile" if p.get("target_audience") else "hypothesis", _profile_refs(p, "target_audience", "value_proposition"), "medium" if has_caveat else "high" if p.get("target_audience") else "low"),
        },
        "content_pillars": pillars,
        "channels": channels,
        "content_direction": {
            "primary_content_type": content_type,
            "reason": ("The profile lists several distinct features, which suit a multi-slide format." if content_type == "Carousel"
                       else "A text-first post is the fastest format to test messaging with a small feature set."),
            "alternatives": [t for t in ("Article", "Carousel", "Social Post") if t != content_type][:2],
            "subject_areas": roadmap_topics,
            "messaging_angles": angles,
            "grounding": _g("product_profile", _profile_refs(p, "key_features")),
        },
        "cadence": {
            # The horizon matches the roadmap actually planned (one week per pillar, at most four).
            "frequency": cadence, "planning_horizon": f"First {len(roadmap)} week{'s' if len(roadmap) != 1 else ''}",
            "rationale": "A modest starting cadence to learn which themes resonate. No performance data exists yet."
                         + (f" Each roadmap week lists its main, pillar-focused post; the other {weekly[0]} {weekly[1]} that "
                            f"week stay on the same pillar (for example a closer look at one feature, or a question to the "
                            f"audience), for {weekly[2]} per week in total." if weekly else ""),
            "is_hypothesis": True, "grounding": _g("hypothesis", confidence="low"),
        },
        "roadmap": roadmap,
        "measurement": [
            {"indicator": "Reach", "what_to_measure": "Impressions and unique viewers per post",
             "why": "Shows whether the content is reaching the audience at all.", "grounding": _g("hypothesis")},
            {"indicator": "Engagement quality", "what_to_measure": "Saves, comments and shares per post, by pillar",
             "why": "Shows which themes resonate, which guides the next roadmap steps.", "grounding": _g("hypothesis")},
            {"indicator": "Interest", "what_to_measure": "Profile visits and link clicks to the product page",
             "why": "Connects content to product interest.", "grounding": _g("hypothesis")},
            {"indicator": "Baseline", "what_to_measure": "Record results of the first weeks before setting targets",
             "why": "There is no historical data yet, so targets would be guesses.", "grounding": _g("hypothesis")},
        ],
        "limitations": limitations,
    }
