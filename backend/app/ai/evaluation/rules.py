"""Deterministic, rule-based evaluator (Demo Mode and default). Not an LLM judgment.

It reuses the generation-time checks instead of re-implementing them:
- validate_post (app/ai/generation_validation.py) — limits, placeholders, JSON, invented figures, other-product and
  competitor names, copied competitor wording, evidence on claims;
- pillar_alignment (app/ai/pillar_alignment.py) — whether the post carries the selected pillar;
- competitor_findings (app/services/generation_service.py, passed in) — what the approved comparison does and does
  not establish.
On top it adds evaluation-only rules: audience/value-proposition coverage, readability, messaging direction, and
competitive superlatives the approved evidence does not support.
"""

import re
from typing import Any, Dict, List, Optional, Set

from ..generation_validation import assemble
from ..pillar_alignment import lead, pillar_alignment, pillar_kind, stems
from .base import DIMENSIONS, EvaluationContext

NAME = "rules-v1"
MODE = "rule-based"
ABOUT = ("Deterministic, rule-based evaluation (Demo Mode): fixed checks against your approved profile, strategy, "
         "evidence and LinkedIn rules. It is not an AI judgment, gives no scores, and does not predict engagement "
         "or performance.")

# Validation issue codes → (dimension, severity). All are confirmed problems.
_ISSUE_MAP = {
    "missing": ("platform_readiness", "high"),
    "over_limit": ("platform_readiness", "high"),
    "placeholder": ("platform_readiness", "high"),
    "json": ("platform_readiness", "high"),
    "alternatives": ("platform_readiness", "low"),
    "unsupported_number": ("factual_grounding", "high"),
    "cross_product": ("factual_grounding", "high"),
    "product_missing": ("factual_grounding", "high"),
    "competitor_named": ("strategy_alignment", "high"),
    "competitor_copy": ("strategy_alignment", "high"),
}
_ISSUE_SUGGESTION = {
    "missing": "Fill in the missing part of the post in Generate Content.",
    "over_limit": "Shorten the body until the post fits the LinkedIn limit.",
    "placeholder": "Replace the placeholder with real, approved information or remove it.",
    "json": "Remove the leaked field names or JSON from the text.",
    "alternatives": "Regenerate or add distinct alternative hooks (optional for publishing).",
    "unsupported_number": "Remove the figure, or add it to the approved profile/sources first so it can be cited.",
    "cross_product": "Remove the other product's name; this post is about this product only.",
    "product_missing": "Name the product at least once.",
    "competitor_named": "Remove the competitor's name; use competitor insights only to choose emphasis.",
    "competitor_copy": "Rewrite the sentence in your own words; it repeats competitor wording.",
}
# Competitive superlatives/comparisons that need evidence the approved comparison does not provide.
_COMPETITIVE = re.compile(
    r"\b(?:unlike (?:other|any|most)\b[^.]*|better than|faster than|cheaper than|easier than|the only\b[^.]*|"
    r"no other\b[^.]*|best(?:-in-class)?\b|#1\b|number one|world'?s first|industry[- ]leading|beats? (?:the|every|all)\b|"
    r"outperform\w*)", re.I)
_STOP_DIRECTION = {"lead", "leads", "differentiate", "with", "supplied", "competitor", "evidence", "does", "mention",
                   "what", "lead with"}


def _finding(type_: str, severity: str, message: str, suggestion: str = "", evidence: Optional[List[dict]] = None,
             excerpt: str = "") -> dict:
    return {"type": type_, "severity": severity, "message": message, "suggestion": suggestion,
            "evidence": evidence or [], "excerpt": excerpt}


def _covers(phrase: str, text_stems: Set[str], ratio: float) -> bool:
    s = stems(phrase)
    return bool(s) and len(s & text_stems) / len(s) >= ratio


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _short(text: str, n: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


_DISCLAIMER_SENTENCE_RE = re.compile(
    r"\b(?:"
    r"this problem statement is based on|"
    r"not a? validated customer[- ]research|"
    r"not a customer quote|"
    r"not a verbatim customer quote|"
    r"(?:intended\s+)?(?:initial\s+)?(?:test\s+)?audience|"
    r"intended audience selection|"
    r"documented product requirement|"
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


def normalize_persona(text: Optional[str]) -> str:
    """Normalize audience persona for evaluation feedback and recommendations.

    Strips:
    - Metadata prefixes ('Primary:', 'Secondary:', 'Segment:', 'Role:', 'Persona:').
    - Role wrappers like 'Decision-Maker (...)', 'Practitioner / End-User (...)'.
    - Internal test instructions ('For this test, prioritize ...').
    - Research disclaimers/caveats ('This is the intended initial test audience...').
    """
    if not text:
        return ""
    # Strip parenthetical caveats
    text = re.sub(r"\s*\([^)]*(?:intended|not\s+a?\s*validated|customer[- ]research|test\s+audience|product\s+requirement)[^)]*\)", "", text, flags=re.I)
    # Strip intra-sentence caveats e.g. "..., not a validated customer-research finding"
    text = re.sub(r"[,;\-—:]\s*(?:this\s+is|not\s+a?\s*validated|intended|documented\s+product).*$", "", text, flags=re.I)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    for s in sentences:
        if not _DISCLAIMER_SENTENCE_RE.search(s):
            cleaned_s = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", s, flags=re.I).strip()
            if cleaned_s:
                kept.append(cleaned_s)
    candidate = kept[0] if kept else (sentences[0] if sentences else text)
    candidate = re.split(r"\b(?:this\s+is\s+(?:the\s+)?(?:intended|our|a)|not\s+a?\s*validated|intended\s+audience|documented\s+product\s+requirement)\b", candidate, flags=re.I)[0].strip()

    # Strip prefixes and wrappers
    for _ in range(3):
        candidate = re.sub(r"^(?:primary|secondary|tertiary|segment|role|persona|target\s*audience|audience):\s*", "", candidate, flags=re.I).strip()
        m = re.match(r"^(?:decision-maker|practitioner(?:\s*/\s*end-user)?|daily user|team lead|budget-conscious evaluator)\s*\((.*?)\)$", candidate, re.I)
        if m:
            candidate = m.group(1).strip()
        candidate = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", candidate, flags=re.I).strip()
        candidate = candidate.rstrip(". ,;—:-").strip()

    candidate = " ".join(candidate.split())
    if not candidate:
        return ""
    return candidate[:1].upper() + candidate[1:]


def _clean_problem(text: Optional[str]) -> str:
    if not text:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = [s for s in sentences if not _DISCLAIMER_SENTENCE_RE.search(s)]
    return " ".join(kept) if kept else text


def _clean_value(text: Optional[str]) -> str:
    if not text:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = [s for s in sentences if not _DISCLAIMER_SENTENCE_RE.search(s)]
    return " ".join(kept) if kept else text


def _strip_disclaimers(text: Optional[str]) -> str:
    """Strip research disclaimers, test instructions, and caveats from notes text."""
    if not text:
        return ""
    text = re.sub(r"\s*\([^)]*(?:intended|not\s+a?\s*validated|customer[- ]research|test\s+audience|product\s+requirement)[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"[,;\-—:]\s*(?:this\s+is|not\s+a?\s*validated|intended|documented\s+product).*$", "", text, flags=re.I)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    for s in sentences:
        if not _DISCLAIMER_SENTENCE_RE.search(s):
            cleaned_s = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", s, flags=re.I).strip()
            if cleaned_s:
                kept.append(cleaned_s)
    res = " ".join(kept) if kept else (sentences[0] if sentences else text)
    res = re.split(r"\b(?:this\s+is\s+(?:the\s+)?(?:intended|our|a)|not\s+a?\s*validated|intended\s+audience|documented\s+product\s+requirement)\b", res, flags=re.I)[0].strip()
    res = re.sub(r"^(?:for this test,?\s*)?prioritize\s+", "", res, flags=re.I).strip()
    # Strip primary / role / persona prefix if it's metadata, while keeping Segment label
    res = re.sub(r"^(?:primary|role|persona|target\s*audience):\s*", "", res, flags=re.I).strip()
    return " ".join(res.split()).strip().rstrip(" .")


class RuleBasedEvaluator:
    name = NAME
    mode = MODE

    def evaluate(self, ctx: EvaluationContext) -> Dict[str, Any]:
        post = ctx.post
        text = assemble(post)
        opening = lead(post.get("hook", ""), post.get("body", ""))
        post_stems = stems(text)
        excluded = stems(" ".join([ctx.product_name or "", ctx.profile.get("target_audience") or ""]))
        found: Dict[str, List[dict]] = {key: [] for key, _ in DIMENSIONS}
        notes: Dict[str, str] = {}

        # ── Validator issues (confirmed problems) ──────────────────────────
        for issue in ctx.validation.get("issues") or []:
            dim, severity = _ISSUE_MAP.get(issue["code"], ("platform_readiness", "medium"))
            found[dim].append(_finding("problem", severity, issue["message"], _ISSUE_SUGGESTION.get(issue["code"], "")))
        if ctx.stale_reasons:
            found["strategy_alignment"].append(_finding(
                "problem", "high", "The post was generated from approved context that has since changed: " + " ".join(ctx.stale_reasons),
                "Regenerate the post in Generate Content so it reflects the current approved profile and strategy."))

        # ── Pillar alignment ───────────────────────────────────────────────
        aligned, how = pillar_alignment(text, opening, ctx.pillar_name, ctx.pillar, ctx.profile)
        kind = pillar_kind({**(ctx.pillar or {}), "name": ctx.pillar_name}, ctx.profile) if ctx.pillar else "unknown"
        notes["pillar_alignment"] = (f"Selected pillar: \"{ctx.pillar_name}\" ({kind}). "
                                     + ("Matched by the pillar's own words." if how == "literal" and aligned else
                                        "Matched by the pillar's substance in the approved context." if aligned else
                                        "Not reflected in the post."))
        if not aligned:
            found["pillar_alignment"].append(_finding(
                "problem", "medium", f"The post does not clearly reflect the selected pillar \"{ctx.pillar_name}\".",
                self._pillar_suggestion(kind, ctx)))
        if not ctx.pillar:
            found["pillar_alignment"].append(_finding(
                "unknown", "low", "The approved strategy pillar for this post could not be found, so only the pillar's name was checked."))

        # ── Factual grounding ──────────────────────────────────────────────
        evidence = ctx.evidence or {}
        cite = lambda refs: [{"ref": r, "description": evidence.get(r, "Not in this post's evidence list")} for r in refs]  # noqa: E731
        supported = 0
        for claim in post.get("claims") or []:
            if claim.get("kind") != "product_fact":
                continue
            refs = claim.get("refs") or []
            grounded = [r for r in refs if r.startswith(("S", "P:"))]
            if not grounded:
                found["factual_grounding"].append(_finding(
                    "problem", "medium", f"Product claim without supporting evidence: \"{_short(claim.get('text', ''))}\".",
                    "Cite an approved profile field or source for it, or remove or soften the claim.", cite(refs)))
                continue
            missing_fields = [r for r in grounded if r.startswith("P:") and not ctx.profile.get(r[2:])]
            if missing_fields:
                found["factual_grounding"].append(_finding(
                    "problem", "medium", f"\"{_short(claim.get('text', ''))}\" cites profile fields that are empty in the approved profile.",
                    "Cite a field that actually holds this information, or remove the claim.", cite(missing_fields)))
                continue
            excerpt_issue = self._excerpt_issue(claim, [r for r in grounded if r.startswith("S:")], ctx, cite)
            if excerpt_issue:
                found["factual_grounding"].append(excerpt_issue)
                if excerpt_issue["type"] == "problem":
                    continue
            supported += 1
        notes["factual_grounding"] = f"{supported} product claim(s) cite approved profile fields or sources."
        if ctx.edited:
            found["factual_grounding"].append(_finding(
                "unknown", "low", "The post was edited by hand; its claims list describes the generated text, so new "
                                  "statements added in the edit are not covered by these checks.",
                "Check any new factual statement against the approved profile before approving."))
        found["factual_grounding"].append(_finding(
            "unknown", "low", "Rule-based checks verify listed claims, figures and names. Statements not listed as "
                              "claims are not fact-checked."))

        # ── Audience & positioning ─────────────────────────────────────────
        target_audience_raw = ctx.strategy.get("primary_audience") or ctx.profile.get("target_audience") or ""
        audience_raw = ctx.audience_persona or target_audience_raw

        has_research_caveat = bool(
            _DISCLAIMER_SENTENCE_RE.search(target_audience_raw)
            or _DISCLAIMER_SENTENCE_RE.search(ctx.audience_persona or "")
        )

        target_audience_clean = _strip_disclaimers(target_audience_raw)
        persona_note_label = _strip_disclaimers(ctx.audience_persona or "")

        # For evaluation feedback (recommendations & findings), fully normalize role prefixes and caveats
        audience = normalize_persona(audience_raw)

        raw_val = ctx.strategy.get("value_proposition") or ctx.profile.get("value_proposition") or ""
        value = _clean_value(raw_val)

        core_audience = audience.split(" who ")[0].strip().rstrip(".")
        first_w = core_audience.split()[0] if core_audience else ""
        if first_w.isupper() and len(first_w) <= 4:
            audience_inline = core_audience
        else:
            audience_inline = (core_audience[:1].lower() + core_audience[1:]) if core_audience else "your audience"

        if audience and not _covers(core_audience, post_stems, 0.5):
            found["audience_positioning"].append(_finding(
                "recommendation", "medium",
                f"The post does not clearly address the target persona: \"{audience}\".",
                f"Speak to {audience_inline} directly, ideally in the hook."
            ))
        elif audience and not _covers(core_audience, stems(opening), 0.5):
            found["audience_positioning"].append(_finding(
                "recommendation", "low",
                f"The target persona (\"{audience}\") is named in the post but not in its opening.",
                f"Mention {audience_inline} in the hook or first line so the right readers stop scrolling."
            ))

        if value and not _covers(value, post_stems, 0.5):
            found["audience_positioning"].append(_finding(
                "recommendation", "medium",
                f"The approved value proposition is not clearly stated: \"{_short(value, 120)}\".",
                "Add one line that states this benefit in your own words."
            ))

        aud_note_parts = []
        if target_audience_clean:
            aud_note_parts.append(f"Approved audience: \"{_short(target_audience_clean, 80)}\".")
        else:
            aud_note_parts.append("No approved audience.")

        if persona_note_label:
            aud_note_parts.append(f"Persona: \"{_short(persona_note_label, 60)}\".")

        if ctx.editorial_tone:
            aud_note_parts.append(f"Tone: {ctx.editorial_tone.capitalize()}.")

        if has_research_caveat:
            aud_note_parts.append("Audience grounding: Documented product requirement (intended test audience; not validated customer research).")
        elif target_audience_clean:
            aud_note_parts.append("Audience grounding: Approved profile audience.")

        notes["audience_positioning"] = " ".join(aud_note_parts)

        # ── Readability ────────────────────────────────────────────────────
        body = post.get("body", "")
        sentences = _sentences(f"{post.get('hook', '')}\n{body}\n{post.get('cta', '')}")
        long_ones = [s for s in sentences if len(s.split()) > 30]
        for s in long_ones[:3]:
            found["readability"].append(_finding("recommendation", "low", f"Long sentence ({len(s.split())} words).",
                                                 "Split it into two shorter sentences.", excerpt=_short(s)))
        paragraphs = [p for p in re.split(r"\n\s*\n|\n", body) if p.strip()]
        for p_ in [p for p in paragraphs if len(p.split()) > 70][:2]:
            found["readability"].append(_finding("recommendation", "low", f"Dense paragraph ({len(p_.split())} words).",
                                                 "Break it into shorter paragraphs; LinkedIn readers skim.", excerpt=_short(p_)))
        if len(body) > 400 and len(paragraphs) < 2:
            found["readability"].append(_finding("recommendation", "medium", "The body is one block of text.",
                                                 "Add line breaks between ideas."))
        if text.count("!") > 3:
            found["readability"].append(_finding("recommendation", "low", f"{text.count('!')} exclamation marks.",
                                                 "Keep one at most; let the content carry the emphasis."))
        shouting = [w for w in re.findall(r"\b[A-Z]{5,}\b", text) if w.upper() != (ctx.product_name or "").upper()]
        if len(shouting) > 2:
            found["readability"].append(_finding("recommendation", "low", "Several words in capitals.",
                                                 "Use normal case; capitals read as shouting.", excerpt=", ".join(shouting[:4])))
        words = len(text.split())
        notes["readability"] = (f"{words} words, {len(sentences)} sentences, {len(paragraphs)} body paragraph(s); "
                                f"average {round(words / max(1, len(sentences)), 1)} words per sentence.")

        # ── Platform readiness ─────────────────────────────────────────────
        policy = ctx.policy
        hook = post.get("hook", "")
        if policy and len(hook) > policy.hook_max_chars:
            found["platform_readiness"].append(_finding(
                "recommendation", "medium", f"Hook is {len(hook)} characters; about {policy.hook_max_chars} show before \"…see more\".",
                "Shorten the hook so the whole idea is visible before the fold."))
        if not post.get("hashtags"):
            found["platform_readiness"].append(_finding("recommendation", "low", "No hashtags.",
                                                        "Add one to three relevant hashtags."))
        cta = post.get("cta", "")
        if cta and len(cta) > 220:
            found["platform_readiness"].append(_finding("recommendation", "low", "The call to action is long.",
                                                        "Make it one short sentence."))
        count = ctx.validation.get("character_count")
        notes["platform_readiness"] = (f"{count:,} / {policy.max_chars:,} characters." if count is not None and policy else "")

        # ── Strategy alignment ─────────────────────────────────────────────
        direction = ctx.strategy.get("messaging_direction") or ""
        direction_stems = stems(direction) - excluded - {w[:5] for w in _STOP_DIRECTION}
        if direction_stems and len(direction_stems & post_stems) / len(direction_stems) < 0.35:
            found["strategy_alignment"].append(_finding(
                "recommendation", "medium", "The post only loosely follows the approved messaging direction.",
                f"Lean on the approved direction: \"{_short(direction, 160)}\"."))
        established = len((ctx.competitor or {}).get("differences") or [])
        for match in list(dict.fromkeys(m.group(0).strip() for m in _COMPETITIVE.finditer(text)))[:3]:
            found["strategy_alignment"].append(_finding(
                "problem", "medium",
                "Competitive claim not established by the approved competitor analysis: \"" + _short(match, 100) + "\".",
                "Remove it or rephrase without comparing to competitors; the approved comparison "
                + ("records only inferred differences, not superiority." if established else "establishes no such advantage."),
                excerpt=_short(match, 100)))
        if ctx.competitor is None:
            found["strategy_alignment"].append(_finding(
                "unknown", "low",
                "Competitor Analysis was approved with limited evidence, so competitive positioning could not be checked "
                "against competitor findings." if ctx.competitor_limited else
                "No approved, current competitor comparison was available, so competitive positioning was not checked against it."))
        notes["strategy_alignment"] = ("Messaging direction: \"" + _short(direction, 120) + "\"." if direction else "No messaging direction.")

        return self._assemble(found, notes)

    @staticmethod
    def _excerpt_issue(claim: dict, excerpt_refs: List[str], ctx: EvaluationContext, cite) -> Optional[dict]:
        """Retrieved excerpts are unverified source text. A cited excerpt must still match its source and actually
        contain the claim; a claim backed only by excerpts (no approved profile field) stays an unknown."""
        if not excerpt_refs:
            return None
        text = _short(claim.get("text", ""))
        for ref in excerpt_refs:
            info = ctx.excerpts.get(ref) or {"status": "missing"}
            if info["status"] != "current":
                return _finding("problem", "medium",
                                f"\"{text}\" cites a source excerpt that has {'changed' if info['status'] == 'changed' else 'been removed'} since the post was generated.",
                                "Regenerate the post, or check the claim against the current source.", cite([ref]))
            claim_terms = stems(claim.get("text", ""))
            if claim_terms and len(claim_terms & stems(info.get("content", ""))) / len(claim_terms) < 0.5:
                return _finding("problem", "medium", f"The cited source excerpt does not clearly contain the claim \"{text}\".",
                                "Cite evidence that states it, or remove or soften the claim.", cite([ref]),
                                excerpt=_short(info.get("content", ""), 160))
        if not any(r.startswith("P:") for r in claim.get("refs") or []):
            return _finding("unknown", "low", f"\"{text}\" is backed only by source text, not by the approved profile.",
                            "Source excerpts are unverified. Confirm the fact, or add it to the approved profile.", cite(excerpt_refs))
        return None

    @staticmethod
    def _pillar_suggestion(kind: str, ctx: EvaluationContext) -> str:
        p = ctx.profile
        if kind == "problem" and p.get("problem_solved"):
            clean_prob = _clean_problem(p["problem_solved"])
            return f"Open with the problem in your audience's terms, from the approved profile: \"{_short(clean_prob, 160)}\"."
        if kind == "value" and p.get("value_proposition"):
            clean_val = _clean_value(p["value_proposition"])
            return f"Make the benefit explicit: \"{_short(clean_val, 160)}\"."
        if kind == "features" and p.get("key_features"):
            return "Explain at least two approved features: " + ", ".join(p["key_features"][:3]) + "."
        if kind == "differentiator" and p.get("differentiators"):
            valid_diffs = [d for d in p["differentiators"] if not _DISCLAIMER_SENTENCE_RE.search(d)]
            diff_text = valid_diffs[0] if valid_diffs else p["differentiators"][0]
            return f"Lead with the differentiator: \"{_short(diff_text, 140)}\"."
        relation = (ctx.pillar or {}).get("relation_to_product") or ""
        return f"Connect the post to what this pillar is about: \"{_short(relation, 140)}\"." if relation else \
            "Connect the post to the selected pillar."

    @staticmethod
    def _assemble(found: Dict[str, List[dict]], notes: Dict[str, str]) -> Dict[str, Any]:
        dimensions = []
        for key, label in DIMENSIONS:
            items = sorted(found[key], key=lambda f: (("problem", "recommendation", "unknown").index(f["type"]),
                                                      ("high", "medium", "low").index(f["severity"])))
            types = {f["type"] for f in items}
            status = "problem" if "problem" in types else "attention" if "recommendation" in types else "pass"
            dimensions.append({"key": key, "label": label, "status": status, "summary": notes.get(key, ""), "findings": items})
        all_items = [f for d in dimensions for f in d["findings"]]
        counts = {
            "problems": sum(f["type"] == "problem" for f in all_items),
            "high_problems": sum(f["type"] == "problem" and f["severity"] == "high" for f in all_items),
            "recommendations": sum(f["type"] == "recommendation" for f in all_items),
            "unknowns": sum(f["type"] == "unknown" for f in all_items),
        }
        if counts["high_problems"]:
            level, label = "not_ready", "Not ready — fix the high-severity problems"
        elif counts["problems"]:
            level, label = "needs_improvement", "Needs improvement"
        elif counts["recommendations"]:
            level, label = "ready_with_recommendations", "Ready for review, with recommendations"
        else:
            level, label = "ready", "Ready for review"
        explanation = (
            "How this was decided: Not ready if any confirmed problem is high severity; Needs improvement if any other "
            "confirmed problem remains; Ready with recommendations if only recommendations remain; otherwise Ready. "
            "Unknowns are listed but never change the result. "
            f"This version: {counts['problems']} problem(s) ({counts['high_problems']} high), "
            f"{counts['recommendations']} recommendation(s), {counts['unknowns']} unknown(s)."
        )
        return {"overall": {"level": level, "label": label, "explanation": explanation}, "dimensions": dimensions,
                "counts": counts, "about": ABOUT}
