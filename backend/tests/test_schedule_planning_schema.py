"""Calendar & content planning, step 1 (schema only): alembic f6a7b8c9d0e1.

- The real migration is run with Alembic against a throwaway database (`mcf_db_schedule_migration_test`, created and
  dropped here): legacy schedule rows keep every original value, get no invented links, and survive a downgrade.
- The schema produced by the models (the test database) is checked for nullability, defaults, foreign keys, the
  check constraint and the partial unique index, and matches the migrated schema.
No application database is touched and nothing is published or scheduled.
"""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.schedule import Schedule

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION_DB = "mcf_db_schedule_migration_test"
BEFORE, AFTER = "e5f6a7b8c9d0", "f6a7b8c9d0e1"
ORIGINAL_COLUMNS = ("id", "project_id", "platform", "scheduled_at", "status", "created_at", "updated_at")
NEW_COLUMNS = {  # name -> (data type, nullable, default)
    "product_id": ("uuid", "YES", None),
    "generated_content_id": ("uuid", "YES", None),
    "content_version": ("integer", "YES", None),
    "content_digest": ("character varying", "YES", None),
    "content_type": ("character varying", "YES", None),
    "timezone": ("character varying", "YES", None),
    "notes": ("text", "YES", None),
    "lock_version": ("integer", "NO", "1"),
    "cancelled_at": ("timestamp with time zone", "YES", None),
}
SCHEMA_OBJECTS = {
    "ix_schedules_product_id", "ix_schedules_generated_content_id", "ix_schedules_scheduled_at",
    "ix_schedules_project_id_scheduled_at", "uq_schedules_active_plan",
}
CONSTRAINTS = {
    "fk_schedules_product_id": "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL",
    "fk_schedules_generated_content_id": "FOREIGN KEY (generated_content_id) REFERENCES generated_contents(id) ON DELETE SET NULL",
    "ck_schedules_post_version": "CHECK (((generated_content_id IS NULL) OR (content_version IS NOT NULL)))",
}


def _url(database: str, driver: str = "postgresql+asyncpg") -> str:
    base = settings.DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{database}".replace("postgresql+asyncpg://", f"{driver}://")


def _alembic(*args: str) -> None:
    """Run Alembic for the throwaway database only (DATABASE_URL overrides .env in the child process)."""
    url = _url(MIGRATION_DB)
    assert url.endswith("_test") and url != settings.DATABASE_URL
    env = {**os.environ, "DATABASE_URL": url, "AI_PROVIDER": "demo"}
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr.replace(url, "<migration-test-db>")[-2000:]


async def _schema(conn) -> tuple:
    columns = {r["column_name"]: (r["data_type"], r["is_nullable"], r["column_default"]) for r in await conn.fetch(
        "select column_name, data_type, is_nullable, column_default from information_schema.columns "
        "where table_name = 'schedules'")}
    indexes = {r["indexname"]: r["indexdef"] for r in await conn.fetch(
        "select indexname, indexdef from pg_indexes where tablename = 'schedules'")}
    constraints = {r["conname"]: r["def"] for r in await conn.fetch(
        "select conname, pg_get_constraintdef(oid) as def from pg_constraint where conrelid = 'schedules'::regclass")}
    return columns, indexes, constraints


@pytest.fixture
async def migration_db():
    admin = await asyncpg.connect(_url("postgres", "postgresql"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"')
        await admin.execute(f'CREATE DATABASE "{MIGRATION_DB}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_url(MIGRATION_DB, "postgresql"))
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield conn
    finally:
        await conn.close()
        admin = await asyncpg.connect(_url("postgres", "postgresql"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest.mark.asyncio
async def test_migration_preserves_legacy_schedules(migration_db):
    conn = migration_db
    _alembic("upgrade", BEFORE)

    user_id = await conn.fetchval("insert into users (email, hashed_password, is_active) values ('legacy@example.com', 'x', true) returning id")
    projects = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    for i, pid in enumerate(projects):
        await conn.execute("insert into projects (id, title, status, source_type, source_reference, current_stage, user_id) "
                           "values ($1, $2, 'Draft', 'Text Idea', 'x', 'source-grounding', $3)", pid, f"Legacy {i}", user_id)
    utc = timezone.utc
    legacy = [  # five legacy rows shaped like the real ones: several per project, past and future, odd status strings
        (uuid.uuid4(), projects[0], "LinkedIn", datetime(2026, 9, 29, 21, 35, tzinfo=utc), "Scheduled",
         datetime(2026, 9, 23, 9, 28, 53, 914327, tzinfo=utc), datetime(2026, 9, 23, 9, 28, 53, 914327, tzinfo=utc)),
        (uuid.uuid4(), projects[0], "LinkedIn", datetime(2026, 9, 30, 3, 30, tzinfo=utc), "Scheduled",
         datetime(2026, 9, 23, 9, 22, 17, 146273, tzinfo=utc), datetime(2026, 9, 24, 1, 0, tzinfo=utc)),
        (uuid.uuid4(), projects[1], "YouTube", datetime(2026, 10, 1, 12, 0, tzinfo=utc), "Completed",
         datetime(2026, 9, 23, 6, 33, 37, 492576, tzinfo=utc), datetime(2026, 9, 23, 6, 33, 37, 492576, tzinfo=utc)),
        (uuid.uuid4(), projects[2], "LinkedIn", datetime(2026, 10, 20, 3, 30, tzinfo=utc), "Draft", None, None),
        (uuid.uuid4(), projects[2], "LinkedIn", datetime(2026, 10, 20, 3, 30, tzinfo=utc), "Scheduled",  # same slot twice
         datetime(2026, 10, 8, 14, 59, 3, 54778, tzinfo=utc), datetime(2026, 10, 8, 14, 59, 3, 54778, tzinfo=utc)),
    ]
    await conn.executemany(f"insert into schedules ({', '.join(ORIGINAL_COLUMNS)}) values ($1, $2, $3, $4, $5, $6, $7)", legacy)
    select_original = f"select {', '.join(ORIGINAL_COLUMNS)} from schedules order by id"
    before = [tuple(r) for r in await conn.fetch(select_original)]
    assert len(before) == 5

    _alembic("upgrade", AFTER)
    assert await conn.fetchval("select version_num from alembic_version") == AFTER
    assert [tuple(r) for r in await conn.fetch(select_original)] == before  # every original value unchanged
    extra = await conn.fetch(f"select {', '.join(NEW_COLUMNS)} from schedules")
    assert all(r["lock_version"] == 1 and all(r[c] is None for c in NEW_COLUMNS if c != "lock_version") for r in extra)

    columns, indexes, constraints = await _schema(conn)
    assert {c: columns[c] for c in NEW_COLUMNS} == NEW_COLUMNS
    assert {c: columns[c][1] for c in ORIGINAL_COLUMNS} == {  # original columns keep their nullability
        "id": "NO", "project_id": "NO", "platform": "NO", "scheduled_at": "NO", "status": "NO",
        "created_at": "YES", "updated_at": "YES"}
    assert set(indexes) == SCHEMA_OBJECTS | {"schedules_pkey"}
    assert {k: v for k, v in constraints.items() if k in CONSTRAINTS} == CONSTRAINTS

    # The models (used to build the test database) describe the same schema as the migration.
    from tests.conftest import test_engine
    async with test_engine.connect() as model_conn:
        raw = await model_conn.get_raw_connection()
        model_columns, model_indexes, model_constraints = await _schema(raw.driver_connection)
    assert model_columns == columns
    assert model_indexes == indexes
    assert {k: v for k, v in model_constraints.items() if k in CONSTRAINTS} == CONSTRAINTS

    # Downgrade removes only the new objects; the legacy rows are still intact.
    _alembic("downgrade", BEFORE)
    assert [tuple(r) for r in await conn.fetch(select_original)] == before
    columns, indexes, _ = await _schema(conn)
    assert set(columns) == set(ORIGINAL_COLUMNS) and set(indexes) == {"schedules_pkey"}


# ─── Constraint behaviour on the model schema (test database) ───────────────

async def _post(db):
    """A product, campaign and approved post owned by a dedicated user, so these rows never show up in other tests'
    schedule listings."""
    from app.models.user import User
    owner = User(email=f"planning-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    product = Product(user_id=owner.id, name=f"Plan {uuid.uuid4().hex[:6]}")
    db.add(product)
    await db.flush()
    project = Project(title="Campaign", source_type="Text Idea", source_reference="x", user_id=owner.id, product_id=product.id)
    db.add(project)
    await db.flush()
    post = GeneratedContent(project_id=project.id, product_id=product.id, content_type="Social Post", platform="linkedin",
                            content={"hook": "x"}, status="approved", version=2, approved_version=2)
    db.add(post)
    await db.commit()
    # Plain snapshots: ORM objects expire after the rollbacks these tests provoke.
    return (SimpleNamespace(id=product.id), SimpleNamespace(id=project.id),
            SimpleNamespace(id=post.id, product_id=post.product_id, version=post.version, content_type=post.content_type))


def _plan(project, post=None, when=datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc), **extra):
    fields = dict(project_id=project.id, platform="LinkedIn", scheduled_at=when, status="Scheduled")
    if post is not None:
        fields.update(product_id=post.product_id, generated_content_id=post.id, content_version=post.version,
                      content_digest="a" * 64, content_type=post.content_type, timezone="Asia/Kolkata")
    return Schedule(**fields, **extra)


@pytest.mark.asyncio
async def test_new_fields_defaults_and_legacy_rows(db_session):
    _, project, _ = await _post(db_session)
    legacy = [_plan(project), _plan(project), _plan(project)]  # same slot, no post: legacy rows stay valid
    db_session.add_all(legacy)
    await db_session.commit()
    for row in legacy:
        await db_session.refresh(row)
        assert row.lock_version == 1
        assert (row.product_id, row.generated_content_id, row.content_version, row.content_digest, row.content_type,
                row.timezone, row.notes, row.cancelled_at) == (None,) * 8
    # The database default applies to raw inserts too (as for rows that existed before the migration).
    sid = uuid.uuid4()
    await db_session.execute(text("insert into schedules (id, project_id, platform, scheduled_at, status, created_at, updated_at) "
                                  "values (:id, :p, 'LinkedIn', now(), 'Scheduled', now(), now())"), {"id": sid, "p": project.id})
    await db_session.commit()
    assert (await db_session.execute(text("select lock_version from schedules where id = :id"), {"id": sid})).scalar() == 1


@pytest.mark.asyncio
async def test_duplicate_active_plan_is_rejected(db_session):
    _, project, post = await _post(db_session)
    db_session.add(_plan(project, post))
    await db_session.commit()
    db_session.add(_plan(project, post))
    with pytest.raises(IntegrityError, match="uq_schedules_active_plan"):
        await db_session.commit()
    await db_session.rollback()
    # Not duplicates: another platform, another time, or another version of the same post.
    other_platform = _plan(project, post)
    other_platform.platform = "Blog"
    other_time = _plan(project, post, when=datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
    other_version = _plan(project, post)
    other_version.content_version = 3
    db_session.add_all([other_platform, other_time, other_version])
    await db_session.commit()


@pytest.mark.asyncio
async def test_cancelled_plan_does_not_block_a_replacement(db_session):
    _, project, post = await _post(db_session)
    first = _plan(project, post)
    db_session.add(first)
    await db_session.commit()
    first.cancelled_at = datetime.now(timezone.utc)
    await db_session.commit()
    replacement = _plan(project, post)
    db_session.add(replacement)
    await db_session.commit()
    second_cancelled = _plan(project, post, cancelled_at=datetime.now(timezone.utc))  # cancelled rows never collide
    db_session.add(second_cancelled)
    await db_session.commit()
    db_session.add(_plan(project, post))  # but a second ACTIVE plan for the same slot still does
    with pytest.raises(IntegrityError, match="uq_schedules_active_plan"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_post_reference_requires_a_version(db_session):
    _, project, post = await _post(db_session)
    plan = _plan(project, post)
    plan.content_version = None
    db_session.add(plan)
    with pytest.raises(IntegrityError, match="ck_schedules_post_version"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["product_id", "generated_content_id"])
async def test_foreign_keys_reject_unknown_references(db_session, field):
    _, project, post = await _post(db_session)
    plan = _plan(project, post)
    setattr(plan, field, uuid.uuid4())
    db_session.add(plan)
    with pytest.raises(IntegrityError, match=f"fk_schedules_{field}"):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_deleting_references_keeps_the_plan_history(db_session):
    product, project, post = await _post(db_session)
    plan = _plan(project, post)
    db_session.add(plan)
    await db_session.commit()
    plan_id = plan.id

    await db_session.execute(text("delete from generated_contents where id = :id"), {"id": post.id})
    await db_session.commit()
    row = (await db_session.execute(text("select generated_content_id, content_version, content_digest, product_id "
                                         "from schedules where id = :id"), {"id": plan_id})).one()
    assert row[0] is None and row[1] == 2 and row[2] == "a" * 64 and row[3] == product.id  # what was planned is kept

    await db_session.execute(text("delete from products where id = :id"), {"id": product.id})
    await db_session.commit()
    row = (await db_session.execute(text("select product_id, project_id from schedules where id = :id"), {"id": plan_id})).one()
    assert row[0] is None and row[1] == project.id  # project link (and the plan) survive; projects keep product SET NULL

    await db_session.execute(text("delete from projects where id = :id"), {"id": project.id})
    await db_session.commit()
    assert (await db_session.execute(text("select count(*) from schedules where id = :id"), {"id": plan_id})).scalar() == 0
