"""RAG + research grounding: chunking with provenance, safe ingestion (empty / oversized / duplicate / failure /
re-index / stale), owner-scoped relevant retrieval with stable references, and grounding of Product Understanding,
competitor comparison, Promotion Strategy, post generation and Evaluate & Improve. Demo embeddings only; no
external calls."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from app.ai.config import AIConfig
from app.ai.evaluation import EvaluationContext, RuleBasedEvaluator
from app.ai.platform_policy import platform_policy
from app.core.config import settings
from app.models.source import DocumentChunk, SourceDocument
from app.services.chunking_service import ChunkingService
from app.services.retrieval_service import RetrievalService, excerpt_ref
from tests.ai.test_pillar_alignment import PILLARS, PROFILE
from tests.test_generate_content import GOOD_POST, gen_url, ready_project
from tests.test_promotion_strategy import other_client  # noqa: F401

DEMO = AIConfig(provider="demo")
PRICING = ("Pricing: TaskNest costs nothing for one board. The team plan adds shared boards for agencies. "
           "Annual billing is available for the team plan.")
FEATURES = ("Features: task boards for every client, deadline reminders before due dates, and simple project "
            "tracking designed for independent freelancers.")


async def make_project(client, title="RAG"):
    res = await client.post("/api/projects", json={"title": title, "source_type": "Text Idea", "source_reference": "x"})
    return res.json()["id"]


async def ingest(client, project_id, text):
    return await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": text})


async def chunks_of(db, source_id):
    return (await db.execute(select(DocumentChunk).where(DocumentChunk.source_document_id == UUID(source_id))
                             .order_by(DocumentChunk.chunk_index))).scalars().all()


# ─── Chunking ───────────────────────────────────────────────────────────────

def test_chunks_are_bounded_overlapping_and_carry_provenance():
    text = "\n\n".join(f"Paragraph {i}. " + "This sentence describes one idea in plain words. " * 6 for i in range(12))
    chunks = ChunkingService.chunk_text(text, {"title": "Brief", "raw_text": text, "file_path": "/srv/tmp/x.pdf"},
                                        chunk_size=400, chunk_overlap=80)
    assert len(chunks) > 3
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.metadata["char_start"] < prev.metadata["char_end"] or cur.content.startswith("Paragraph")  # overlap or boundary
    for c in chunks:
        assert len(c.content) <= 400
        assert c.content in text[c.metadata["char_start"]:c.metadata["char_end"] + 1]  # offsets point at the text
        assert c.metadata["title"] == "Brief" and c.metadata["content_hash"]
        assert "raw_text" not in c.metadata and "file_path" not in c.metadata  # no full text or server paths on chunks
    assert sum(c.content.rstrip().endswith(".") for c in chunks) >= len(chunks) - 1  # sentence/paragraph boundaries


def test_pdf_page_numbers_follow_real_pages():
    page1, page3 = "Alpha page text. " * 30, "Gamma page text. " * 30
    text = page1 + "\n\n" + page3
    chunks = ChunkingService.chunk_text(text, {}, chunk_size=200, chunk_overlap=20,
                                        page_ranges=[[0, len(page1)], [len(page1) + 2, len(text)]], page_numbers=[1, 3])
    assert {c.metadata["page"] for c in chunks} == {1, 3}  # page 2 had no text and is never cited
    assert all(c.metadata["page"] == (1 if "Alpha" in c.content else 3) for c in chunks if "Alpha" in c.content or "Gamma" in c.content)


def test_pdf_extraction_reports_page_ranges(monkeypatch):
    from app.services import extraction_service
    pages = [SimpleNamespace(extract_text=lambda: "First page."), SimpleNamespace(extract_text=lambda: ""),
             SimpleNamespace(extract_text=lambda: "Third page.")]
    monkeypatch.setattr(extraction_service.pypdf, "PdfReader", lambda _: SimpleNamespace(pages=pages))
    result = extraction_service.ExtractionService.extract_from_pdf(b"%PDF fake")
    assert result.text == "First page.\n\nThird page."
    assert result.metadata["page_numbers"] == [1, 3]
    for (start, end), expected in zip(result.metadata["page_ranges"], ["First page.", "Third page."]):
        assert result.text[start:end] == expected


# ─── Ingestion ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingestion_keeps_full_text_and_chunk_provenance(authenticated_client, db_session):
    project_id = await make_project(authenticated_client)
    long_text = (FEATURES + " ") * 40
    res = await ingest(authenticated_client, project_id, long_text)
    assert res.status_code == 200 and res.json()["status"] == "Success" and res.json()["chunks_created"] > 1
    source = await db_session.get(SourceDocument, UUID(res.json()["id"]))
    await db_session.refresh(source)
    assert source.extracted_text == long_text and source.metadata_["content_hash"]
    assert source.metadata_["embedding_provider"] == "demo" and source.metadata_["chunk_count"] == res.json()["chunks_created"]
    for chunk in await chunks_of(db_session, res.json()["id"]):
        meta = chunk.metadata_
        assert meta["source_document_id"] == res.json()["id"] and meta["source_content_hash"] == source.metadata_["content_hash"]
        assert meta["embedding_provider"] == "demo" and meta["embedding_model"] == "demo-hash-1536"
        assert "raw_text" not in meta and len(chunk.content) <= settings.RAG_CHUNK_SIZE


@pytest.mark.asyncio
async def test_empty_and_oversized_sources_are_clear_errors(authenticated_client, db_session, monkeypatch):
    project_id = await make_project(authenticated_client)
    empty = await ingest(authenticated_client, project_id, "   \n  ")
    assert empty.status_code == 422 and "no extractable text" in empty.json()["detail"]
    monkeypatch.setattr(settings, "RAG_MAX_SOURCE_CHARS", 100)
    big = await ingest(authenticated_client, project_id, "word " * 100)
    assert big.status_code == 422 and "too large" in big.json()["detail"]
    count = (await db_session.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.project_id == UUID(project_id)))).scalar()
    assert count == 0
    statuses = (await db_session.execute(select(SourceDocument.status).where(SourceDocument.project_id == UUID(project_id)))).scalars().all()
    assert statuses and set(statuses) == {"failed"}


@pytest.mark.asyncio
async def test_duplicate_ingestion_is_not_indexed_twice(authenticated_client, db_session):
    project_id = await make_project(authenticated_client)
    first = (await ingest(authenticated_client, project_id, FEATURES)).json()
    again = await ingest(authenticated_client, project_id, FEATURES + "  ")  # same content, different whitespace
    assert again.status_code == 200 and again.json()["status"] == "Duplicate" and again.json()["duplicate_of"] == first["id"]
    assert again.json()["chunks_created"] == 0
    total = (await db_session.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.project_id == UUID(project_id)))).scalar()
    assert total == first["chunks_created"]
    other = await make_project(authenticated_client, "Other")
    assert (await ingest(authenticated_client, other, FEATURES)).json()["status"] == "Success"  # per project only


@pytest.mark.asyncio
async def test_failed_indexing_leaves_no_partial_chunks(authenticated_client, db_session, monkeypatch):
    from app.ai.providers.embedding.demo import DemoEmbeddingProvider

    async def broken(self, texts):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(DemoEmbeddingProvider, "embed_documents", broken)
    project_id = await make_project(authenticated_client)
    res = await ingest(authenticated_client, project_id, FEATURES)
    assert res.status_code == 500
    source = (await db_session.execute(select(SourceDocument).where(SourceDocument.project_id == UUID(project_id)))).scalar_one()
    await db_session.refresh(source)
    assert source.status == "failed" and "embedding service down" in source.metadata_["error"]
    assert (await db_session.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.project_id == UUID(project_id)))).scalar() == 0


@pytest.mark.asyncio
async def test_stale_chunks_are_never_used_until_reindexed(authenticated_client, db_session, other_client):
    project_id = await make_project(authenticated_client)
    source_id = (await ingest(authenticated_client, project_id, PRICING)).json()["id"]
    found = await RetrievalService.retrieve_evidence(db_session, "pricing team plan", DEMO, user_id=None, project_ids=[UUID(project_id)])
    assert found.status == "ok"
    old_ids = {c.id for c in await chunks_of(db_session, source_id)}

    # The source's text changed after indexing: its chunks are now stale and must not be returned.
    await db_session.execute(update(SourceDocument).where(SourceDocument.id == UUID(source_id)).values(
        extracted_text=PRICING + " New: a student plan.",
        metadata_=SourceDocument.metadata_.op("||")({"content_hash": "changed"})))
    await db_session.commit()
    stale = await RetrievalService.retrieve_evidence(db_session, "pricing team plan", DEMO, user_id=None, project_ids=[UUID(project_id)])
    assert stale.chunks == [] and stale.skipped_stale == len(old_ids) and stale.status == "no_relevant_results"

    assert (await other_client.post(f"/api/projects/{project_id}/sources/{source_id}/reindex")).status_code == 404
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/{source_id}/reindex")
    assert res.status_code == 200 and res.json()["status"] == "Reindexed" and res.json()["embedding_provider"] == "demo"
    db_session.expire_all()
    new = await chunks_of(db_session, source_id)
    assert new and not ({c.id for c in new} & old_ids)  # replaced, not appended
    fresh = await RetrievalService.retrieve_evidence(db_session, "student plan", DEMO, user_id=None, project_ids=[UUID(project_id)])
    assert fresh.status == "ok" and "student plan" in fresh.chunks[0].content


# ─── Retrieval ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieval_is_relevant_and_explicit_when_nothing_matches(authenticated_client, db_session, test_user):
    project_id = await make_project(authenticated_client)
    await ingest(authenticated_client, project_id, PRICING)
    await ingest(authenticated_client, project_id, FEATURES)
    pid = [UUID(project_id)]
    pricing = await RetrievalService.retrieve_evidence(db_session, "How much does the team plan cost? annual billing", DEMO,
                                                       user_id=test_user.id, project_ids=pid)
    assert pricing.status == "ok" and "Annual billing" in pricing.chunks[0].content and pricing.mode == "keyword"
    features = await RetrievalService.retrieve_evidence(db_session, "deadline reminders and task boards", DEMO, user_id=test_user.id, project_ids=pid)
    assert "deadline reminders" in features.chunks[0].content
    nothing = await RetrievalService.retrieve_evidence(db_session, "quantum chromodynamics lattice", DEMO, user_id=test_user.id, project_ids=pid)
    assert nothing.status == "no_relevant_results" and nothing.chunks == []  # no fallback evidence
    assert "nothing was substituted" in nothing.note()


@pytest.mark.asyncio
async def test_one_document_cannot_dominate(authenticated_client, db_session, test_user):
    project_id = await make_project(authenticated_client)
    await ingest(authenticated_client, project_id, " ".join(f"Deadline reminders section {i}. " + "Deadline reminders keep due dates. " * 30 for i in range(6)))
    await ingest(authenticated_client, project_id, "Deadline reminders also arrive by email.")
    found = await RetrievalService.retrieve_evidence(db_session, "deadline reminders", DEMO, user_id=test_user.id,
                                                     project_ids=[UUID(project_id)], top_k=5)
    per_doc = {}
    for c in found.chunks:
        per_doc[c.source_document_id] = per_doc.get(c.source_document_id, 0) + 1
    assert len(per_doc) == 2 and max(per_doc.values()) <= settings.RAG_MAX_PER_SOURCE


@pytest.mark.asyncio
async def test_ownership_and_product_scope(authenticated_client, other_client, db_session, test_user):
    mine = await make_project(authenticated_client)
    await ingest(authenticated_client, mine, PRICING)
    theirs = await make_project(other_client, "Theirs")
    await ingest(other_client, theirs, "Pricing: a completely different product with its own team plan.")
    # Even when a caller passes another user's project id, ownership in the query keeps it out.
    found = await RetrievalService.retrieve_evidence(db_session, "team plan pricing", DEMO, user_id=test_user.id,
                                                     project_ids=[UUID(mine), UUID(theirs)])
    assert found.chunks and all(c.source_document_id != theirs for c in found.chunks)
    assert all("completely different" not in c.content for c in found.chunks)
    assert (await RetrievalService.retrieve_evidence(db_session, "team plan", DEMO, user_id=test_user.id,
                                                     project_ids=[UUID(theirs)])).status == "no_sources"


@pytest.mark.asyncio
async def test_stable_references_and_metadata(authenticated_client, db_session, test_user):
    project_id = await make_project(authenticated_client)
    source_id = (await ingest(authenticated_client, project_id, PRICING)).json()["id"]
    a = await RetrievalService.retrieve_evidence(db_session, "team plan", DEMO, user_id=test_user.id, project_ids=[UUID(project_id)])
    b = await RetrievalService.retrieve_evidence(db_session, "team plan", DEMO, user_id=test_user.id, project_ids=[UUID(project_id)])
    assert [c.ref for c in a.chunks] == [c.ref for c in b.chunks] == [excerpt_ref(source_id, 0)]
    assert a.chunks[0].ref.startswith("S:") and a.chunks[0].source_name and "unverified" in a.chunks[0].describe()
    assert "raw_text" not in a.chunks[0].metadata


@pytest.mark.asyncio
async def test_vectors_from_another_provider_are_not_compared(authenticated_client, db_session, test_user, monkeypatch):
    from app.ai.providers.embedding import factory

    class FakeSemantic:
        provider_name, model_name, semantic = "fake", "fake-1536", True

        async def embed_text(self, text):
            return [0.01] * 1536

    project_id = await make_project(authenticated_client)
    await ingest(authenticated_client, project_id, PRICING)  # indexed with demo vectors
    monkeypatch.setattr(factory.EmbeddingProviderFactory, "get_provider", staticmethod(lambda config: FakeSemantic()))
    found = await RetrievalService.retrieve_evidence(db_session, "team plan", DEMO, user_id=test_user.id, project_ids=[UUID(project_id)])
    assert found.mode == "hybrid" and found.keyword_only == found.considered and found.chunks[0].semantic is None


@pytest.mark.asyncio
async def test_no_paid_embeddings_in_demo(authenticated_client, monkeypatch):
    from app.ai.providers.embedding import openai as openai_embeddings

    def refuse(*args, **kwargs):
        raise AssertionError("A paid embedding provider was used.")

    monkeypatch.setattr(openai_embeddings.OpenAIEmbeddingProvider, "__init__", refuse)
    project_id = await make_project(authenticated_client)
    assert (await ingest(authenticated_client, project_id, PRICING)).status_code == 200


# ─── Downstream grounding ───────────────────────────────────────────────────

class ExcerptCitingProvider:
    """Real-AI stand-in: cites the first retrieved excerpt it was given; records the prompt."""

    def __init__(self, claim_text: str):
        self.claim_text, self.prompts, self.allowed = claim_text, [], []

    async def generate_structured(self, prompt, schema):
        from app.ai.generation_context import get_generation_context
        self.prompts.append(prompt)
        self.allowed = list(get_generation_context()["allowed_refs"])
        excerpt = next(r for r in self.allowed if r.startswith("S:"))
        post = {**GOOD_POST, "pillar": get_generation_context()["meta"]["pillar"],
                "claims": [{"text": self.claim_text, "kind": "product_fact", "refs": [excerpt]}]}
        return schema.model_validate(post)

    async def generate_text(self, prompt):
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_generation_prompt_uses_stable_labelled_excerpts(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    provider = ExcerptCitingProvider("LedgerLeaf creates GST invoices")
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 200, res.text
    prompt = provider.prompts[0]
    assert "S1 — Project sources" in prompt and "unverified source text" in prompt
    assert "Source excerpts (S:...) are unverified text" in prompt
    snapshot = res.json()["draft"]["context_snapshot"]
    excerpts = [r for r in provider.allowed if r.startswith("S:")]
    assert excerpts and set(excerpts) <= set(snapshot["evidence_meta"]) and snapshot["retrieval"]["status"] == "ok"
    evidence = {e["ref"]: e["description"] for e in res.json()["draft"]["evidence"]}
    assert all("Source excerpt (" in evidence[r] and "unverified" in evidence[r] for r in excerpts)


@pytest.mark.asyncio
async def test_evaluation_checks_cited_excerpts(authenticated_client, db_session):
    project_id, _, _ = await ready_project(authenticated_client)
    provider = ExcerptCitingProvider("GST invoice generation")
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        draft = (await authenticated_client.post(gen_url(project_id), json={})).json()["draft"]
    ev = (await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": draft["version"]})).json()
    grounding = next(d for d in ev["evaluation"]["result"]["dimensions"] if d["key"] == "factual_grounding")
    assert any(f["type"] == "unknown" and "backed only by source text" in f["message"] for f in grounding["findings"])
    assert not any(f["type"] == "problem" for f in grounding["findings"])

    # The cited source changes after generation: the citation is flagged, not trusted.
    ref = next(r for r in provider.allowed if r.startswith("S:"))
    source_id = draft["context_snapshot"]["evidence_meta"][ref]["source_document_id"]
    await db_session.execute(update(SourceDocument).where(SourceDocument.id == UUID(source_id)).values(
        metadata_=SourceDocument.metadata_.op("||")({"content_hash": "changed"})))
    await db_session.commit()
    ev = (await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": draft["version"]})).json()
    grounding = next(d for d in ev["evaluation"]["result"]["dimensions"] if d["key"] == "factual_grounding")
    assert any(f["type"] == "problem" and "changed since the post was generated" in f["message"] for f in grounding["findings"])


def test_excerpt_that_does_not_contain_the_claim_is_a_problem():
    ref = "S:abcd1234#0"
    ctx = EvaluationContext(
        post={"hook": "TaskNest for freelance designers.", "body": "Task boards and deadline reminders.", "cta": "Try it.",
              "hashtags": ["#TaskNest"], "alternative_hooks": ["a", "b", "c"], "pillar": "How it works", "limitations": [],
              "strategy_alignment": "", "claims": [{"text": "TaskNest integrates with every accounting tool", "kind": "product_fact", "refs": [ref]}]},
        version=1, edited=False, product_name="TaskNest", profile=PROFILE, pillar_name="How it works", pillar=PILLARS["features"],
        strategy={}, competitor=None, validation={"issues": [], "warnings": [], "character_count": 100}, evidence={ref: "Source excerpt"},
        policy=platform_policy(), excerpts={ref: {"status": "current", "content": "Task boards for every client."}})
    grounding = next(d for d in RuleBasedEvaluator().evaluate(ctx)["dimensions"] if d["key"] == "factual_grounding")
    (problem,) = [f for f in grounding["findings"] if f["type"] == "problem"]
    assert "does not clearly contain the claim" in problem["message"] and problem["evidence"][0]["ref"] == ref


@pytest.mark.asyncio
async def test_product_understanding_grounding_is_labelled(authenticated_client, test_user, db_session):
    from app.services.product_service import ProductService
    project_id = await make_project(authenticated_client)
    await ingest(authenticated_client, project_id, FEATURES)
    grounding = await ProductService(db_session, test_user.id)._grounding(UUID(project_id))
    assert grounding["refs"] and grounding["refs"][0].startswith("S:")
    assert "unverified source text, not approved facts" in grounding["text"] and f"[{grounding['refs'][0]}]" in grounding["text"]


@pytest.mark.asyncio
async def test_strategy_and_comparison_get_background_excerpts_that_are_not_citable(authenticated_client, db_session, test_user):
    from tests.test_promotion_strategy import approve_competitors, make_product
    from app.services.strategy_service import StrategyService

    project_id, product_id = await make_product(authenticated_client)
    captured = {}

    async def fake_compare(state):
        captured.update(state)
        return {"similarities": [], "differences": [], "messaging_gaps": [], "positioning_opportunities": [],
                "promotion_patterns_to_investigate": [], "evidence_needed": []}

    with patch("app.services.competitor_service.run_competitor_comparison", fake_compare):
        await approve_competitors(authenticated_client, project_id, product_id)
    titles = [t for t, _ in captured["prompt_context"]]
    assert any(t.startswith("Our own source excerpts — unverified background") for t in titles)
    assert not any(r.startswith("S:") for r in captured["allowed_refs"])  # never competitor evidence

    from app.models.product import Product
    product = await db_session.get(Product, UUID(product_id))
    await db_session.refresh(product)
    context = await StrategyService(db_session, test_user.id)._context(product)
    section = next(body for title, body in context["prompt_context"] if title.startswith("Our own source excerpts"))
    assert "[S:" in section and "GST invoice generation" in section
    assert not any(r.startswith("S:") for r in context["allowed_refs"])


# ─── Cited-excerpt evaluation cases (audit follow-up) ───────────────────────

class FakeEmbeddings:
    """Hermetic, deterministic stand-in for the configured embedding provider (no network, no cost)."""
    provider_name, model_name, semantic = "fake", "fake-1536", False

    async def embed_text(self, text):
        return [0.0] * 1535 + [1.0]

    async def embed_documents(self, texts):
        return [[0.0] * 1535 + [1.0] for _ in texts]


@pytest.fixture
def fake_embeddings(monkeypatch):
    from app.ai.providers.embedding import factory
    monkeypatch.setattr(factory.EmbeddingProviderFactory, "get_provider", staticmethod(lambda config: FakeEmbeddings()))


async def post_citing_an_excerpt(client):
    """Isolated test product + a post whose only claim cites the first retrieved excerpt (fake real-AI provider)."""
    project_id, _, _ = await ready_project(client)
    provider = ExcerptCitingProvider("GST invoice generation")
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        res = await client.post(gen_url(project_id), json={})
    assert res.status_code == 200, res.text
    draft = res.json()["draft"]
    ref = next(r for r in provider.allowed if r.startswith("S:"))
    return project_id, draft, ref, draft["context_snapshot"]["evidence_meta"][ref]


async def excerpt_status(db, user, project_id, draft):
    from app.models.project import Project
    from app.services.evaluation_service import EvaluationService
    db.expire_all()
    project = await db.get(Project, UUID(project_id))
    await db.refresh(user)  # the test committed: reload before reading attributes
    return await EvaluationService(db, user.id)._excerpt_status(project, draft["context_snapshot"])


async def excerpt_findings(client, project_id, draft, ref):
    """(type, severity, message) of every factual-grounding finding that cites `ref`, from a real evaluation."""
    res = await client.post(f"/api/projects/{project_id}/evaluation", json={"version": draft["version"]})
    assert res.status_code == 200, res.text
    dims = res.json()["evaluation"]["result"]["dimensions"]
    findings = next(d for d in dims if d["key"] == "factual_grounding")["findings"]
    return [(f["type"], f["severity"], f["message"]) for f in findings if any(e.get("ref") == ref for e in f.get("evidence") or [])]


async def cited_chunk(db, meta):
    db.expire_all()
    return (await db.execute(select(DocumentChunk).where(
        DocumentChunk.source_document_id == UUID(meta["source_document_id"]),
        DocumentChunk.chunk_index == meta["chunk_index"]))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_current_cited_excerpt_is_only_an_unknown(authenticated_client, db_session, test_user):
    project_id, draft, ref, _ = await post_citing_an_excerpt(authenticated_client)
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "current"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("unknown", "low")]
    assert "backed only by source text" in findings[0][2]


@pytest.mark.asyncio
async def test_deleted_cited_chunk_is_missing(authenticated_client, db_session, test_user):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    await db_session.delete(await cited_chunk(db_session, meta))
    await db_session.commit()
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "missing"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]
    assert "has been removed since the post was generated" in findings[0][2]


@pytest.mark.asyncio
@pytest.mark.parametrize("new_status", ["failed", "duplicate", "processing"])
async def test_source_no_longer_completed_is_not_current(authenticated_client, db_session, test_user, new_status):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    await db_session.execute(update(SourceDocument).where(SourceDocument.id == UUID(meta["source_document_id"]))
                             .values(status=new_status))
    await db_session.commit()
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "missing"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]
    assert "has been removed since the post was generated" in findings[0][2]


@pytest.mark.asyncio
async def test_chunk_hash_differing_from_snapshot_is_changed(authenticated_client, db_session, test_user):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    chunk = await cited_chunk(db_session, meta)
    chunk.metadata_ = {**chunk.metadata_, "content_hash": "0" * 64}
    await db_session.commit()
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "changed"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]
    assert "has changed since the post was generated" in findings[0][2]


@pytest.mark.asyncio
async def test_chunk_source_hash_differing_from_source_is_changed(authenticated_client, db_session, test_user):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    chunk = await cited_chunk(db_session, meta)
    chunk.metadata_ = {**chunk.metadata_, "source_content_hash": "f" * 64}
    await db_session.commit()
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "changed"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]
    assert "has changed since the post was generated" in findings[0][2]


@pytest.mark.asyncio
async def test_cited_excerpt_without_the_claims_terms_is_a_problem(authenticated_client, db_session, test_user):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    chunk = await cited_chunk(db_session, meta)
    chunk.content = "Our office is open on weekdays."  # hashes untouched: still "current", but no longer states the claim
    await db_session.commit()
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "current"
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]
    assert "does not clearly contain the claim" in findings[0][2]


# ─── Evaluation after re-indexing ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluation_and_retrieval_across_reindexing(authenticated_client, db_session, test_user, fake_embeddings):
    project_id, draft, ref, meta = await post_citing_an_excerpt(authenticated_client)
    source_id, user_id = meta["source_document_id"], test_user.id
    assert "chunk_row_id" not in meta  # identity is source + chunk index + content hash (row ids change on re-index)
    old_row_id = (await cited_chunk(db_session, meta)).id

    async def reindex():
        res = await authenticated_client.post(f"/api/projects/{project_id}/sources/{source_id}/reindex")
        assert res.status_code == 200, res.text

    async def search(query):
        db_session.expire_all()
        return await RetrievalService.retrieve_evidence(db_session, query, DEMO, user_id=user_id,
                                                        project_ids=[UUID(project_id)])

    # 1. Re-index without changing the text: new chunk rows (fake embeddings), same evidence → still current.
    await reindex()
    chunk = await cited_chunk(db_session, meta)
    assert chunk.id != old_row_id and chunk.metadata_["embedding_provider"] == "fake"
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "current"
    assert [(t, s) for t, s, _ in await excerpt_findings(authenticated_client, project_id, draft, ref)] == [("unknown", "low")]

    # 2. The source's extracted text changes (isolated test row only). Until re-indexed, its chunks are stale:
    #    retrieval must not return them, and the cited excerpt is no longer current.
    new_text = "LedgerLeaf now sends payment reminders over SMS to freelance clients who pay late."
    await db_session.execute(update(SourceDocument).where(SourceDocument.id == UUID(source_id)).values(extracted_text=new_text))
    await db_session.commit()
    before = await search("GST invoice generation payment reminders SMS")
    assert before.chunks == [] and before.skipped_stale > 0
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] == "changed"

    # 3. Re-index: only replacement chunks (from the new text) are retrievable; the old reference is not current.
    await reindex()
    after = await search("payment reminders over SMS")
    assert after.status == "ok" and after.skipped_stale == 0
    assert all(c.source_document_id == source_id and "over SMS" in c.content for c in after.chunks)
    assert (await excerpt_status(db_session, test_user, project_id, draft))[ref]["status"] in ("changed", "missing")
    findings = await excerpt_findings(authenticated_client, project_id, draft, ref)
    assert [(t, s) for t, s, _ in findings] == [("problem", "medium")]


# ─── Owner isolation in the assembled product-level prompts ─────────────────

@pytest.mark.asyncio
async def test_other_users_excerpts_never_reach_strategy_or_comparison_prompts(authenticated_client, other_client, db_session, test_user):
    from app.models.product import Product
    from app.models.project import Project
    from app.services.strategy_service import StrategyService
    from tests.test_promotion_strategy import approve_competitors, make_product

    project_id, product_id = await make_product(authenticated_client)
    # Another user's project whose source matches the same terms, attached (bad data) to this user's product.
    intruder = await make_project(other_client, "Intruder")
    res = await ingest(other_client, intruder, "LedgerLeaf GST invoice generation for freelance designers. ZebraFrost roadmap.")
    assert res.status_code == 200, res.text
    await db_session.execute(update(Project).where(Project.id == UUID(intruder)).values(product_id=UUID(product_id)))
    await db_session.commit()
    intruder_source = (await db_session.execute(select(SourceDocument.id).where(SourceDocument.project_id == UUID(intruder)))).scalar_one()
    intruder_label = excerpt_ref(intruder_source, 0).split("#")[0]

    captured = {}

    async def fake_compare(state):
        captured.update(state)
        return {"similarities": [], "differences": [], "messaging_gaps": [], "positioning_opportunities": [],
                "promotion_patterns_to_investigate": [], "evidence_needed": []}

    with patch("app.services.competitor_service.run_competitor_comparison", fake_compare):
        await approve_competitors(authenticated_client, project_id, product_id)
    comparison = "\n".join(f"{t}\n{b}" for t, b in captured["prompt_context"])
    assert "[S:" in comparison and "GST invoice generation" in comparison  # our own excerpts do arrive
    assert "ZebraFrost" not in comparison and intruder_label not in comparison

    product = await db_session.get(Product, UUID(product_id))
    await db_session.refresh(product)
    context = await StrategyService(db_session, test_user.id)._context(product)
    strategy = "\n".join(f"{t}\n{b}" for t, b in context["prompt_context"])
    assert "[S:" in strategy and "GST invoice generation" in strategy
    assert "ZebraFrost" not in strategy and intruder_label not in strategy
