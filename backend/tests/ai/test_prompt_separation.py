"""Real providers must receive production prompts: shared rules + project context + stage
instructions, and never the Demo Mode instructions."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.prompts import GLOBAL_RELEVANCE_REQUIREMENT, PROVIDER_SYSTEM_PROMPT, SHARED_SYSTEM_RULES, build_stage_prompt
from app.ai.providers.demo_provider import DEMO_MODE_RULES
from app.ai.nodes import (
    content_selection_nodes, content_strategy_nodes, content_type_nodes, platform_strategy_nodes,
    script_nodes, storyboard_nodes, topic_angle_nodes,
)

FULL_STATE = {
    "input_text": "LedgerLeaf is a bookkeeping app for freelance designers.",
    "approved_content_type": "Carousel",
    "selected_opportunity": {"id": "opt-1", "title": "LedgerLeaf basics", "summary": "s", "potentialAudience": "designers"},
    "selected_platforms": [{"platform": "LinkedIn", "recommendedFormat": "Carousel on LinkedIn"}],
    "selected_angle": {"title": "How LedgerLeaf works", "angle": "Educational", "hook": "h", "corePromise": "c"},
    "approved_strategy": {"objective": "o", "format": "Carousel", "platformAdaptations": []},
    "approved_storyboard": {"scenes": [{"order": 1, "title": "Hook", "narration": "n", "transition": "Swipe"}]},
    "grounding_context": {"text": "Retrieved chunk about GST invoices."},
    "intent": "analysis",
    "error": None,
    "retries": 0,
}

NODES = [
    (content_type_nodes, content_type_nodes.recommend_type, None),
    (content_selection_nodes, content_selection_nodes.generate_recommendations, content_selection_nodes.analyze_source),
    (platform_strategy_nodes, platform_strategy_nodes.generate_platforms, platform_strategy_nodes.analyze_content),
    (topic_angle_nodes, topic_angle_nodes.generate_angles, topic_angle_nodes.analyze_context),
    (content_strategy_nodes, content_strategy_nodes.generate_strategy, content_strategy_nodes.analyze_context),
    (storyboard_nodes, storyboard_nodes.generate_storyboard, storyboard_nodes.analyze_context),
    (script_nodes, script_nodes.generate_script, script_nodes.analyze_storyboard_context),
]


def test_shared_rules_contain_no_demo_instructions():
    assert "DEMO MODE" not in SHARED_SYSTEM_RULES
    assert "Demo Mode" not in SHARED_SYSTEM_RULES
    assert GLOBAL_RELEVANCE_REQUIREMENT == SHARED_SYSTEM_RULES
    assert "demo" not in PROVIDER_SYSTEM_PROMPT.lower()
    # The demo rules still exist — but only with the DemoProvider.
    assert "DEMO MODE" in DEMO_MODE_RULES


def test_build_stage_prompt_has_three_ordered_parts():
    prompt = build_stage_prompt("Test Stage", [("Source Material", "abc"), ("Empty", None)], "Do the task.")
    rules_at = prompt.index("GLOBAL REQUIREMENT")
    context_at = prompt.index("CURRENT PROJECT CONTEXT")
    task_at = prompt.index("STAGE INSTRUCTIONS — Test Stage")
    assert rules_at < context_at < task_at
    assert "Source Material: abc" in prompt
    assert "Empty" not in prompt  # empty context values are skipped


@pytest.mark.asyncio
@pytest.mark.parametrize("module, generate, analyze", NODES)
async def test_every_stage_prompt_is_production_clean(module, generate, analyze):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=RuntimeError("stop after capturing the prompt"))
    provider.generate_text = AsyncMock(return_value="analysis")

    with patch.object(module, "get_provider", return_value=provider):
        await generate(dict(FULL_STATE))
        if analyze:
            await analyze(dict(FULL_STATE))

    prompts = [c.args[0] for c in provider.generate_structured.call_args_list]
    prompts += [c.args[0] for c in provider.generate_text.call_args_list]
    assert prompts
    for prompt in prompts:
        assert "DEMO MODE" not in prompt
        assert "Demo Mode" not in prompt
        assert "GLOBAL REQUIREMENT — CONTENT RELEVANCE & CONTEXTUAL CONSISTENCY" in prompt
        assert "CURRENT PROJECT CONTEXT" in prompt
        assert "STAGE INSTRUCTIONS" in prompt


@pytest.mark.asyncio
# The content-type node is excluded: the type is chosen at that stage, so nothing is approved yet.
@pytest.mark.parametrize("module, generate, analyze", [n for n in NODES if n[0] is not content_type_nodes])
async def test_generate_prompts_carry_the_approved_type_constraint(module, generate, analyze):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=RuntimeError("capture"))
    with patch.object(module, "get_provider", return_value=provider):
        await generate(dict(FULL_STATE))
    prompt = provider.generate_structured.call_args.args[0]
    assert "APPROVED CONTENT TYPE — HARD CONSTRAINT: Carousel" in prompt
    assert "LedgerLeaf is a bookkeeping app for freelance designers." in prompt


@pytest.mark.asyncio
async def test_openai_provider_sends_system_and_user_messages():
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.ai.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(api_key="sk-test")
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
    provider.llm = fake_llm

    assert await provider.generate_text("USER PROMPT") == "ok"
    messages = fake_llm.ainvoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage) and messages[0].content == PROVIDER_SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage) and messages[1].content == "USER PROMPT"
