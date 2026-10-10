"""Calendar & content planning, step 2: server-side scheduling eligibility (read-only).

Posts are produced through the real workflow in Demo Mode (generate → evaluate → approve); individual conditions
are then broken in the isolated test database only. Nothing is scheduled, published or sent.
"""
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, event, func, select, update

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.schedule import Schedule
from app.services.scheduling_eligibility import check_scheduling_eligibility, content_digest
from tests.test_generate_content import approve_type, gen_url, generate, ready_project
from tests.test_promotion_strategy import approve as approve_strategy
from tests.test_promotion_strategy import generate as generate_strategy
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_review_approval import evaluate

FUTURE = datetime.now(timezone.utc) + timedelta(days=7)


async def approved_post(client):
    """A product-workflow project whose saved post (v1) was generated, evaluated and approved — Demo Mode."""
    project_id, product_id, _ = await ready_project(client)
    await generate(client, project_id)
    await evaluate(client, project_id, 1)
    res = await client.post(f"{gen_url(project_id)}/approve", json={"version": 1})
    assert res.status_code == 200, res.text
    return UUID(project_id), UUID(product_id)


async def check(db, user_id, project_id, **kwargs):
    db.expire_all()  # the tests change rows directly; read them fresh
    return await check_scheduling_eligibility(db, user_id, project_id, **kwargs)


async def post_row(db, project_id) -> GeneratedContent:
    db.expire_all()
    return (await db.execute(select(GeneratedContent).where(GeneratedContent.project_id == project_id))).scalar_one()


@pytest.mark.asyncio
async def test_approved_and_currently_evaluated_post_is_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, product_id = await approved_post(authenticated_client)
    result = await check(db_session, user_id, project_id, product_id=product_id, scheduled_at=FUTURE)
    assert result.eligible is True and result.reasons == []
    row = await post_row(db_session, project_id)
    assert (result.project_id, result.product_id, result.generated_content_id) == (project_id, product_id, row.id)
    assert (result.content_type, result.platform, result.content_version) == ("Social Post", "linkedin", 1)
    assert result.content_digest == content_digest(row.content) and len(result.content_digest) == 64
    latest = (await db_session.execute(select(ContentEvaluation).where(ContentEvaluation.generated_content_id == row.id))).scalar_one()
    assert result.evaluation_id == latest.id
    body = result.as_dict()
    assert body["eligible"] is True and body["generated_content_id"] == str(row.id) and body["reasons"] == []
    # Any time zone is fine as long as it is explicit; no time at all is also fine (eligibility of the post only).
    ist = timezone(timedelta(hours=5, minutes=30))
    assert (await check(db_session, user_id, project_id, scheduled_at=FUTURE.astimezone(ist))).eligible
    assert (await check(db_session, user_id, project_id)).eligible


@pytest.mark.asyncio
async def test_draft_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    result = await check(db_session, user_id, UUID(project_id))
    assert result.eligible is False and result.codes == ["not_approved", "evaluation_missing"]
    assert "has not been approved" in result.reasons[0].message


@pytest.mark.asyncio
async def test_evaluated_but_unapproved_post_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await evaluate(authenticated_client, project_id, 1)
    result = await check(db_session, user_id, UUID(project_id))
    assert result.codes == ["not_approved"]


@pytest.mark.asyncio
async def test_approved_version_must_be_the_saved_version(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id).values(version=2))
    await db_session.commit()
    result = await check(db_session, user_id, project_id)
    assert result.codes == ["approval_outdated", "evaluation_outdated"]
    assert "Version 1 was approved" in result.reasons[0].message and result.content_version == 2


@pytest.mark.asyncio
async def test_stale_approved_context_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, product_id = await approved_post(authenticated_client)
    # The strategy is regenerated and re-approved and the Content Type re-confirmed: the approved post is now stale.
    s = await generate_strategy(authenticated_client, str(product_id))
    await approve_strategy(authenticated_client, str(project_id), str(product_id), s["version"])
    await approve_type(authenticated_client, str(project_id))
    result = await check(db_session, user_id, project_id)
    assert result.codes == ["stale_content"] and "Promotion Strategy" in result.reasons[0].message


@pytest.mark.asyncio
async def test_missing_evaluation_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    await db_session.execute(delete(ContentEvaluation).where(ContentEvaluation.project_id == project_id))
    await db_session.commit()
    result = await check(db_session, user_id, project_id)
    assert result.codes == ["evaluation_missing"] and result.evaluation_id is None


@pytest.mark.asyncio
async def test_evaluation_of_an_older_version_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    await db_session.execute(update(ContentEvaluation).where(ContentEvaluation.project_id == project_id).values(content_version=0))
    await db_session.commit()
    result = await check(db_session, user_id, project_id)
    assert result.codes == ["evaluation_outdated"] and "version 1" in result.reasons[0].message


@pytest.mark.asyncio
async def test_evaluation_with_blocking_problems_is_not_eligible(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    await db_session.execute(update(ContentEvaluation).where(ContentEvaluation.project_id == project_id).values(overall="not_ready"))
    await db_session.commit()
    assert (await check(db_session, user_id, project_id)).codes == ["evaluation_blocking"]
    # Lesser outcomes (problems without high severity, recommendations) do not block planning.
    await db_session.execute(update(ContentEvaluation).where(ContentEvaluation.project_id == project_id).values(overall="needs_improvement"))
    await db_session.commit()
    assert (await check(db_session, user_id, project_id)).eligible


@pytest.mark.asyncio
async def test_other_users_projects_reveal_nothing(authenticated_client, other_client, db_session, test_user):
    user_id = test_user.id
    theirs, their_product = await approved_post(other_client)
    result = await check(db_session, user_id, theirs, product_id=their_product, scheduled_at=FUTURE)
    missing = await check(db_session, user_id, uuid.uuid4())
    assert result.as_dict() == missing.as_dict()  # indistinguishable from a project that does not exist
    assert result.codes == ["project_not_found"] and result.reasons[0].message == "Project not found."
    assert all(value is None for key, value in result.as_dict().items() if key not in ("eligible", "reasons"))


@pytest.mark.asyncio
async def test_project_must_belong_to_the_selected_product(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, product_id = await approved_post(authenticated_client)
    assert (await check(db_session, user_id, project_id, product_id=product_id)).eligible
    result = await check(db_session, user_id, project_id, product_id=uuid.uuid4())
    assert result.codes == ["product_mismatch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"platform": "twitter"}, {"content_type": "Short Video"}])
async def test_unsupported_platform_or_content_type(authenticated_client, db_session, test_user, change):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id).values(**change))
    await db_session.commit()
    result = await check(db_session, user_id, project_id)
    assert result.codes == ["unsupported_content"] and result.generated_content_id is None


@pytest.mark.asyncio
async def test_no_saved_post_and_legacy_projects(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    assert (await check(db_session, user_id, UUID(project_id))).codes == ["no_content"]
    legacy = Project(title="Legacy", source_type="Text Idea", source_reference="x", user_id=user_id)  # no product stages
    db_session.add(legacy)
    await db_session.commit()
    assert (await check(db_session, user_id, legacy.id)).codes == ["legacy_workflow"]


@pytest.mark.asyncio
async def test_planned_time_must_be_explicit_and_in_the_future(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    naive = (await check(db_session, user_id, project_id, scheduled_at=datetime(2030, 1, 1, 9, 0)))
    assert naive.codes == ["timezone_required"]
    now = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    assert (await check(db_session, user_id, project_id, scheduled_at=now - timedelta(minutes=1), now=now)).codes == ["time_in_past"]
    assert (await check(db_session, user_id, project_id, scheduled_at=now, now=now)).codes == ["time_in_past"]
    assert (await check(db_session, user_id, project_id, scheduled_at=now + timedelta(minutes=1), now=now)).eligible


def test_content_digest_is_stable_and_sensitive():
    post = {"hook": "Invoices in a minute.", "body": "LedgerLeaf creates GST invoices.", "hashtags": ["#GST", "#Freelance"],
            "claims": [{"text": "GST invoices", "refs": ["P:key_features"]}]}
    same_content_other_order = {"claims": [{"refs": ["P:key_features"], "text": "GST invoices"}],
                                "hashtags": ["#GST", "#Freelance"], "body": "LedgerLeaf creates GST invoices.",
                                "hook": "Invoices in a minute."}
    digest = content_digest(post)
    assert digest == content_digest(same_content_other_order) == content_digest(dict(post))
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert content_digest({**post, "body": "LedgerLeaf creates GST invoices!"}) != digest
    assert content_digest({**post, "hashtags": ["#Freelance", "#GST"]}) != digest  # list order is content
    assert content_digest({}) is None and content_digest(None) is None


@pytest.mark.asyncio
async def test_eligibility_checks_never_write(authenticated_client, db_session, test_user):
    user_id = test_user.id
    eligible_id, _ = await approved_post(authenticated_client)
    draft_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, draft_id)

    async def snapshot():
        db_session.expire_all()
        posts = (await db_session.execute(select(GeneratedContent.id, GeneratedContent.status, GeneratedContent.version,
                                                 GeneratedContent.approved_version, GeneratedContent.updated_at)
                                          .order_by(GeneratedContent.id))).all()
        return ((await db_session.execute(select(func.count(Schedule.id)))).scalar(),
                (await db_session.execute(select(func.count(ContentEvaluation.id)))).scalar(), posts)

    before = await snapshot()
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    # Every statement the session sends goes through this connection (listening on the engine would miss a
    # connection the session already holds).
    connection = (await db_session.connection()).sync_connection
    event.listen(connection, "before_cursor_execute", record)
    try:
        for project_id, kwargs in ((eligible_id, {"scheduled_at": FUTURE}), (UUID(draft_id), {}),
                                   (eligible_id, {"scheduled_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}),
                                   (uuid.uuid4(), {})):
            await check_scheduling_eligibility(db_session, user_id, project_id, **kwargs)
        assert not (db_session.new or db_session.dirty or db_session.deleted)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert statements and set(statements) <= {"SELECT"}, set(statements)
    assert await snapshot() == before  # no schedule, evaluation or post change
