"""Migration chain audit (Step 11): `alembic upgrade head` from an EMPTY database (what a fresh deployment runs) must
succeed and produce exactly the schema the models describe — tables, columns (type, nullability), foreign keys with
their ON DELETE rules, unique constraints and indexes. Uses two throwaway databases, dropped afterwards; the
application and shared test databases are never touched.
"""
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import create_engine, inspect

from app.core.config import settings
from app.db.base_class import Base
import app.db.base  # noqa: F401  (registers every model)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATED, MODELED = "mcf_db_chain_test_migrated", "mcf_db_chain_test_models"
BASE_URL = settings.DATABASE_URL.rsplit("/", 1)[0]


def _url(database: str, driver: str) -> str:
    return f"{BASE_URL}/{database}".replace("postgresql+asyncpg://", f"{driver}://")


async def _admin(sql: str) -> None:
    conn = await asyncpg.connect(_url("postgres", "postgresql"))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _fresh_database(name: str) -> None:
    await _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await _admin(f'CREATE DATABASE "{name}"')
    conn = await asyncpg.connect(_url(name, "postgresql"))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await conn.close()


def _schema(engine) -> dict:
    insp = inspect(engine)
    out = {}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        out[table] = {
            "columns": {c["name"]: (str(c["type"]).split("(")[0].upper(), bool(c["nullable"])) for c in insp.get_columns(table)},
            "foreign_keys": sorted((tuple(f["constrained_columns"]), f["referred_table"], (f.get("options") or {}).get("ondelete"))
                                   for f in insp.get_foreign_keys(table)),
            "uniques": sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(table)),
            "indexes": sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(table)),
        }
    return out


@pytest.mark.asyncio
async def test_upgrade_head_from_empty_matches_the_models():
    assert MIGRATED.endswith("_migrated") and MIGRATED != settings.DATABASE_URL.rsplit("/", 1)[1]
    try:
        await _fresh_database(MIGRATED)
        await _fresh_database(MODELED)
        env = {**os.environ, "DATABASE_URL": _url(MIGRATED, "postgresql+asyncpg"), "AI_PROVIDER": "demo"}
        done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr.replace(env["DATABASE_URL"], "<db>")[-1500:]

        migrated = create_engine(_url(MIGRATED, "postgresql+psycopg2"))
        modeled = create_engine(_url(MODELED, "postgresql+psycopg2"))
        try:
            Base.metadata.create_all(modeled)
            from_migrations, from_models = _schema(migrated), _schema(modeled)
        finally:
            migrated.dispose()
            modeled.dispose()
        assert len(from_models) >= 13, "the model schema should not be empty"
        assert set(from_migrations) == set(from_models), (set(from_migrations) ^ set(from_models))
        drift = {table: [key for key in from_models[table] if from_migrations[table][key] != from_models[table][key]]
                 for table in from_models if from_migrations[table] != from_models[table]}
        assert not drift, f"migrations and models disagree: {drift}"
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{MIGRATED}" WITH (FORCE)')
        await _admin(f'DROP DATABASE IF EXISTS "{MODELED}" WITH (FORCE)')
