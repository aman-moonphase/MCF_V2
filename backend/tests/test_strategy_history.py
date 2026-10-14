"""Pillar 2: promotion strategy version HISTORY (the content of earlier versions survives later edits).

The current strategy is edited in place (version + 1). promotion_strategy_versions keeps what every version contained,
so an approved version can still be inspected after the strategy was edited. Isolated fixtures only (Demo Mode).
"""
import copy
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from tests.test_promotion_strategy import approve, approve_competitors, generate, make_product, other_client, url  # noqa: F401


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


def versions_url(product_id, suffix=""):
    return f"/api/products/{product_id}/strategy/versions{suffix}"


async def approved_strategy(client):
    project_id, product_id = await make_product(client)
    await approve_competitors(client, project_id, product_id)
    s = await generate(client, product_id)
    assert (await approve(client, project_id, product_id, s["version"])).status_code == 200
    return project_id, product_id, s


@pytest.mark.asyncio
async def test_an_approved_version_survives_later_edits(authenticated_client):
    project_id, product_id, s = await approved_strategy(authenticated_client)
    original = copy.deepcopy(s["strategy"])

    edited = {**s["strategy"]["audience"], "messaging_direction": "Lead with the weekly time saved, said plainly."}
    patched = await authenticated_client.patch(url(product_id), json={"strategy": {"audience": edited}})
    assert patched.status_code == 200, patched.text
    v2 = patched.json()["version"]
    assert v2 == s["version"] + 1 and patched.json()["status"] == "draft"

    listing = await authenticated_client.get(versions_url(product_id))
    assert listing.status_code == 200, listing.text
    rows = {r["version"]: r for r in listing.json()}
    assert sorted(rows, reverse=True) == [r["version"] for r in listing.json()], "newest first"
    assert rows[s["version"]]["status"] == "approved" and rows[s["version"]]["approved_at"], "v1 stays approved in history"
    assert rows[v2]["status"] == "draft" and "audience" in rows[v2]["edited_sections"]

    old = (await authenticated_client.get(versions_url(product_id, f"/{s['version']}"))).json()
    assert old["strategy"] == original, "the approved version still has exactly what was approved"
    assert old["strategy"]["audience"]["messaging_direction"] != edited["messaging_direction"]
    new = (await authenticated_client.get(versions_url(product_id, f"/{v2}"))).json()
    assert new["strategy"]["audience"]["messaging_direction"] == edited["messaging_direction"]
    assert new["strategy"]["content_pillars"] == original["content_pillars"], "untouched sections are unchanged"

    current = (await authenticated_client.get(url(product_id))).json()
    assert current["version"] == v2 and current["strategy"] == new["strategy"], "history agrees with the current strategy"


@pytest.mark.asyncio
async def test_approving_a_later_version_is_recorded_and_earlier_history_is_kept(authenticated_client):
    project_id, product_id, s = await approved_strategy(authenticated_client)
    v1 = s["version"]
    for i in range(2):
        res = await authenticated_client.patch(url(product_id), json={"strategy": {"audience": {
            **s["strategy"]["audience"], "messaging_direction": f"Direction {i + 1}"}}})
        assert res.status_code == 200, res.text
    v3 = v1 + 2
    assert (await approve(authenticated_client, project_id, product_id, v3)).status_code == 200

    listing = {r["version"]: r for r in (await authenticated_client.get(versions_url(product_id))).json()}
    assert sorted(listing) == [v1, v1 + 1, v3]
    assert [listing[v]["status"] for v in (v1, v1 + 1, v3)] == ["approved", "draft", "approved"]
    middle = (await authenticated_client.get(versions_url(product_id, f"/{v1 + 1}"))).json()
    assert middle["strategy"]["audience"]["messaging_direction"] == "Direction 1"


@pytest.mark.asyncio
async def test_a_rejected_edit_adds_no_version_and_changes_nothing(authenticated_client):
    project_id, product_id, s = await approved_strategy(authenticated_client)
    bad_channels = await authenticated_client.patch(url(product_id), json={"strategy": {"channels": []}})
    bad_section = await authenticated_client.patch(url(product_id), json={"strategy": {"not_a_section": {}}})
    assert bad_channels.status_code == 422 and bad_section.status_code == 422

    listing = (await authenticated_client.get(versions_url(product_id))).json()
    assert [r["version"] for r in listing] == [s["version"]] and listing[0]["status"] == "approved"
    current = (await authenticated_client.get(url(product_id))).json()
    assert current["version"] == s["version"] and current["status"] == "approved" and current["strategy"] == s["strategy"]


@pytest.mark.asyncio
async def test_strategy_history_is_private_to_the_owner(authenticated_client, other_client):
    project_id, product_id, s = await approved_strategy(authenticated_client)
    assert (await other_client.get(versions_url(product_id))).status_code == 404
    assert (await other_client.get(versions_url(product_id, f"/{s['version']}"))).status_code == 404
    assert (await authenticated_client.get(versions_url(product_id, "/999"))).status_code == 404
    assert (await authenticated_client.get(versions_url(uuid.uuid4()))).status_code == 404
    # The owner still sees it, so the 404s above are about ownership and not a broken route.
    assert (await authenticated_client.get(versions_url(product_id))).status_code == 200


# ─── The migration: backfill only the current version of strategies that already exist ──────────────────

@pytest.mark.asyncio
async def test_migration_backfills_the_current_strategy_and_keeps_existing_data():
    """Upgrade a scratch database that already holds a product and an approved strategy, from the revision before this
    feature to head. The existing strategy must be untouched and gain exactly one history row for its current version."""
    backend = Path(__file__).resolve().parents[1]
    base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    name = f"mcf_db_hist_{uuid.uuid4().hex[:8]}"

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
        done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=backend, env=env,
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr.replace(env["DATABASE_URL"], "<db>")[-1500:]

    await admin(f'CREATE DATABASE "{name}"')
    try:
        conn0 = await asyncpg.connect(pg("postgresql"))
        await conn0.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn0.close()
        alembic("b1c2d3e4f5a6")

        conn = await asyncpg.connect(pg("postgresql"))
        try:
            async def insert(table, **given):
                """Insert one row, filling any other NOT NULL column that has no default with a type-appropriate value."""
                cols = await conn.fetch(
                    "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = $1", table)
                values = dict(given)
                for c in cols:
                    n = c["column_name"]
                    if n in values or c["is_nullable"] == "YES" or c["column_default"] is not None:
                        continue
                    t = c["data_type"]
                    values[n] = (uuid.uuid4() if t == "uuid" else 1 if t in ("integer", "bigint") else
                                 False if t == "boolean" else "{}" if t in ("json", "jsonb") else
                                 __import__("datetime").datetime.now(__import__("datetime").timezone.utc) if "timestamp" in t else "x")
                names = ", ".join(values)
                marks = ", ".join(f"${i + 1}" + ("::jsonb" if isinstance(v, str) and v in ("{}",) else "") for i, v in enumerate(values.values()))
                await conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", *values.values())

            user_id = 9001
            await insert("users", id=user_id, email="m@example.com")
            product_id = uuid.uuid4()
            await insert("products", id=product_id, user_id=user_id, name="MigratedProduct")
            strategy_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO promotion_strategies (id, product_id, strategy, status, version, approved_version, approved_at) "
                "VALUES ($1, $2, $3::jsonb, 'approved', 12, 12, now())", strategy_id, product_id, '{"audience": {"primary_audience": "Freelancers"}}')
            before = await conn.fetchrow("SELECT strategy::text AS s, status, version, approved_version FROM promotion_strategies WHERE id = $1", strategy_id)
        finally:
            await conn.close()

        alembic("head")

        conn = await asyncpg.connect(pg("postgresql"))
        try:
            after = await conn.fetchrow("SELECT strategy::text AS s, status, version, approved_version FROM promotion_strategies WHERE id = $1", strategy_id)
            history = await conn.fetch("SELECT version, status, strategy::text AS s FROM promotion_strategy_versions WHERE product_id = $1", product_id)
            has_column = await conn.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name='projects' AND column_name='last_workflow_run'")
        finally:
            await conn.close()
        assert dict(after) == dict(before), "the existing strategy was not modified"
        assert [(r["version"], r["status"]) for r in history] == [(12, "approved")], "one history row: the current approved version"
        assert history[0]["s"] == before["s"]
        assert has_column == 1
    finally:
        await admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
