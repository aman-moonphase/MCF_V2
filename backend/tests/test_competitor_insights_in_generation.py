"""Regression (manual StudioDesk test): Generate Content showed "Competitor insights: None recorded" although the
approved comparison held a cited possible overlap, a labelled suggestion and unresolved feature comparisons.
Those findings must reach the context panel and the real-AI prompt with their uncertainty and citations, without
being turned into differences or competitor weaknesses, and without touching saved posts or the analysis.
"""
import hashlib
import json
import re
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.services.generation_service import _competitor_prompt_sections, competitor_findings
from tests.test_generate_content import GOOD_POST, RecordingProvider, gen_url, generate, ready_project

# The StudioDesk/Momoyoga comparison as stored after the earlier fixes (no differences or messaging gaps).
STUDIODESK_COMPARISON = {
    "similarities": [{"statement": 'Momoyoga — Possibly comparable to our "Class booking links" (partial match, not confirmed): '
                                   "All-in-one yoga studio management software for class scheduling, bookings, payments",
                      "status": "inferred", "refs": ["C1:E1"]}],
    "differences": [], "messaging_gaps": [], "positioning_opportunities": [],
    "promotion_patterns_to_investigate": [{
        "suggestion": 'Messaging angle to evaluate (suggestion, not a fact): consider whether a call to action like '
                      '"Get started for free" suits our offer.',
        "rationale": "Generic CTA; not a messaging gap.", "refs": ["C1:E1"]}],
    "evidence_needed": [
        f'Momoyoga: the supplied evidence does not establish whether Momoyoga offers something like our "{f}". This '
        "comparison is unresolved (not evidence that the feature is absent) — add their feature list, help pages or pricing page to settle it."
        for f in ("Automatic payment reminders", "Attendance tracking", "Offline attendance check-in")
    ] + ["Momoyoga: no evidence about promotion channels."],
}
NEGATIVE = re.compile(r"\b(?:lacks?|does not offer|doesn't offer|no support for|missing|weakness|unlike)\b", re.I)


def test_findings_keep_their_groups_labels_and_citations():
    groups = competitor_findings(STUDIODESK_COMPARISON)
    assert groups["differences"] == []
    assert [(s["status"], s["refs"]) for s in groups["similarities"]] == [("inferred", ["C1:E1"])]
    assert "Class booking links" in groups["similarities"][0]["statement"]
    assert groups["suggestions"][0]["suggestion"].startswith("Messaging angle to evaluate (suggestion, not a fact)")
    assert groups["suggestions"][0]["refs"] == ["C1:E1"]
    assert groups["unresolved"] == [{"competitor": "Momoyoga", "feature": f} for f in
                                    ("Automatic payment reminders", "Attendance tracking", "Offline attendance check-in")]


def test_prompt_sections_separate_findings_and_state_the_rules():
    sections = dict(_competitor_prompt_sections(competitor_findings(STUDIODESK_COMPARISON)))
    titles = list(sections)
    assert len(titles) == 4
    assert sections[titles[0]].startswith("None: the evidence establishes no differences or messaging gaps")
    assert "POSSIBLE OVERLAPS (inferred, not confirmed)" in titles[1] and "NOT unique advantages" in titles[1]
    assert "(inferred, unconfirmed)" in sections[titles[1]] and "[C1:E1]" in sections[titles[1]]
    assert "SUGGESTIONS to evaluate (not facts, not proven opportunities" in titles[2] and "[C1:E1]" in sections[titles[2]]
    assert "UNRESOLVED comparisons (unknown)" in titles[3] and "Never say or imply that it lacks them" in titles[3]
    assert sections[titles[3]].splitlines() == ["- Automatic payment reminders", "- Attendance tracking", "- Offline attendance check-in"]


def test_no_finding_becomes_a_difference_or_a_weakness():
    groups = competitor_findings(STUDIODESK_COMPARISON)
    assert groups["differences"] == []  # similarities / suggestions / unknowns are never promoted to differences
    findings_text = json.dumps(groups) + "\n".join(body for _, body in _competitor_prompt_sections(groups))
    assert not NEGATIVE.search(findings_text)
    assert "promotion channels" not in json.dumps(groups["unresolved"])  # only feature comparisons are listed


# ─── Through the API ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_panel_lists_overlap_suggestion_and_unresolved(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)  # LedgerLeaf vs Zoho Books note evidence
    state = (await authenticated_client.get(gen_url(project_id))).json()
    competitor = state["context"]["competitor"]
    assert "competitor_insights" not in state["context"]
    sims = competitor["similarities"]
    assert sims and all(s["status"] == "inferred" and s["refs"] for s in sims)
    assert any("GST invoice generation" in s["statement"] and "partial match, not confirmed" in s["statement"] for s in sims)
    # Differences / gaps are exactly what the approved comparison recorded, with their own status — nothing added.
    for d in competitor["differences"]:
        assert d["section"] in ("differences", "messaging_gaps") and d["status"] in ("observed", "inferred")
        if d["section"] == "differences":
            assert d["status"] == "inferred" and "not mentioned in any supplied competitor evidence" in d["statement"]
    unresolved = {u["feature"] for u in competitor["unresolved"]}
    assert "Expense categorisation" in unresolved and all(u["competitor"] == "Zoho Books" for u in competitor["unresolved"])
    assert "GST invoice generation" not in unresolved  # covered by the (partial) overlap


@pytest.mark.asyncio
async def test_real_ai_prompt_receives_the_findings_with_citations(authenticated_client):
    project_id, _, s = await ready_project(authenticated_client)
    provider = RecordingProvider({**GOOD_POST, "pillar": s["strategy"]["content_pillars"][0]["name"]})
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        await generate(authenticated_client, project_id)
    prompt = provider.prompts[0]
    assert "POSSIBLE OVERLAPS (inferred, not confirmed)" in prompt and "(inferred, unconfirmed)" in prompt
    assert re.search(r"GST invoice generation.*\[C1:E\d\]", prompt)
    assert "UNRESOLVED comparisons (unknown)" in prompt and "- Expense categorisation" in prompt
    assert "never present that feature as something only" in prompt  # rule from the generation instructions
    assert "never say or imply a competitor lacks them" in prompt
    # Demo emphasis is unchanged: the differentiator, cited to competitor evidence only when a difference does.
    emphasis = provider.contexts[0]["demo_input"]["emphasis"]
    assert emphasis["text"] == "WhatsApp invoice sharing" and emphasis["field"] == "differentiators"
    assert emphasis["competitor_refs"] == []  # the recorded difference carries no citation, so none is invented


@pytest.mark.asyncio
async def test_empty_differences_have_a_clear_state(authenticated_client, db_session):
    project_id, product_id, _ = await ready_project(authenticated_client)
    product = await db_session.get(Product, UUID(product_id))
    await db_session.refresh(product)
    stored = dict(product.competitor_comparison)
    product.competitor_comparison = {**stored, "differences": [], "messaging_gaps": []}
    await db_session.commit()
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["context"]["competitor"]["differences"] == []
    provider = RecordingProvider({**GOOD_POST, "pillar": "x"})
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        await authenticated_client.post(gen_url(project_id), json={})
    assert "None: the evidence establishes no differences or messaging gaps. Do not claim any." in provider.prompts[0]


@pytest.mark.asyncio
async def test_reading_context_never_changes_saved_posts_or_the_analysis(authenticated_client, db_session):
    project_id, product_id, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    # Evaluate & Improve precedes approval.
    assert (await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": 1})).status_code == 200
    assert (await authenticated_client.post(f"{gen_url(project_id)}/approve", json={"version": 1})).status_code == 200

    def fingerprint(row, product):
        return hashlib.sha256(json.dumps([row.status, row.version, row.approved_version, row.content, row.validation,
                                          row.context_snapshot, product.competitor_comparison, product.competitor_version,
                                          product.competitor_approved_version], sort_keys=True, default=str).encode()).hexdigest()

    async def snapshot():
        from tests.conftest import TestingSessionLocal
        async with TestingSessionLocal() as fresh:
            row = (await fresh.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalar_one()
            product = await fresh.get(Product, UUID(product_id))
            return fingerprint(row, product)

    before = await snapshot()
    for _ in range(2):
        state = (await authenticated_client.get(gen_url(project_id))).json()
        assert state["status"] == "approved" and state["context"]["competitor"]["similarities"]
    assert await snapshot() == before
