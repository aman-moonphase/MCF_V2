"""Redaction of secret-shaped text from anything returned to a client.

Provider SDKs and database drivers put credential fragments in exception messages (OpenAI: "Incorrect API key
provided: sk-proj-********abcd"; drivers: connection URLs with passwords), and some MCF code paths return exception
text in HTTP error details. `redact` removes
- the exact values of the configured secrets (API keys, SECRET_KEY, SMTP password, the database password),
- key-shaped tokens ("sk-…"), bearer tokens, connection URLs, and "password/token/secret/api key = value" pairs.
Ordinary messages are left unchanged. It is applied to every HTTP error body in app/main.py.
"""
import re
from typing import Any, List
from urllib.parse import unquote, urlsplit

REDACTED = "[redacted]"
# Exact-value replacement only for values that cannot be mistaken for ordinary words: a weak local value such as a
# database password that is literally "password" would otherwise garble messages like "Incorrect email or password".
# (Such values are still covered by the patterns below when they appear as "password=…" or in a connection URL.)
_MIN_SECRET_LENGTH = 12
_PLAIN_WORD = re.compile(r"^[a-z]+$")
_PLAIN_WORD_LIMIT = 16

_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{3,}[A-Za-z0-9*._\-]*"),  # sk-…, sk-ant-…, sk-proj-… (also masked: sk-proj-****abcd)
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s'\"<>]*@[^\s'\"<>]+"),  # any URL with credentials (user:pass@host)
    re.compile(r"(?i)\b(?:postgres(?:ql)?(?:\+\w+)?|mysql|redis|amqp|mongodb(?:\+srv)?)://[^\s'\"<>]+"),
    re.compile(r"(?i)\b(?:api[-_ ]?key|secret|token|password|passwd)\b(\s*[:=]\s*)[^\s,;'\"}\])]{4,}"),
]


def _configured_secrets() -> List[str]:
    from .config import settings

    values = [getattr(settings, name, None) for name in
              ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "POLLINATIONS_API_KEY", "REDDIT_CLIENT_SECRET", "SECRET_KEY", "SMTP_PASSWORD", "POSTGRES_PASSWORD")]
    try:
        parts = urlsplit(settings.DATABASE_URL)
        values += [unquote(parts.password) if parts.password else None]
    except Exception:
        pass
    usable = {v.strip() for v in values if isinstance(v, str) and len(v.strip()) >= _MIN_SECRET_LENGTH
              and not (_PLAIN_WORD.match(v.strip()) and len(v.strip()) < _PLAIN_WORD_LIMIT)}
    return sorted(usable, key=len, reverse=True)


def redact(text: Any) -> Any:
    """`text` with secrets removed (non-strings are returned unchanged)."""
    if not isinstance(text, str) or not text:
        return text
    # Patterns first (so "password=value" is recognised before a weak configured value such as a literal "password"
    # could be replaced inside the keyword), then the exact configured values.
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    for secret in _configured_secrets():
        text = text.replace(secret, REDACTED)
    return text


def redact_payload(value: Any) -> Any:
    """`redact` applied to every string inside nested dicts / lists (keys and non-strings are untouched)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(v) for v in value]
    return value
