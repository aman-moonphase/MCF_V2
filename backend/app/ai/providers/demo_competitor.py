"""Deterministic Demo Mode for Competitor Analysis.

Works only from the evidence the user supplied for a competitor (fetched pages, notes, description)
and the approved Product Profile. It quotes and classifies what the evidence says; it never invents
companies, research, metrics, or activity. With no evidence, it produces no findings.
"""

import re
from typing import Dict, List

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
_AUDIENCE = re.compile(r"\bfor (?:[\w-]+ ){0,4}(businesses|teams|freelancers|owners|companies|agencies|startups|families|professionals|users|customers|accountants|restaurants|designers|creators|managers|shops|stores|clinics)\b", re.I)
_CADENCE = re.compile(r"\b(daily|every (day|week|month)|weekly|monthly|\d+ (posts?|videos?|episodes?|times) (a|per) (day|week|month))\b", re.I)
_STRENGTH = re.compile(r"\b(only|first|award|trusted|leading|no credit card|free plan|free forever|integrat\w*)\b", re.I)


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
    for item in items:
        label, text = item["label"], item["text"]
        sentences = _sentences(text)
        if sentences and not out["overview"] and label != "N":
            out["overview"].append(_finding(f"{name}: {sentences[0]}", "observed", [label]))
        for s in sentences:
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            if _POSITIONING.search(s) and len(out["positioning"]) < 3:
                out["positioning"].append(_finding(s, "observed", [label]))
            if _AUDIENCE.search(s) and len(out["target_audience"]) < 2:
                out["target_audience"].append(_finding(s, "observed", [label]))
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

    all_text = " ".join(i["text"] for i in items).lower()
    all_labels = [i["label"] for i in items]
    for feature in product.get("key_features") or []:
        words = _keywords(feature)
        needed = max(1, (len(words) + 1) // 2)
        for item in items:
            hit = next((s for s in _sentences(item["text"]) if sum(_matches(w, s) for w in words) >= needed), None)
            if hit:
                out["overlapping_features"].append(_finding(
                    f"Similar to our \"{feature}\": {hit}", "observed", [item["label"]]))
                break
    for diff in (product.get("differentiators") or []) + (product.get("key_features") or []):
        words = _keywords(diff)
        if words and not _mentioned(diff, all_text) and len(out["opportunities_for_us"]) < 4:
            out["opportunities_for_us"].append(_finding(
                f"The supplied evidence for {name} does not mention \"{diff}\", which our product offers.", "inferred", all_labels))
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
