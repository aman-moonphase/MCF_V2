"""Server-side password policy (Step 11): the browser's minLength is only a convenience."""
import uuid

import pytest


def email():
    return f"policy-{uuid.uuid4().hex[:8]}@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["", "a", "1234567", "x" * 129])
async def test_registration_refuses_out_of_policy_passwords(client, password):
    res = await client.post("/api/auth/register", json={"email": email(), "password": password})
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_registration_and_login_with_a_valid_password(client):
    address = email()
    created = await client.post("/api/auth/register", json={"email": address, "password": "eight-ok"})  # exactly 8
    assert created.status_code == 200, created.text
    assert "password" not in created.text.lower() or "hashed" not in created.text.lower()
    login = await client.post("/api/auth/login/access-token", data={"username": address, "password": "eight-ok"})
    assert login.status_code == 200 and login.json()["access_token"]


@pytest.mark.asyncio
async def test_reset_refuses_out_of_policy_passwords(client):
    for password in ("short", "x" * 129):
        res = await client.post("/api/auth/reset-password", json={"token": "1:abc", "new_password": password})
        assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_login_still_accepts_existing_short_passwords(client, db_session):
    """The policy applies to NEW passwords only: an existing account with a short password can still sign in."""
    from app.core.security import get_password_hash
    from app.models.user import User

    address = email()
    db_session.add(User(email=address, hashed_password=get_password_hash("short"), is_active=True))
    await db_session.commit()
    login = await client.post("/api/auth/login/access-token", data={"username": address, "password": "short"})
    assert login.status_code == 200
