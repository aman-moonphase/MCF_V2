"""Tests must never send real email, even when backend/.env contains real SMTP credentials."""
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_password_reset_email_goes_to_the_fake_smtp_outbox(authenticated_client, test_user, db_session, smtp_outbox):
    test_user.password_reset_requested_at = None
    await db_session.commit()

    with patch("app.core.config.settings.SMTP_HOST", "smtp.example.invalid"), \
         patch("app.core.config.settings.SMTP_USER", "sender@example.invalid"), \
         patch("app.core.config.settings.SMTP_PASSWORD", "not-a-real-password"):
        res = await authenticated_client.post("/api/auth/forgot-password", json={"email": test_user.email})

    assert res.status_code == 200
    assert len(smtp_outbox) == 1
    assert smtp_outbox[0]["to"] == test_user.email
    assert "reset-password?token=" in smtp_outbox[0]["message"]
