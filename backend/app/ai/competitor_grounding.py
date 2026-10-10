"""Deterministic evidence checks applied to every competitor analysis / comparison, whatever the provider.

- References must point at evidence that actually exists; unknown labels are dropped.
- An "observed" finding without a valid reference is downgraded to "inferred".
- Any statement containing a number that does not appear in the evidence (or our own profile) is
  removed — no invented statistics, prices, counts, or schedules.
- Posting cadence is kept only when it is observed and cited.
- Content examples are kept only when their excerpt is a verbatim quote of the cited evidence.
- Empty sections are reported as unknown rather than filled in.
- "Opportunities" that rest only on the evidence NOT mentioning something are moved to the unknowns as
  evidence gaps: absence from the supplied evidence does not show the competitor lacks it.
"""

import re
from typing import Dict, Iterable, List, Tuple

from .competitor_schemas import FINDING_SECTIONS, PERFORMANCE_DATA_NOTE

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ABSENCE = re.compile(
    r"\b(?:does not|doesn't|do not|don't|did not|never) (?:mention|show|reference|state|include|discuss)\b|"
    r"\bnot (?:mentioned|shown|referenced|stated)\b|\bno mention\b|\bsilent (?:on|about)\b", re.I)
# Generic calls to action. A competitor using one is an observed message, but our profile not containing the
# same phrase is not a messaging gap: it is at most an angle to evaluate (a suggestion).
_GENERIC_CTA = re.compile(
    r"\b(?:get started|sign up|start (?:your |a )?(?:free )?trial|free trial|try (?:it |us |\w+ )?(?:for )?free|"
    r"(?:book|request|schedule|get) a demo|learn more|contact (?:us|sales)|join (?:now|today|us|free)|"
    r"download (?:now|the app|it)|buy now|subscribe|register (?:now|today)|start (?:now|today|for free))\b", re.I)
_QUOTE = re.compile(r"\"([^\"]{2,120})\"")
CTA_SUGGESTION_PREFIX = "Messaging angle to evaluate (suggestion, not a fact): "
EVIDENCE_GAP_PREFIX = "Evidence gap (hypothesis to investigate, not a confirmed competitor weakness): "


def normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def has_unsupported_numbers(text: str, corpus: str) -> bool:
    corpus_numbers = set(_NUMBER.findall(corpus))
    return any(n not in corpus_numbers for n in _NUMBER.findall(text or ""))


def clean_findings(findings: Iterable[dict], allowed_refs: set, corpus: str) -> Tuple[List[dict], int]:
    kept, removed = [], 0
    for f in findings or []:
        statement = (f.get("statement") or "").strip()
        if not statement:
            continue
        if has_unsupported_numbers(statement, corpus):
            removed += 1
            continue
        refs = [r for r in dict.fromkeys(f.get("refs") or []) if r in allowed_refs]
        status = f.get("status") if f.get("status") in ("observed", "inferred") else "inferred"
        if status == "observed" and not refs:
            status = "inferred"
        kept.append({"statement": statement, "status": status, "refs": refs})
    return kept, removed


def _coverage(findings: List[dict]) -> str:
    if any(f["status"] == "observed" for f in findings):
        return "observed"
    return "inferred" if findings else "unknown"


def ground_analysis(output: dict, allowed_refs: Iterable[str], corpus: str, evidence_count: int) -> dict:
    allowed = set(allowed_refs)
    corpus_norm = normalise(corpus)
    result: Dict[str, object] = {}
    removed_total = 0
    gaps: List[str] = []
    for section in FINDING_SECTIONS:
        kept, removed = clean_findings(output.get(section), allowed, corpus)
        if section == "posting_cadence":
            kept = [f for f in kept if f["status"] == "observed"]
        if section == "opportunities_for_us":
            gaps = [EVIDENCE_GAP_PREFIX + f["statement"] for f in kept if _ABSENCE.search(f["statement"])]
            kept = [f for f in kept if not _ABSENCE.search(f["statement"])]
        result[section] = kept
        removed_total += removed

    examples = []
    for ex in output.get("content_examples") or []:
        excerpt = (ex.get("excerpt") or "").strip()
        if ex.get("ref") in allowed and excerpt and normalise(excerpt) in corpus_norm:
            examples.append({"description": (ex.get("description") or "").strip(), "ref": ex["ref"], "excerpt": excerpt})
    result["content_examples"] = examples

    coverage = {section: _coverage(result[section]) for section in FINDING_SECTIONS}
    coverage["content_examples"] = "observed" if examples else "unknown"
    # Sections without findings are listed by key in `unknown_sections` (the UI shows them under their own
    # headings); `unknowns` holds only specific unknown items, never section names.
    unknown_sections = [s for s, c in coverage.items() if c == "unknown"]
    unknowns = list(gaps)
    if removed_total:
        unknowns.append(f"{removed_total} generated statement(s) were removed because they contained numbers not found in the evidence.")

    observed_sections = sum(1 for c in coverage.values() if c == "observed")
    confidence = "high" if evidence_count >= 3 and observed_sections >= 5 else "medium" if evidence_count >= 1 and observed_sections >= 2 else "low"

    result.update(
        coverage=coverage,
        unknowns=unknowns,
        unknown_sections=unknown_sections,
        performance_data=PERFORMANCE_DATA_NOTE,
        confidence=confidence,
    )
    return result


def ground_comparison(output: dict, allowed_refs: Iterable[str], corpus: str) -> dict:
    allowed = set(allowed_refs)
    result: Dict[str, object] = {}
    for section in ("similarities", "differences", "messaging_gaps"):
        result[section], _ = clean_findings(output.get(section), allowed, corpus)
    cta_suggestions = []
    for f in [f for f in result["messaging_gaps"] if _GENERIC_CTA.search(f["statement"])]:
        quoted = _QUOTE.findall(f["statement"])
        message = f"\"{quoted[-1]}\"" if quoted else "this call to action"
        cta_suggestions.append({
            "suggestion": f"{CTA_SUGGESTION_PREFIX}consider whether a call to action like {message} suits our offer.",
            "rationale": ("The competitor's evidence uses this generic call to action (observed). Our profile not using the "
                          "same phrase is not a messaging gap, and the evidence says nothing about how well it works."),
            "refs": f["refs"],
        })
    result["messaging_gaps"] = [f for f in result["messaging_gaps"] if not _GENERIC_CTA.search(f["statement"])]
    for section in ("positioning_opportunities", "promotion_patterns_to_investigate"):
        suggestions = []
        for s in output.get(section) or []:
            text = f"{s.get('suggestion', '')} {s.get('rationale', '')}"
            if not (s.get("suggestion") or "").strip() or has_unsupported_numbers(text, corpus):
                continue
            suggestions.append({
                "suggestion": s["suggestion"].strip(),
                "rationale": (s.get("rationale") or "").strip(),
                "refs": [r for r in dict.fromkeys(s.get("refs") or []) if r in allowed],
            })
        result[section] = suggestions
    result["promotion_patterns_to_investigate"] += cta_suggestions
    result["evidence_needed"] = [e.strip() for e in output.get("evidence_needed") or [] if e and e.strip()]
    if "performance" not in " ".join(result["evidence_needed"]).lower():
        result["evidence_needed"].append(
            "Engagement and campaign performance data for competitors (not available from the supplied sources)."
        )
    return result
