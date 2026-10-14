"""Pillar 1: claim validation regression tests (pure, no database, no AI).

Isolated example posts run through the real generation-time validator and the real rule-based evaluator. They pin
what the checks DO flag (unsupported or empty-evidence claims, invented figures, competitor comparisons and names,
guaranteed outcomes, changed sources) and what they honestly do NOT claim (statements that are not listed as claims
are not fact-checked; hand edits can add uncovered text).
"""
from typing import Dict, List, Optional

from app.ai.evaluation.base import EvaluationContext
from app.ai.evaluation.rules import RuleBasedEvaluator
from app.ai.generation_validation import absolute_claims, validate_post
from app.ai.platform_policy import platform_policy

CORPUS = (
    "LedgerLeaf is a bookkeeping app for freelance designers. Features: GST invoice generation, expense categorisation, "
    "quarterly tax reminders and WhatsApp invoice sharing. Designers finish bookkeeping in minutes. Plans start with a 30 day trial."
)
PROFILE = {
    "name": "LedgerLeaf",
    "key_features": ["GST invoice generation", "expense categorisation", "quarterly tax reminders"],
    "target_audience": "freelance designers",
    "value_proposition": "bookkeeping designers finish in minutes",
    "differentiators": ["WhatsApp invoice sharing"],
    "pricing": None,  # the approved profile has NO pricing information
}
ALLOWED = ["P:key_features", "P:value_proposition", "P:pricing", "P:differentiators", "S1"]
HOOKS = ["Invoices over WhatsApp.", "Bookkeeping for freelance designers.", "Tax reminders that arrive on time."]


def post(body: str, claims: Optional[List[dict]] = None, hook: str = "LedgerLeaf keeps bookkeeping short.", cta: str = "Try LedgerLeaf.") -> Dict:
    return {"hook": hook, "alternative_hooks": HOOKS, "body": body, "cta": cta, "hashtags": ["#LedgerLeaf"],
            "claims": claims or [], "pillar": "Features", "strategy_alignment": "x", "limitations": []}


def claim(text: str, refs: List[str], kind: str = "product_fact") -> Dict:
    return {"text": text, "kind": kind, "refs": refs}


def run(candidate: Dict, corpus: str = CORPUS, competitor_names: Optional[List[str]] = None, excerpts: Optional[Dict] = None,
        edited: bool = False, allowed: Optional[List[str]] = None, competitor=None):
    """(validation report, evaluation result) for one post, exactly as saved posts are checked."""
    meta = {"product_name": "LedgerLeaf", "competitor_names": competitor_names or [], "forbidden_names": [], "pillar": "Features"}
    validation = validate_post(candidate, allowed if allowed is not None else ALLOWED, corpus, meta, platform_policy())
    ctx = EvaluationContext(
        post=validation["post"], version=1, edited=edited, product_name="LedgerLeaf", profile=PROFILE, pillar_name="Features",
        pillar={"name": "Features", "purpose": "Explain what it does", "relation_to_product": "Shows the features"},
        strategy={"primary_audience": "freelance designers", "value_proposition": PROFILE["value_proposition"], "messaging_direction": ""},
        competitor=competitor, validation=validation, evidence={"S1": "Product description", "P:key_features": "Approved profile"},
        policy=platform_policy(), excerpts=excerpts or {})
    return validation, RuleBasedEvaluator().evaluate(ctx)


def findings(result, dimension: str, kind: Optional[str] = None) -> List[dict]:
    dim = next(d for d in result["dimensions"] if d["key"] == dimension)
    return [f for f in dim["findings"] if kind is None or f["type"] == kind]


def all_messages(result) -> str:
    return " | ".join(f["message"] for d in result["dimensions"] for f in d["findings"])


# ─── Supported, partially supported, unsupported ────────────────────────────────────────────────────────

def test_a_fully_supported_statement_has_no_grounding_problem():
    validation, result = run(post("LedgerLeaf creates GST invoices and shares them on WhatsApp.",
                                  [claim("LedgerLeaf creates GST invoices", ["P:key_features", "S1"])]))
    assert validation["unsupported_claims"] == [] and validation["errors"] == []
    assert findings(result, "factual_grounding", "problem") == []
    summary = next(d for d in result["dimensions"] if d["key"] == "factual_grounding")["summary"]
    assert summary.startswith("1 product claim")


def test_a_partly_supported_post_flags_only_the_unsupported_claim():
    unsupported = "LedgerLeaf files your taxes automatically"
    validation, result = run(post(
        "LedgerLeaf creates GST invoices. It also files your taxes automatically.",
        [claim("LedgerLeaf creates GST invoices", ["P:key_features"]), claim(unsupported, [])]))
    assert validation["unsupported_claims"] == [unsupported]
    problems = findings(result, "factual_grounding", "problem")
    assert len(problems) == 1 and unsupported in problems[0]["message"]
    assert result["overall"]["level"] != "ready"


def test_a_capability_claim_citing_an_empty_profile_field_is_a_problem():
    claim_text = "LedgerLeaf starts at a low monthly price"
    _, result = run(post("LedgerLeaf starts at a low monthly price.", [claim(claim_text, ["P:pricing"])]))
    problems = findings(result, "factual_grounding", "problem")
    assert len(problems) == 1 and "empty in the approved profile" in problems[0]["message"]


def test_citing_evidence_that_does_not_exist_leaves_the_claim_unsupported():
    # "S9" is not one of this post's evidence labels, so the citation is dropped and the claim has no support.
    validation, result = run(post("LedgerLeaf connects to every bank.", [claim("LedgerLeaf connects to every bank", ["S9"])]))
    assert validation["unsupported_claims"] == ["LedgerLeaf connects to every bank"]
    assert validation["post"]["claims"][0]["refs"] == []
    assert len(findings(result, "factual_grounding", "problem")) == 1


# ─── Invented figures, competitors, guarantees ──────────────────────────────────────────────────────────

def test_an_invented_statistic_is_a_high_severity_problem_but_a_sourced_number_is_not():
    invented, result = run(post("LedgerLeaf cuts invoicing time by 73% for every designer."))
    assert any(i["code"] == "unsupported_number" for i in invented["issues"])
    problems = findings(result, "factual_grounding", "problem")
    assert any(p["severity"] == "high" and "figure" in p["message"] for p in problems)
    assert result["overall"]["level"] == "not_ready"

    sourced, _ = run(post("LedgerLeaf starts with a 30 day trial."))
    assert not any(i["code"] == "unsupported_number" for i in sourced["issues"])


def test_an_unestablished_competitive_comparison_is_flagged():
    _, result = run(post("LedgerLeaf is better than other invoicing tools and the only app built for designers."))
    flagged = " ".join(f["message"] for f in findings(result, "strategy_alignment", "problem"))
    assert "better than" in flagged and "the only" in flagged.lower()


def test_naming_a_competitor_is_blocked_and_reported():
    validation, result = run(post("Unlike Zoho Books, LedgerLeaf shares invoices on WhatsApp."), competitor_names=["Zoho Books"])
    assert any(i["code"] == "competitor_named" for i in validation["issues"])
    assert any("competitor" in f["message"].lower() for f in findings(result, "strategy_alignment", "problem"))


def test_guaranteed_financial_outcomes_are_flagged_unless_the_approved_context_says_so_itself():
    for text in ("LedgerLeaf is guaranteed to save you money every quarter.", "Risk-free bookkeeping for designers.",
                 "LedgerLeaf will save you thousands in costs."):
        validation, result = run(post(text))
        assert any(i["code"] == "absolute_claim" for i in validation["issues"]), text
        assert "guarantee" in all_messages(result).lower(), text
    assert absolute_claims("Backed by our 30 day money-back guarantee.", "We offer a 30 day money-back guarantee.") == []
    assert absolute_claims("Create GST invoices in minutes.", CORPUS) == []
    assert absolute_claims("Helps you save time on bookkeeping.", CORPUS) == []


# ─── Incomplete, conflicting or changed evidence; honest limits ─────────────────────────────────────────

def test_a_claim_citing_a_source_excerpt_that_changed_or_vanished_is_a_problem():
    ref = "S:abcd1234#0"
    candidate = post("LedgerLeaf creates GST invoices.", [claim("LedgerLeaf creates GST invoices", ["P:key_features", ref])])
    for status in ("changed", "missing"):
        _, result = run(candidate, allowed=ALLOWED + [ref], excerpts={ref: {"status": status, "content": "old text"}})
        assert any("since the post was generated" in p["message"] for p in findings(result, "factual_grounding", "problem")), status


def test_an_excerpt_that_does_not_contain_the_claim_is_a_problem_and_a_source_only_claim_stays_unknown():
    ref = "S:abcd1234#1"
    off_topic = post("LedgerLeaf supports multiple currencies.", [claim("LedgerLeaf supports multiple currencies", [ref])])
    _, result = run(off_topic, allowed=ALLOWED + [ref], excerpts={ref: {"status": "current", "content": "Invoices can be shared on WhatsApp."}})
    assert any("does not clearly contain the claim" in p["message"] for p in findings(result, "factual_grounding", "problem"))

    on_topic = post("LedgerLeaf shares invoices on WhatsApp.", [claim("LedgerLeaf shares invoices on WhatsApp", [ref])])
    _, result = run(on_topic, allowed=ALLOWED + [ref], excerpts={ref: {"status": "current", "content": "Invoices can be shared on WhatsApp by LedgerLeaf."}})
    assert findings(result, "factual_grounding", "problem") == []
    assert any("only by source text" in f["message"] for f in findings(result, "factual_grounding", "unknown"))


def test_the_evaluator_states_its_limits_instead_of_claiming_full_fact_checking():
    _, result = run(post("LedgerLeaf creates GST invoices.", [claim("LedgerLeaf creates GST invoices", ["P:key_features"])]))
    unknowns = " ".join(f["message"] for f in findings(result, "factual_grounding", "unknown"))
    assert "not listed as claims are not fact-checked" in unknowns
    assert "not an AI judgment" in result["about"] and "does not predict engagement" in result["about"]

    _, edited = run(post("LedgerLeaf creates GST invoices."), edited=True)
    assert any("edited by hand" in f["message"] for f in findings(edited, "factual_grounding", "unknown"))


def test_an_unlisted_statement_is_not_fact_checked_and_that_is_stated():
    """The rule-based check verifies LISTED claims, figures, names and guarantee wording. A plain factual statement that is
    simply not in the claims list is not checked - the evaluator says so rather than implying it was verified."""
    unlisted = "LedgerLeaf integrates with every Indian bank."
    validation, result = run(post(unlisted, claims=[]))
    assert validation["unsupported_claims"] == [] and findings(result, "factual_grounding", "problem") == []
    assert any("not fact-checked" in f["message"] for f in findings(result, "factual_grounding", "unknown"))
