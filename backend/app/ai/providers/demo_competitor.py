"""Deterministic Demo Mode for Competitor Analysis.

Works only from the evidence the user supplied for a competitor (fetched pages, notes, description)
and the approved Product Profile. It quotes and classifies what the evidence says; it never invents
companies, research, metrics, or activity. With no evidence, it produces no findings.
"""

import re
from typing import Dict, List

from app.core.text_encoding import has_mojibake

from ..generation_context import get_generation_context
from .demo_provider import _sentences

_STOP = {
    "with", "from", "that", "this", "your", "their", "into", "over", "about", "have", "will", "they", "them",
    "and", "for", "the", "app", "apps", "tool", "tools", "using", "based", "more", "less", "than", "also",
}
_CHANNELS = {
    "LinkedIn": r"\blinkedin\b", "Instagram": r"\binstagram\b", "YouTube": r"\byoutube\b",
    "X (Twitter)": r"\btwitter\b|\bx\.com\b", "Facebook": r"\bfacebook\b", "TikTok": r"\btiktok\b",
    "Email newsletter": r"\bnewsletter", "Blog": r"\bblog\b", "Podcast": r"\bpodcast", "Webinars": r"\bwebinar",
}
_FORMATS = {
    "Blog posts / articles": r"\bblog posts?\b|\barticles?\b", "Case studies": r"\bcase stud", "Webinars": r"\bwebinar",
    "Videos / tutorials": r"\bvideos?\b|\btutorials?\b", "Guides / e-books": r"\be-?books?\b|\bguides?\b",
    "Templates": r"\btemplates?\b", "Newsletters": r"\bnewsletter", "Podcasts": r"\bpodcast",
}
_POSITIONING = re.compile(r"\b(helps?|lets?|makes?|built for|designed for|all-in-one|platform for|the (easiest|simplest|fastest|best|only|smartest))\b", re.I)
# An explicit audience: "we help <group>", "software/platform/built/designed ... for <group>", "the home for
# every <group>", where <group> ends in a customer noun ("yoga teachers and studios", "small businesses").
# A bare "for <group>" is not enough ("an experience for students" names their customers' customers).
# Only the stated phrase is extracted: no demographics, geography or other details are inferred.
_AUDIENCE_NOUN = (r"(?:business(?:es)?|teams?|freelancers?|owners?|compan(?:y|ies)|agenc(?:y|ies)|startups?|famil(?:y|ies)|"
                  r"professionals?|users?|customers?|clients?|accountants?|restaurants?|designers?|creators?|managers?|"
                  r"shops?|stores?|clinics?|teachers?|studios?|instructors?|coach(?:es)?|trainers?|gyms?|schools?|"
                  r"students?|therapists?|practitioners?|salons?|founders?|marketers?|developers?|retailers?|sellers?|educators?)")
_AUDIENCE_GROUP = rf"(?:[a-z][\w-]* ){{0,3}}?{_AUDIENCE_NOUN}(?:,? (?:and|&|or) (?:[a-z][\w-]* ){{0,2}}?{_AUDIENCE_NOUN})?"
_AUDIENCE = re.compile(
    r"\b(?:(?:software|platform|apps?|tools?|solutions?|system|built|designed|made|created|tailored|suitable|perfect|"
    rf"ideal|home) for|helps?|helping)\s+(?:every |all |each |any )?({_AUDIENCE_GROUP})\b", re.I)
_AUDIENCE_LEAD = re.compile(r"^(?:the|our|your|their|a|an|any)\s+", re.I)


def _audience_key(phrase: str) -> str:
    return re.sub(r"(?:es|s)\b", "", phrase.lower())  # "teachers and studios" ~ "teacher and studio"


def _audience_findings(candidates: List[tuple], limit: int = 3) -> List[dict]:
    """One observed finding per distinct audience, most often stated first (singular/plural variants count
    together; the plural wording is kept). A phrase whose words are all covered by a higher-ranked audience
    ("yoga studio" after "yoga teachers and studios") adds nothing and is dropped."""
    best: Dict[str, tuple] = {}
    counts: Dict[str, int] = {}
    for audience, sentence, label in candidates:
        key = _audience_key(audience)
        counts[key] = counts.get(key, 0) + 1
        if key not in best or len(audience) > len(best[key][0]):
            best[key] = (audience, sentence, label)
    kept: List[str] = []
    for key in sorted(best, key=lambda k: -counts[k]):  # stable: ties keep order of first appearance
        if not any(set(key.split()) <= set(k.split()) for k in kept):
            kept.append(key)
    return [_finding(f"Audience: \"{best[k][0]}\" — stated as \"{best[k][1]}\"", "observed", [best[k][2]])
            for k in kept[:limit]]


def _audience(sentence: str):
    """The audience phrase a sentence states explicitly, e.g. "yoga teachers and studios"."""
    if _QUOTED.search(sentence):
        return None  # a customer's testimonial is not the company's stated audience
    m = _AUDIENCE.search(sentence)
    return _AUDIENCE_LEAD.sub("", m.group(1)).strip() if m else None
_CADENCE = re.compile(r"\b(daily|every (day|week|month)|weekly|monthly|\d+ (posts?|videos?|episodes?|times) (a|per) (day|week|month))\b", re.I)
_STRENGTH = re.compile(r"\b(only|first|award|trusted|leading|no credit card|free plan|free forever|integrat\w*)\b", re.I)


# Sentences about selling, pricing or engagement say nothing about what the product can do
# ("promo codes that help you maximise attendance" is not attendance tracking).
_MARKETING = re.compile(
    r"\b(pric\w*|promo\w*|discount\w*|coupons?|vouchers?|memberships?|rates?|offers?|deals?|sign-?ups?|subscri\w*|"
    r"loyalty|referrals?|engag\w*|maximi[sz]\w*|increas\w*|boost\w*|grow\w*|revenue|marketing|campaigns?|testimonials?)\b",
    re.I)
_QUOTED = re.compile(r"^[\"“‘']|[“”]|[\"']\W*$")  # opening/closing quotes: a testimonial, not the company's own copy
# The competitor's own evidence stating a limitation ("not available offline", "requires an internet connection").
_LIMITATION = re.compile(
    r"\b(?:not (?:available|supported|included|possible)|(?:isn't|is not) (?:available|supported|included)|"
    r"(?:doesn't|does not|can't|cannot) (?:support|include|offer|work)|coming soon|"
    r"requires? (?:an? )?(?:internet|online|wi-?fi)|internet connection (?:is )?required|extra (?:cost|charge|fee)|paid add-?on)\b",
    re.I)
_FEATURE_WINDOW = 6  # all matched feature words must sit within this many words of each other


def _feature_support(feature: str, sentence: str):
    """How a sentence relates to one of OUR features: "observed" (it names the same capability),
    "inferred" (most of it, e.g. "class scheduling, bookings" for "Class booking links"), or None.

    A shared word alone is never enough: a two-word feature needs both words, longer ones all but one,
    close together, in a sentence that describes functionality rather than pricing/marketing or a quote.
    """
    # Short terms like "GST" or "CRM" count here: they are often the most specific word of a feature.
    words = list(dict.fromkeys(w for w in re.findall(r"[a-z][a-z-]{2,}", feature.lower()) if w not in _STOP))
    if not words or _MARKETING.search(sentence) or _QUOTED.search(sentence) or has_mojibake(sentence):
        return None
    tokens = re.findall(r"[a-z][a-z-]+", sentence.lower())
    positions = {w: [i for i, t in enumerate(tokens) if t.startswith(w[:5])] for w in words}
    found = [w for w in words if positions[w]]
    if len(found) == len(words):
        status = "observed"
    elif len(words) >= 3 and len(found) == len(words) - 1:
        status = "inferred"
    else:
        return None
    first = [positions[w][0] for w in found]
    if max(first) - min(first) > _FEATURE_WINDOW:
        return None
    return status


def _keywords(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z][a-z-]{3,}", (text or "").lower()) if w not in _STOP]


def _matches(word: str, text: str) -> bool:
    """Stem-prefix match, so 'invoice' matches 'invoices' and 'tracker' matches 'track'."""
    stem = word[:5]
    return any(token.startswith(stem) for token in re.findall(r"[a-z][a-z-]+", text.lower()))


def _mentioned(phrase: str, text: str) -> bool:
    """A phrase counts as mentioned when most of its keywords appear (stem match)."""
    words = _keywords(phrase)
    return bool(words) and sum(_matches(w, text) for w in words) >= max(1, (len(words) + 1) // 2)


def _finding(statement: str, status: str, refs: List[str]) -> dict:
    return {"statement": statement, "status": status, "refs": refs}


def _items(ctx: dict) -> List[dict]:
    return [i for i in ctx.get("items") or [] if (i.get("text") or "").strip()]


def build_demo_competitor_analysis(prompt: str) -> dict:
    ctx = (get_generation_context() or {}).get("demo_input") or {}
    product = ctx.get("product") or {}
    name = (ctx.get("competitor") or {}).get("name") or "This competitor"
    items = _items(ctx)
    out: Dict[str, list] = {k: [] for k in (
        "overview", "positioning", "target_audience", "overlapping_features", "messaging_themes", "promotion_channels",
        "content_formats", "content_examples", "posting_cadence", "strengths", "opportunities_for_us",
    )}
    if not items:
        return out

    seen = set()
    audiences: List[tuple] = []
    for item in items:
        label, text = item["label"], item["text"]
        sentences = [s for s in _sentences(text) if not has_mojibake(s)]  # never quote unrecoverable text
        if sentences and not out["overview"] and label != "N":
            out["overview"].append(_finding(f"{name}: {sentences[0]}", "observed", [label]))
        for s in sentences:
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            if _POSITIONING.search(s) and len(out["positioning"]) < 3:
                out["positioning"].append(_finding(s, "observed", [label]))
            audience = _audience(s)
            if audience:
                audiences.append((audience, s, label))
            if _CADENCE.search(s):
                out["posting_cadence"].append(_finding(s, "observed", [label]))
            if _STRENGTH.search(s) and len(out["strengths"]) < 3:
                out["strengths"].append(_finding(f"Claims: \"{s}\"", "observed", [label]))
            if 4 <= len(s.split()) <= 12 and len(out["messaging_themes"]) < 3 and not _CADENCE.search(s):
                out["messaging_themes"].append(_finding(f"Message used: \"{s}\"", "observed", [label]))

        for channel, pattern in _CHANNELS.items():
            if re.search(pattern, text, re.I) and not any(channel in f["statement"] for f in out["promotion_channels"]):
                out["promotion_channels"].append(_finding(
                    f"The evidence references {channel} (presence only; activity level unknown)", "observed", [label]))
        for fmt, pattern in _FORMATS.items():
            match = next((s for s in sentences if re.search(pattern, s, re.I)), None)
            if match and not any(fmt in f["statement"] for f in out["content_formats"]):
                out["content_formats"].append(_finding(f"{fmt} are referenced in the evidence", "observed", [label]))
                if len(out["content_examples"]) < 3:
                    out["content_examples"].append({"description": f"{fmt} mentioned by {name}", "ref": label, "excerpt": match[:200]})

    out["target_audience"] = _audience_findings(audiences)

    for feature in product.get("key_features") or []:
        best = None
        for item in items:
            for sentence in _sentences(item["text"]):
                status = _feature_support(feature, sentence)
                if status and (best is None or (status == "observed" and best[0] == "inferred")):
                    best = (status, sentence, item["label"])
            if best and best[0] == "observed":
                break
        if best is None:
            continue  # no supporting evidence: the relationship stays unknown (see CompetitorService.analyze)
        status, sentence, label = best
        statement = (f"Similar to our \"{feature}\": {sentence}" if status == "observed"
                     else f"Possibly comparable to our \"{feature}\" (partial match, not confirmed): {sentence}")
        out["overlapping_features"].append(_finding(statement, status, [label]))
    # Opportunities are suggestions motivated by what the evidence SHOWS. Silence about one of our features is
    # not a competitor weakness: those cases are reported as unknowns (CompetitorService._evidence_gaps).
    for item in items:
        for s in _sentences(item["text"]):
            if _LIMITATION.search(s) and not has_mojibake(s) and len(out["opportunities_for_us"]) < 3:
                out["opportunities_for_us"].append(_finding(
                    f"Suggestion: {name}'s own evidence states \"{s}\". If our product handles this differently, "
                    "it may be worth highlighting — verify before using it in messaging.", "inferred", [item["label"]]))
    return out


def build_demo_comparison(prompt: str) -> dict:
    ctx = (get_generation_context() or {}).get("demo_input") or {}
    product = ctx.get("product") or {}
    competitors = ctx.get("competitors") or []
    out = {k: [] for k in ("similarities", "differences", "messaging_gaps", "positioning_opportunities",
                           "promotion_patterns_to_investigate", "evidence_needed")}
    profile_text = " ".join(str(v) for v in product.values() if v).lower()
    all_text = " ".join(i["text"] for c in competitors for i in c.get("items", [])).lower()

    for c in competitors:
        prefix, name, analysis = c["label"], c["name"], c.get("analysis") or {}
        pref = lambda refs: [f"{prefix}:{r}" for r in refs]  # noqa: E731
        for f in analysis.get("overlapping_features") or []:
            out["similarities"].append(_finding(f"{name} — {f['statement']}", f["status"], pref(f["refs"])))
        for f in analysis.get("messaging_themes") or []:
            words = _keywords(f["statement"])
            if words and not any(w in profile_text for w in words):
                out["messaging_gaps"].append(_finding(
                    f"{name} uses a message our profile does not address — {f['statement']}", "observed", pref(f["refs"])))
        for section, label in (("promotion_channels", "promotion channels"), ("content_formats", "content formats"),
                               ("positioning", "positioning")):
            if not analysis.get(section):
                out["evidence_needed"].append(f"{name}: no evidence about {label}.")

    for diff in product.get("differentiators") or []:
        words = _keywords(diff)
        if words and competitors and not _mentioned(diff, all_text):
            out["differences"].append(_finding(
                f"Our differentiator \"{diff}\" is not mentioned in any supplied competitor evidence.", "inferred", []))
            out["positioning_opportunities"].append({
                "suggestion": f"Consider leading with \"{diff}\".",
                "rationale": "None of the supplied competitor evidence mentions it, so it may be distinctive. Verify with more evidence.",
                "refs": [],
            })

    for channel in _CHANNELS:
        users = [c for c in competitors if any(channel in f["statement"] for f in (c.get("analysis") or {}).get("promotion_channels") or [])]
        if users:
            refs = [f"{c['label']}:{r}" for c in users for f in c["analysis"]["promotion_channels"] if channel in f["statement"] for r in f["refs"]]
            out["promotion_patterns_to_investigate"].append({
                "suggestion": f"Look at how {', '.join(c['name'] for c in users)} use {channel}.",
                "rationale": f"Their evidence references {channel}. It shows presence only, not activity or results.",
                "refs": refs,
            })
    return out
