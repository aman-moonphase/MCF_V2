"""Generated post version HISTORY: regenerating or hand-editing a post never loses the previous version.

GeneratedContent holds the current post and is overwritten in place (version + 1). generated_content_versions keeps every
version, including a person's hand edits. Isolated fixtures (Demo Mode); the migration is exercised against real rows
in a throwaway database.
"""
import datetime as dt
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from tests.test_generate_content import gen_url, generate, ready_project
from tests.test_promotion_strategy import other_client  # noqa: F401


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


def versions_url(project_id, suffix=""):
    return f"/api/projects/{project_id}/generated-content/versions{suffix}"


@pytest.mark.asyncio
async def test_edits_and_regeneration_keep_every_earlier_version(authenticated_client):
    c = authenticated_client
    project_id, _, _ = await ready_project(c)
    v1 = (await generate(c, project_id))["draft"]
    assert v1["version"] == 1
    original_hook = v1["content"]["hook"]

    edited_cta = "Message us this week to book a short walkthrough."
    edit = await c.patch(gen_url(project_id), json={"cta": edited_cta, "version": 1})
    assert edit.status_code == 200, edit.text
    assert edit.json()["draft"]["version"] == 2

    v3 = (await generate(c, project_id, pillar_index=1))["draft"]  # regenerate: overwrites the current post
    assert v3["version"] == 3

    listing = (await c.get(versions_url(project_id))).json()
    assert [r["version"] for r in listing] == [3, 2, 1], "newest first, nothing missing"
    by_version = {r["version"]: r for r in listing}
    assert by_version[2]["edited"] is True and by_version[1]["edited"] is False and by_version[3]["edited"] is False

    second = (await c.get(versions_url(project_id, "/2"))).json()
    assert second["content"]["cta"] == edited_cta, "the person's hand edit is preserved after regeneration replaced it"
    first = (await c.get(versions_url(project_id, "/1"))).json()
    assert first["content"]["hook"] == original_hook and first["content"]["cta"] != edited_cta
    assert first["context_snapshot"]["strategy_version"] is not None and first["is_demo"] is True

    current = (await c.get(gen_url(project_id))).json()["draft"]
    assert current["version"] == 3 and current["content"] == (await c.get(versions_url(project_id, "/3"))).json()["content"]


@pytest.mark.asyncio
async def test_approval_is_recorded_on_the_approved_version_only(authenticated_client):
    c = authenticated_client
    project_id, _, _ = await ready_project(c)
    await generate(c, project_id)
    await c.patch(gen_url(project_id), json={"cta": "Book a walkthrough today.", "version": 1})
    assert (await c.post(f"/api/projects/{project_id}/evaluation", json={"version": 2})).status_code == 200
    approved = await c.post(f"/api/projects/{project_id}/generated-content/approve", json={"version": 2})
    assert approved.status_code == 200, approved.text

    rows = {r["version"]: r for r in (await c.get(versions_url(project_id))).json()}
    assert rows[2]["status"] == "approved" and rows[2]["approved_at"]
    assert rows[1]["status"] == "draft" and rows[1]["approved_at"] is None
    assert (await c.get(versions_url(project_id, "/2"))).json()["content"]["cta"] == "Book a walkthrough today."


@pytest.mark.asyncio
async def test_post_history_is_private_to_the_owner(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    assert (await other_client.get(versions_url(project_id))).status_code == 404
    assert (await other_client.get(versions_url(project_id, "/1"))).status_code == 404
    assert (await authenticated_client.get(versions_url(project_id, "/99"))).status_code == 404
    assert (await authenticated_client.get(versions_url(uuid.uuid4()))).status_code == 404
    assert (await authenticated_client.get(versions_url(project_id))).status_code == 200


@pytest.mark.asyncio
async def test_migration_backfills_the_current_post_and_keeps_existing_data():
    """Upgrade a scratch database that already holds an approved post, from the revision before this feature to head."""
    backend = Path(__file__).resolve().parents[1]
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    name = f"mcf_db_chist_{uuid.uuid4().hex[:8]}"

    def pg(driver):
        return f"{base_url}/{name}".replace("postgresql+asyncpg://", f"{driver}://")

    async def admin(sql):
        conn = await asyncpg.connect(f"{base_url}/postgres".replace("postgresql+asyncpg://", "postgresql://"))
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    def alembic(target):
        env = {**os.environ, "DATABASE_URL": pg("postgresql+asyncpg"), "AI_PROVIDER": "demo"}
        done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=backend, env=env, capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr.replace(env["DATABASE_URL"], "<db>")[-1500:]

    await admin(f'CREATE DATABASE "{name}"')
    try:
        c0 = await asyncpg.connect(pg("postgresql"))
        await c0.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await c0.close()
        alembic("c2d3e4f5a6b7")

        conn = await asyncpg.connect(pg("postgresql"))
        try:
            async def insert(table, **given):
                cols = await conn.fetch("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = $1", table)
                values = dict(given)
                for c in cols:
                    n = c["column_name"]
                    if n in values or c["is_nullable"] == "YES" or c["column_default"] is not None:
                        continue
                    t = c["data_type"]
                    values[n] = (uuid.uuid4() if t == "uuid" else 1 if t in ("integer", "bigint") else False if t == "boolean" else
                                 "{}" if t in ("json", "jsonb") else dt.datetime.now(dt.timezone.utc) if "timestamp" in t else "x")
                marks = ", ".join(f"${i + 1}" + ("::jsonb" if isinstance(v, str) and v.startswith("{") else "") for i, v in enumerate(values.values()))
                await conn.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({marks})", *values.values())

            await insert("users", id=9001, email="m@example.com")
            project_id, product_id, content_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await insert("projects", id=project_id, user_id=9001)
            await insert("products", id=product_id, user_id=9001, name="Migrated")
            await insert("generated_contents", id=content_id, project_id=project_id, product_id=product_id, content='{"hook": "Original hook"}',
                         status="approved", version=23, approved_version=23, edited=False)
            before = await conn.fetchrow("SELECT content::text AS c, status, version, approved_version FROM generated_contents WHERE id = $1", content_id)
        finally:
            await conn.close()

        alembic("head")

        conn = await asyncpg.connect(pg("postgresql"))
        try:
            after = await conn.fetchrow("SELECT content::text AS c, status, version, approved_version FROM generated_contents WHERE id = $1", content_id)
            history = await conn.fetch("SELECT version, status, content::text AS c FROM generated_content_versions WHERE generated_content_id = $1", content_id)
        finally:
            await conn.close()
        assert dict(after) == dict(before), "the existing post was not modified"
        assert [(r["version"], r["status"]) for r in history] == [(23, "approved")], "one history row: the current approved version"
        assert history[0]["c"] == before["c"]
    finally:
        await admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
