"""Usage and estimated cost of real AI provider requests.

Every Claude request is recorded with metadata only — model, workflow stage, attempt, token counts (including
cache tokens when the API reports them), duration and success/failure. Prompts, source text, responses and API
keys are never recorded or logged.

Records are written to the application log, and collected for the current operation when a caller opens
`collect_usage()` (Generate Content stores the summary on the saved post). Demo Mode makes no requests, so it
produces no records and no cost.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger("mcf.ai.usage")

_collector: ContextVar[Optional[List[dict]]] = ContextVar("mcf_usage_collector", default=None)

COST_DISCLAIMER = ("Estimate only, from MCF's configured per-model rates (USD per million tokens). The Anthropic "
                   "Console is the source of truth for actual charges.")
PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing (rates as configured in MCF, checked 2026-10)"


@dataclass(frozen=True)
class ModelRates:
    """USD per million tokens."""
    input: float
    output: float
    cache_write: float  # 5-minute cache write
    cache_read: float
    note: str = ""


# Central, model-specific rates. A model missing here gets token counts but no cost estimate (never a guess).
CLAUDE_RATES: Dict[str, ModelRates] = {
    "claude-fable-5-1": ModelRates(input=10.0, output=50.0, cache_write=12.5, cache_read=0.25),
    "claude-opus-5-5": ModelRates(input=4.0, output=20.0, cache_write=5.0, cache_read=0.20),
    "claude-sonnet-5-5": ModelRates(input=2.0, output=10.0, cache_write=2.5, cache_read=0.10),
    "claude-sonnet-5": ModelRates(input=2.0, output=10.0, cache_write=2.5, cache_read=0.20),
    "claude-haiku-5-5": ModelRates(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01,
                                   note="Haiku 5.5 is priced 'from' these rates; the actual rate may be higher."),
}


def estimate_cost_usd(model: str, input_tokens: Optional[int], output_tokens: Optional[int],
                      cache_creation_tokens: Optional[int] = None, cache_read_tokens: Optional[int] = None) -> Optional[float]:
    """Estimated USD for one request, or None when the model has no configured rates or no tokens were reported."""
    rates = CLAUDE_RATES.get(model)
    if rates is None or (input_tokens is None and output_tokens is None):
        return None
    total = ((input_tokens or 0) * rates.input + (output_tokens or 0) * rates.output
             + (cache_creation_tokens or 0) * rates.cache_write + (cache_read_tokens or 0) * rates.cache_read) / 1_000_000
    return round(total, 6)


def record_usage(entry: dict) -> None:
    """Log one request's metadata and add it to the active collector, if any."""
    logger.info(
        "ai_request provider=%s model=%s stage=%s attempt=%s status=%s input_tokens=%s output_tokens=%s "
        "cache_creation_input_tokens=%s cache_read_input_tokens=%s duration_ms=%s est_cost_usd=%s",
        entry.get("provider"), entry.get("model"), entry.get("stage"), entry.get("attempt"), entry.get("status"),
        entry.get("input_tokens"), entry.get("output_tokens"), entry.get("cache_creation_input_tokens"),
        entry.get("cache_read_input_tokens"), entry.get("duration_ms"), entry.get("estimated_cost_usd"),
    )
    collected = _collector.get()
    if collected is not None:
        collected.append(entry)


@contextmanager
def collect_usage() -> Iterator[List[dict]]:
    """Collect the usage records of the requests made inside this block (one operation, one request scope)."""
    records: List[dict] = []
    token = _collector.set(records)
    try:
        yield records
    finally:
        _collector.reset(token)


def summarize_usage(records: List[dict], generated_version: int) -> Optional[dict]:
    """The usage summary stored with a generated post, or None when no real provider request was made."""
    if not records:
        return None
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    totals = {k: sum(r.get(k) or 0 for r in records) for k in keys}
    costs = [r.get("estimated_cost_usd") for r in records if r.get("status") == "ok"]
    estimate = round(sum(costs), 6) if costs and all(c is not None for c in costs) else None
    models = sorted({r.get("model") for r in records if r.get("model")})
    notes = sorted({CLAUDE_RATES[m].note for m in models if m in CLAUDE_RATES and CLAUDE_RATES[m].note})
    return {
        "generated_version": generated_version,
        "provider": records[0].get("provider"),
        "models": models,
        "request_count": len(records),
        "failed_requests": sum(1 for r in records if r.get("status") != "ok"),
        "totals": totals,
        "duration_ms": sum(r.get("duration_ms") or 0 for r in records),
        "estimated_cost_usd": estimate,
        "cost_is_estimate": True,
        "cost_note": COST_DISCLAIMER + (" " + " ".join(notes) if notes else "")
                     + ("" if estimate is not None else " No estimate: no configured rate for this model."),
        "pricing_source": PRICING_SOURCE,
        "requests": records,
    }
