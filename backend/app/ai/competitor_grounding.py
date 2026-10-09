"""Deterministic evidence checks applied to every competitor analysis / comparison, whatever the provider.

- References must point at evidence that actually exists; unknown labels are dropped.
- An "observed" finding without a valid reference is downgraded to "inferred".
- Any statement containing a number that does not appear in the evidence (or our own profile) is
  removed — no invented statistics, prices, counts, or schedules.
- Posting cadence is kept only when it is observed and cited.
- Content examples are kept only when their excerpt is a verbatim quote of the cited evidence.
- Empty sections are reported as unknown rather than filled in.
"""

import re
from typing import Dict, Iterable, List, Tuple

from .competitor_schemas import FINDING_SECTIONS, PERFORMANCE_DATA_NOTE, SECTION_LABELS

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


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
    for section in FINDING_SECTIONS:
        kept, removed = clean_findings(output.get(section), allowed, corpus)
        if section == "posting_cadence":
            kept = [f for f in kept if f["status"] == "observed"]
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
    unknowns = [f"{SECTION_LABELS[s]}: not supported by the available evidence" for s, c in coverage.items() if c == "unknown"]
    if removed_total:
        unknowns.append(f"{removed_total} generated statement(s) were removed because they contained numbers not found in the evidence.")

    observed_sections = sum(1 for c in coverage.values() if c == "observed")
    confidence = "high" if evidence_count >= 3 and observed_sections >= 5 else "medium" if evidence_count >= 1 and observed_sections >= 2 else "low"

    result.update(
        coverage=coverage,
        unknowns=unknowns,
        performance_data=PERFORMANCE_DATA_NOTE,
        confidence=confidence,
    )
    return result


def ground_comparison(output: dict, allowed_refs: Iterable[str], corpus: str) -> dict:
    allowed = set(allowed_refs)
    result: Dict[str, object] = {}
    for section in ("similarities", "differences", "messaging_gaps"):
        result[section], _ = clean_findings(output.get(section), allowed, corpus)
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
    result["evidence_needed"] = [e.strip() for e in output.get("evidence_needed") or [] if e and e.strip()]
    if "performance" not in " ".join(result["evidence_needed"]).lower():
        result["evidence_needed"].append(
            "Engagement and campaign performance data for competitors (not available from the supplied sources)."
        )
    return result
