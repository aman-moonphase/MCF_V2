"""Concurrent submissions in the content workflow (Step 11 audit) — a double click must never cause a server error,
duplicate rows, or a half-applied approval. Writes race in independent sessions against the isolated test database.
"""
import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.services.evaluation_service import EvaluationService
from app.services.generation_service import GenerationService
from tests.conftest import TestingSessionLocal
from tests.test_generate_content import generate, ready_project


async def attempt(user_id, action):
    """("ok", value) | ("refused", status) | ("error", type) — an unexpected exception type is the bug we look for."""
    async with TestingSessionLocal() as session:
        try:
            return ("ok", await action(session, user_id))
        except HTTPException as exc:
            return ("refused", exc.status_code)
        except Exception as exc:  # noqa: BLE001
            return ("error", type(exc).__name__)


async def post_rows(project_id):
    async with TestingSessionLocal() as session:
        return (await session.execute(select(GeneratedContent).where(GeneratedContent.project_id == project_id))).scalars().all()


@pytest.mark.asyncio
async def test_simultaneous_first_generations_do_not_error_or_duplicate(authenticated_client, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    results = await asyncio.gather(*[
        attempt(user_id, lambda s, u: GenerationService(s, u).generate(UUID(project_id))) for _ in range(2)])
    assert not [r for r in results if r[0] == "error"], f"unexpected server errors: {results}"
    assert any(r[0] == "ok" for r in results)
    assert all(r == ("refused", 409) for r in results if r[0] != "ok")  # the loser gets a clear conflict, not a 500
    rows = await post_rows(UUID(project_id))
    assert len(rows) == 1  # one post per project/type/platform, never a duplicate


@pytest.mark.asyncio
async def test_simultaneous_approvals_approve_exactly_once(authenticated_client, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    async with TestingSessionLocal() as session:
        await EvaluationService(session, user_id).evaluate(UUID(project_id), 1)
    results = await asyncio.gather(*[
        attempt(user_id, lambda s, u: GenerationService(s, u).approve(UUID(project_id), 1)) for _ in range(3)])
    assert not [r for r in results if r[0] == "error"], f"unexpected server errors: {results}"
    assert any(r[0] == "ok" for r in results)
    assert all(r == ("refused", 409) for r in results if r[0] != "ok")  # the others are told it is already approved
    (post,) = await post_rows(UUID(project_id))
    assert post.status == "approved" and post.approved_version == post.version == 1 and post.approved_at is not None


@pytest.mark.asyncio
async def test_simultaneous_evaluations_do_not_error(authenticated_client, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    results = await asyncio.gather(*[
        attempt(user_id, lambda s, u: EvaluationService(s, u).evaluate(UUID(project_id), 1)) for _ in range(3)])
    assert not [r for r in results if r[0] == "error"], f"unexpected server errors: {results}"
    async with TestingSessionLocal() as session:
        count = (await session.execute(select(func.count(ContentEvaluation.id)).where(ContentEvaluation.project_id == UUID(project_id)))).scalar()
    assert count == len([r for r in results if r[0] == "ok"])  # history is append-only: one row per successful evaluation


@pytest.mark.asyncio
async def test_simultaneous_duplicate_competitors_get_a_conflict_not_an_error(authenticated_client, test_user):
    from app.models.competitor import Competitor
    from app.services.competitor_service import CompetitorService
    from tests.test_promotion_strategy import make_product

    user_id = test_user.id
    project_id, product_id = await make_product(authenticated_client)
    results = await asyncio.gather(*[
        attempt(user_id, lambda s, u: CompetitorService(s, u).create_competitor(UUID(product_id), {"name": "Racer Ltd"})) for _ in range(3)])
    assert not [r for r in results if r[0] == "error"], f"unexpected server errors: {results}"
    assert sum(r[0] == "ok" for r in results) == 1
    assert all(r == ("refused", 409) for r in results if r[0] != "ok")
    async with TestingSessionLocal() as session:
        count = (await session.execute(select(func.count(Competitor.id)).where(
            Competitor.product_id == UUID(product_id), Competitor.name == "Racer Ltd"))).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_simultaneous_registrations_of_one_email_create_one_account():
    import uuid

    from app.api.routes.auth import register_user
    from app.models.user import User
    from app.schemas.user import UserCreate

    email = f"race-{uuid.uuid4().hex[:10]}@example.com"

    async def register(session, _user_id):
        return await register_user(db=session, user_in=UserCreate(email=email, password="a-long-test-password"))

    results = await asyncio.gather(*[attempt(0, register) for _ in range(3)])
    assert not [r for r in results if r[0] == "error"], f"unexpected server errors: {results}"
    assert sum(r[0] == "ok" for r in results) == 1
    assert all(r == ("refused", 400) for r in results if r[0] != "ok")
    async with TestingSessionLocal() as session:
        assert (await session.execute(select(func.count(User.id)).where(User.email == email))).scalar() == 1


@pytest.mark.asyncio
async def test_simultaneous_first_settings_saves_both_succeed(authenticated_client, test_user):
    from sqlalchemy import delete

    from app.api.routes.user_settings import save_my_settings
    from app.models.user import User
    from app.models.user_settings import UserSettings
    from app.schemas.user_settings import UserSettingsUpdate

    user_id = test_user.id
    async with TestingSessionLocal() as session:  # start from "nothing saved yet"
        await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        await session.commit()

    async def save(session, uid, view):
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one()
        return await save_my_settings(UserSettingsUpdate(timezone=None, calendar_default_view=view, default_plan_time="10:00"),
                                      db=session, user=user)

    results = await asyncio.gather(attempt(user_id, lambda s, u: save(s, u, "week")), attempt(user_id, lambda s, u: save(s, u, "day")))
    assert [r[0] for r in results] == ["ok", "ok"], results  # a double save is never an error
    async with TestingSessionLocal() as session:
        rows = (await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))).scalars().all()
    assert len(rows) == 1 and rows[0].calendar_default_view in ("week", "day") and rows[0].default_plan_time == "10:00"


@pytest.mark.asyncio
async def test_registration_commit_conflict_is_a_clear_400(monkeypatch):
    """Deterministic version of the registration race: the email check passes, but the insert collides."""
    import uuid

    from sqlalchemy.exc import IntegrityError

    from app.api.routes.auth import register_user
    from app.schemas.user import UserCreate

    async with TestingSessionLocal() as session:
        async def colliding_commit():
            raise IntegrityError("INSERT INTO users", {}, Exception("duplicate key value violates unique constraint"))

        monkeypatch.setattr(session, "commit", colliding_commit)
        with pytest.raises(HTTPException) as caught:
            await register_user(db=session, user_in=UserCreate(email=f"c-{uuid.uuid4().hex[:8]}@example.com", password="a-long-test-password"))
    assert caught.value.status_code == 400 and "already exists" in caught.value.detail
