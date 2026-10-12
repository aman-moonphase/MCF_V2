"""Generate Content (LinkedIn Social Post): approved context reaches the generator, prerequisites block,
unsupported types are rejected, drafts persist and version, isolation, and legacy compatibility.

Runs in Demo Mode or with a recording fake provider — no API key, no paid calls.
"""
import json
import uuid
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.ai.generation_validation import assemble
from app.ai.providers.demo_generation import DEMO_LIMITATION
from app.core.config import settings
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from tests.test_promotion_strategy import approve_competitors, make_product, other_client  # noqa: F401
from tests.test_promotion_strategy import approve as approve_strategy
from tests.test_promotion_strategy import generate as generate_strategy


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


def gen_url(project_id):
    return f"/api/projects/{project_id}/generated-content"


async def approve_type(client, project_id, content_type="Social Post"):
    res = await client.patch(f"/api/projects/{project_id}/stages/content-type",
                             json={"status": "Completed", "data": {"approved_type": content_type}})
    assert res.status_code == 200, res.text
    return res.json()


async def ready_project(client, with_evidence=True, content_type="Social Post"):
    project_id, product_id = await make_product(client)
    await approve_competitors(client, project_id, product_id, with_evidence=with_evidence)
    s = await generate_strategy(client, product_id)
    assert (await approve_strategy(client, project_id, product_id, s["version"])).status_code == 200
    await approve_type(client, project_id, content_type)
    return project_id, product_id, s


async def generate(client, project_id, **body):
    res = await client.post(gen_url(project_id), json=body)
    assert res.status_code == 200, res.text
    return res.json()


def post_text(state) -> str:
    return assemble(state["draft"]["content"])


class RecordingProvider:
    """Captures the prompt and demo context; returns a fixed, valid post."""

    def __init__(self, post: dict):
        self.post, self.prompts, self.contexts = post, [], []

    async def generate_structured(self, prompt, schema):
        from app.ai.generation_context import get_generation_context
        self.prompts.append(prompt)
        self.contexts.append(dict(get_generation_context()))
        return schema.model_validate(self.post)

    async def generate_text(self, prompt):
        raise AssertionError("not used")


GOOD_POST = {
    "hook": "Bookkeeping that LedgerLeaf users finish in minutes.",
    "alternative_hooks": ["Invoices on WhatsApp.", "Built for solo designers.", "Tax reminders that arrive on time."],
    "body": "LedgerLeaf creates GST invoices and shares them on WhatsApp.",
    "cta": "Try LedgerLeaf for your studio.",
    "hashtags": ["#LedgerLeaf", "#Freelance"],
    "claims": [{"text": "LedgerLeaf creates GST invoices", "kind": "product_fact", "refs": ["P:key_features", "S1"]}],
    "pillar": "x", "strategy_alignment": "Follows the messaging direction.", "limitations": [],
}


# ─── Workflow + prerequisites ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_content_stage_follows_content_type(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    stages = [s["stage_type"] for s in res.json()["stages"]]
    assert stages[stages.index("content-type") + 1] == "generate-content"
    assert "storyboard" not in stages and "final-script" not in stages


@pytest.mark.asyncio
async def test_prerequisites_block_generation(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    bare = res.json()["id"]
    state = (await authenticated_client.get(gen_url(bare))).json()
    assert state["status"] == "blocked" and state["can_generate"] is False and "Link a product" in state["blocking_problem"]
    assert (await authenticated_client.post(gen_url(bare), json={})).status_code == 409

    project_id, product_id = await make_product(authenticated_client)
    blocked = await authenticated_client.post(gen_url(project_id), json={})
    assert blocked.status_code == 409 and "Competitor Analysis" in blocked.json()["detail"]

    await approve_competitors(authenticated_client, project_id, product_id)
    blocked = await authenticated_client.post(gen_url(project_id), json={})
    assert blocked.status_code == 409 and "Promotion Strategy" in blocked.json()["detail"]

    s = await generate_strategy(authenticated_client, product_id)
    assert (await authenticated_client.post(gen_url(project_id), json={})).status_code == 409  # strategy still a draft
    await approve_strategy(authenticated_client, project_id, product_id, s["version"])
    blocked = await authenticated_client.post(gen_url(project_id), json={})
    assert blocked.status_code == 409 and "Content Type" in blocked.json()["detail"]

    await approve_type(authenticated_client, project_id)
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["status"] == "not_generated" and state["can_generate"] is True
    assert all(p["met"] for p in state["prerequisites"])


@pytest.mark.asyncio
async def test_strategy_steers_to_the_mvp_type(authenticated_client):
    _, _, s = await ready_project(authenticated_client)
    cd = s["strategy"]["content_direction"]
    assert cd["primary_content_type"] == "Social Post"
    assert s["strategy"]["channels"][0]["channel"] == "LinkedIn" and s["strategy"]["channels"][0]["priority"] == "primary"


@pytest.mark.asyncio
async def test_unsupported_type_is_rejected_not_redirected(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client, content_type="Carousel")
    stage = (await authenticated_client.get(f"/api/projects/{project_id}/stages/content-type")).json()
    assert stage["data"]["generation_supported"] is False and stage["data"]["overrides_strategy"] is True

    res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 422 and "Carousel" in res.json()["detail"] and "Social Post" in res.json()["detail"]
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["can_generate"] is False and state["draft"] is None
    assert next(p for p in state["prerequisites"] if p["key"] == "supported")["met"] is False


@pytest.mark.asyncio
async def test_stale_or_changed_context_blocks_and_flags(authenticated_client):
    project_id, product_id, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)

    # Editing the profile revokes its approval: the draft is flagged stale and regeneration is blocked.
    res = await authenticated_client.patch(f"/api/products/{product_id}/profile", json={"profile": {"target_audience": "Wedding photographers"}})
    assert res.status_code == 200, res.text
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["stale"] is True and any("Product Profile" in r for r in state["stale_reasons"])
    assert (await authenticated_client.post(gen_url(project_id), json={})).status_code == 409


# ─── The approved context reaches the generator ─────────────────────────────

@pytest.mark.asyncio
async def test_demo_post_is_built_from_the_approved_context(authenticated_client):
    project_id, product_id, s = await ready_project(authenticated_client)
    state = await generate(authenticated_client, project_id)
    draft = state["draft"]
    post, text = draft["content"], post_text(state)

    assert state["status"] == "draft" and draft["version"] == 1 and draft["is_demo"] is True and draft["provider"] == "demo"
    assert DEMO_LIMITATION in post["limitations"]
    assert "LedgerLeaf" in text
    assert "GST invoice generation" in text  # a real feature from the profile
    assert len(post["alternative_hooks"]) == 3 and post["hook"] not in post["alternative_hooks"]
    assert post["pillar"] == s["strategy"]["content_pillars"][0]["name"]
    assert draft["validation"]["character_count"] == len(text) <= draft["validation"]["platform_limit"] == 3000
    # Competitor insight informs, but the competitor is never named or quoted.
    assert "zoho" not in text.lower() and "Create GST invoices in one place" not in text
    facts = [c for c in post["claims"] if c["kind"] == "product_fact"]
    assert facts and all(any(r.startswith(("P:", "S")) for r in c["refs"]) for c in facts)
    assert any("S1" in c["refs"] for c in facts)  # source evidence used
    assert draft["validation"]["unsupported_claims"] == []

    snap = draft["context_snapshot"]
    assert snap["product_id"] == product_id and snap["strategy_version"] == s["version"]
    assert snap["content_type"] == "Social Post" and snap["platform"] == "linkedin"


@pytest.mark.asyncio
async def test_prompt_carries_profile_strategy_sources_and_instructions(authenticated_client):
    project_id, _, s = await ready_project(authenticated_client)
    provider = RecordingProvider({**GOOD_POST, "pillar": s["strategy"]["content_pillars"][1]["name"]})
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        state = await generate(authenticated_client, project_id, pillar_index=1, instructions="Mention the Diwali invoicing rush.")
    prompt = provider.prompts[0]
    strategy = s["strategy"]
    assert "freelance designers" in prompt                                  # profile audience
    assert "GST invoice generation" in prompt                               # profile features
    assert json.dumps(strategy["audience"]["messaging_direction"])[1:-1] in prompt  # strategy positioning (JSON in prompt)
    assert strategy["content_pillars"][1]["name"] in prompt                 # the selected pillar
    assert "Features: GST invoice generation, expense categorisation" in prompt  # S1: the project's own source
    assert "Mention the Diwali invoicing rush." in prompt                   # campaign instructions
    assert "Competitor insights" in prompt and "never name or quote competitors" in prompt
    assert state["draft"]["context_snapshot"]["instructions"] == "Mention the Diwali invoicing rush."
    meta = provider.contexts[0]["meta"]
    assert meta["product_name"] == "LedgerLeaf" and "Zoho Books" in meta["competitor_names"]


@pytest.mark.asyncio
async def test_strategy_changes_change_the_post(authenticated_client):
    project_id, product_id, s = await ready_project(authenticated_client)
    first = await generate(authenticated_client, project_id)

    # A different pillar produces a different post.
    second = await generate(authenticated_client, project_id, pillar_index=1)
    assert second["draft"]["content"]["pillar"] == s["strategy"]["content_pillars"][1]["name"] != first["draft"]["content"]["pillar"]
    assert second["draft"]["version"] == 2

    # Editing the strategy's audience (then re-approving) shows up in the post.
    audience = {**s["strategy"]["audience"], "primary_audience": "boutique branding agencies"}
    edited = (await authenticated_client.patch(f"/api/products/{product_id}/promotion-strategy", json={"strategy": {"audience": audience}})).json()
    assert (await authenticated_client.post(gen_url(project_id), json={})).status_code == 409  # strategy no longer approved
    await approve_strategy(authenticated_client, project_id, product_id, edited["version"])
    blocked = await authenticated_client.post(gen_url(project_id), json={})
    assert blocked.status_code == 409 and "Content Type again" in blocked.json()["detail"]
    await approve_type(authenticated_client, project_id)
    third = await generate(authenticated_client, project_id)
    assert "boutique branding agencies" in post_text(third)
    assert "boutique branding agencies" not in post_text(first)


@pytest.mark.asyncio
async def test_limited_competitor_evidence_is_carried_through(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client, with_evidence=False)
    state = await generate(authenticated_client, project_id)
    post = state["draft"]["content"]
    assert state["draft"]["context_snapshot"]["limited_evidence"] is True
    assert any("Competitor evidence was limited" in x for x in post["limitations"])
    assert not any(c["kind"] == "competitor_context" for c in post["claims"])


@pytest.mark.asyncio
async def test_invalid_output_is_regenerated_then_fails(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    bad = RecordingProvider({**GOOD_POST, "body": "LedgerLeaf saves designers 73% of their bookkeeping time."})
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=bad):
        res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 500 and "figure" in res.json()["detail"]
    assert len(bad.prompts) == 3 and "PREVIOUS ATTEMPT WAS REJECTED" in bad.prompts[1]
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"] is None


@pytest.mark.asyncio
async def test_pillar_and_instruction_bounds(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    assert (await authenticated_client.post(gen_url(project_id), json={"pillar_index": 99})).status_code == 422
    assert (await authenticated_client.post(gen_url(project_id), json={"instructions": "x" * 1001})).status_code == 422


# ─── Editing, persistence, approval guard ───────────────────────────────────

@pytest.mark.asyncio
async def test_edit_save_and_reload(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    state = await generate(authenticated_client, project_id)
    content = state["draft"]["content"]
    new_hook = content["alternative_hooks"][0]
    alternatives = [content["hook"]] + content["alternative_hooks"][1:]
    res = await authenticated_client.patch(gen_url(project_id), json={
        "hook": new_hook, "alternative_hooks": alternatives, "body": content["body"] + "\n\nMade in India for designers.",
        "cta": "Message us to try LedgerLeaf.", "hashtags": ["Bookkeeping", "#LedgerLeaf"], "version": 1,
    })
    assert res.status_code == 200, res.text
    saved = res.json()["draft"]
    assert saved["version"] == 2 and saved["edited"] is True
    assert saved["content"]["hook"] == new_hook and saved["content"]["hashtags"] == ["#Bookkeeping", "#LedgerLeaf"]

    # Survives a new session (a refresh / new login reads the same row).
    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as fresh:
        row = (await fresh.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalar_one()
        assert row.content["cta"] == "Message us to try LedgerLeaf." and row.version == 2
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"]["content"]["hook"] == new_hook

    # Stale version, over-limit text, and placeholders are refused.
    assert (await authenticated_client.patch(gen_url(project_id), json={"cta": "x", "version": 1})).status_code == 409
    too_long = await authenticated_client.patch(gen_url(project_id), json={"body": "LedgerLeaf " * 400})
    assert too_long.status_code == 422 and "limit" in too_long.json()["detail"]
    placeholder = await authenticated_client.patch(gen_url(project_id), json={"cta": "Visit [insert link]"})
    assert placeholder.status_code == 422
    assert (await authenticated_client.patch(gen_url(project_id), json={"pillar": "x"})).status_code == 200  # ignored field


@pytest.mark.asyncio
async def test_approved_post_is_never_overwritten(authenticated_client, db_session):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)).values(status="approved"))
    await db_session.commit()
    assert (await authenticated_client.post(gen_url(project_id), json={})).status_code == 409
    assert (await authenticated_client.patch(gen_url(project_id), json={"cta": "New CTA for LedgerLeaf."})).status_code == 409
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["status"] == "approved" and state["can_generate"] is False and state["draft"]["version"] == 1


# ─── Isolation + legacy ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_other_users_cannot_read_or_generate(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    assert (await other_client.get(gen_url(project_id))).status_code == 404
    assert (await other_client.post(gen_url(project_id), json={})).status_code == 404
    assert (await other_client.patch(gen_url(project_id), json={"cta": "hi"})).status_code == 404


@pytest.mark.asyncio
async def test_no_cross_product_leakage(authenticated_client):
    # The same user has a second product; its name must never reach this post.
    other = await authenticated_client.post("/api/projects", json={"title": "Bloomly", "source_type": "Text Idea", "source_reference": "x"})
    await authenticated_client.post(f"/api/projects/{other.json()['id']}/sources/ingest",
                                    data={"source_type": "text", "content": "Product: Bloomly - a plant care app for apartment gardeners."})
    await authenticated_client.post(f"/api/projects/{other.json()['id']}/product-understanding")

    project_id, _, _ = await ready_project(authenticated_client)
    leaky = RecordingProvider({**GOOD_POST, "body": "LedgerLeaf creates GST invoices. Bloomly users love it too."})
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=leaky):
        res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 500 and "another of the user's products" in res.json()["detail"]
    assert "Bloomly" in leaky.contexts[0]["meta"]["forbidden_names"]
    assert all("Bloomly" not in p for p in leaky.prompts)

    state = await generate(authenticated_client, project_id)  # demo: only this product's data
    assert "bloomly" not in post_text(state).lower()


@pytest.mark.asyncio
async def test_legacy_projects_are_untouched(authenticated_client, db_session, test_user):
    project = Project(title="Legacy", source_type="Text Idea", source_reference="x", user_id=test_user.id)
    db_session.add(project)
    await db_session.commit()
    for key in ("source-grounding", "content-type", "content-selection", "storyboard", "final-script"):
        db_session.add(WorkflowStage(project_id=project.id, stage_type=key, status="Locked"))
    await db_session.commit()

    state = (await authenticated_client.get(gen_url(project.id))).json()
    assert state["status"] == "not_applicable" and state["can_generate"] is False
    assert (await authenticated_client.post(gen_url(project.id), json={})).status_code == 409
    stages = (await authenticated_client.get(f"/api/projects/{project.id}")).json()["stages"]
    assert [s["stage_type"] for s in stages] == ["source-grounding", "content-type", "content-selection", "storyboard", "final-script"]
    # Legacy projects can still approve any content type (no strategy, no generation annotation).
    ok = await approve_type(authenticated_client, project.id, "Carousel")
    assert "generation_supported" not in ok["data"]


@pytest.mark.asyncio
async def test_unknown_project_is_404(authenticated_client):
    assert (await authenticated_client.get(gen_url(uuid.uuid4()))).status_code == 404


@pytest.mark.asyncio
async def test_persona_and_tone_controls_and_persistence(authenticated_client):
    """Audience persona and editorial tone:
    1. Are exposed in context with derived personas and supported tones.
    2. Preferences can be saved before generation and are reflected in state.
    3. Generate accepts persona & tone, persists them in snapshot and stage.data.
    4. Genuinely affect generation prompt and demo post output (hook, CTA, alignment).
    5. Are reflected after reload/get.
    """
    project_id, _, _ = await ready_project(authenticated_client)

    # 1. Inspect state
    st0 = (await authenticated_client.get(gen_url(project_id))).json()
    assert "available_personas" in st0["context"]
    assert len(st0["context"]["available_personas"]) >= 2
    assert st0["context"]["available_tones"] == ["professional", "conversational", "educational", "bold"]
    assert st0["context"]["selected_tone"] == "professional"

    # 2. Save preferences before generating
    pref_res = await authenticated_client.put(
        f"/api/projects/{project_id}/generated-content/preferences",
        json={"audience_persona": "Decision-Maker (CA firms)", "editorial_tone": "conversational"},
    )
    assert pref_res.status_code == 200
    st_pref = pref_res.json()
    assert st_pref["context"]["selected_persona"] == "Decision-Maker (CA firms)"
    assert st_pref["context"]["selected_tone"] == "conversational"

    # 3. Reload reflects saved preferences
    st_reload = (await authenticated_client.get(gen_url(project_id))).json()
    assert st_reload["context"]["selected_persona"] == "Decision-Maker (CA firms)"
    assert st_reload["context"]["selected_tone"] == "conversational"

    # 4. Generate with selected persona and conversational tone
    res_conv = await authenticated_client.post(
        gen_url(project_id),
        json={
            "pillar_index": 0,
            "audience_persona": "Decision-Maker (CA firms)",
            "editorial_tone": "conversational",
        },
    )
    assert res_conv.status_code == 200
    data_conv = res_conv.json()
    snap_conv = data_conv["draft"]["context_snapshot"]
    assert snap_conv["audience_persona"] == "Decision-Maker (CA firms)"
    assert snap_conv["editorial_tone"] == "conversational"

    # Conversational CTA and alignment note
    post_conv = data_conv["draft"]["content"]
    assert "Curious how" in post_conv["cta"] or "say hi" in post_conv["cta"]
    assert "conversational tone" in post_conv["strategy_alignment"]
    assert "Decision-Maker (CA firms)" in post_conv["strategy_alignment"]

    # 5. Generate with bold tone to prove tone genuinely alters output
    res_bold = await authenticated_client.post(
        gen_url(project_id),
        json={
            "pillar_index": 0,
            "audience_persona": "Practitioner / End-User",
            "editorial_tone": "bold",
        },
    )
    assert res_bold.status_code == 200
    data_bold = res_bold.json()
    post_bold = data_bold["draft"]["content"]
    assert "Ready to stop settling?" in post_bold["cta"]
    assert "bold tone" in post_bold["strategy_alignment"]
    assert data_bold["draft"]["context_snapshot"]["editorial_tone"] == "bold"

    # 6. Invalid tone is rejected with 422
    bad_tone = await authenticated_client.post(
        gen_url(project_id),
        json={"editorial_tone": "hyperbolic"},
    )
    assert bad_tone.status_code == 422


@pytest.mark.asyncio
async def test_persona_and_tone_in_prompt_context_for_real_provider(authenticated_client):
    """When a real provider is called, persona and tone are injected into prompt context."""
    project_id, _, _ = await ready_project(authenticated_client)
    recorder = RecordingProvider(GOOD_POST)
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=recorder):
        res = await authenticated_client.post(
            gen_url(project_id),
            json={
                "pillar_index": 0,
                "audience_persona": "Segment: Freelancers",
                "editorial_tone": "educational",
            },
        )
    assert res.status_code == 200
    prompt_ctx = recorder.contexts[0]["prompt_context"]
    ctx_dict = dict(prompt_ctx)
    assert "Target Audience Persona for THIS post" in ctx_dict
    assert "Segment: Freelancers" in ctx_dict["Target Audience Persona for THIS post"]
    assert "Editorial Tone of Voice for THIS post" in ctx_dict
    assert "Educational:" in ctx_dict["Editorial Tone of Voice for THIS post"]
