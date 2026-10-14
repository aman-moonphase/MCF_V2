"""The Demo strategy only names a pillar after TIME saved when the approved value proposition is about time."""
import pytest

from tests.ai.test_strategy_refinement import PROFILE, demo_strategy


@pytest.mark.asyncio
async def test_a_privacy_value_proposition_does_not_claim_a_time_benefit():
    profile = {**PROFILE, "value_proposition": "A simple way for site owners to understand their traffic without surveilling their visitors."}
    names = [p["name"] for p in (await demo_strategy(profile))["content_pillars"]]
    assert "The benefit it delivers" in names and "The time it gives back" not in names


@pytest.mark.asyncio
async def test_a_time_based_value_proposition_keeps_the_time_pillar():
    names = [p["name"] for p in (await demo_strategy(PROFILE))["content_pillars"]]
    assert "The time it gives back" in names
