from typing import Dict, Any, List
from ..content_types import require_content_type
from ..graphs.demo_graph import build_demo_graph
from ..graphs.content_type_graph import build_content_type_graph
from ..graphs.content_selection_graph import build_content_selection_graph
from ..graphs.platform_strategy_graph import build_platform_strategy_graph
from ..graphs.topic_angle_graph import build_topic_angle_graph
from ..graphs.content_strategy_graph import build_content_strategy_graph
from ..graphs.storyboard_graph import build_storyboard_graph
from ..graphs.script_graph import build_script_graph


def _initial_state(input_text: str, grounding_context: dict | None = None, approved_content_type: str | None = None, **selections) -> Dict[str, Any]:
    return {
        "input_text": input_text,
        # The approved type is a hard constraint: it must be one of the six supported values.
        "approved_content_type": require_content_type(approved_content_type) if approved_content_type else None,
        "selected_opportunity": selections.get("selected_opportunity"),
        "selected_platforms": selections.get("selected_platforms"),
        "selected_angle": selections.get("selected_angle"),
        "approved_strategy": selections.get("approved_strategy"),
        "approved_storyboard": selections.get("approved_storyboard"),
        "grounding_context": grounding_context or {},
        "intent": None,
        "keywords": None,
        "structured_output": None,
        "error": None,
        "retries": 0,
    }


class AIOrchestrator:
    def __init__(self):
        self.demo_graph = build_demo_graph()
        self.content_type_graph = build_content_type_graph()
        self.content_selection_graph = build_content_selection_graph()
        self.platform_strategy_graph = build_platform_strategy_graph()
        self.topic_angle_graph = build_topic_angle_graph()
        self.content_strategy_graph = build_content_strategy_graph()
        self.storyboard_graph = build_storyboard_graph()
        self.script_graph = build_script_graph()

    @staticmethod
    async def _run(graph, initial_state: Dict[str, Any], label: str) -> Dict[str, Any]:
        try:
            final_state = await graph.ainvoke(initial_state)

            if final_state.get("error"):
                raise ValueError(f"Graph execution failed: {final_state['error']}")

            return final_state.get("structured_output", {})
        except Exception as e:
            raise RuntimeError(f"{label}: {str(e)}")

    async def run_content_type(self, input_text: str, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the content type graph to recommend a content format."""
        return await self._run(self.content_type_graph, _initial_state(input_text, grounding_context), "Content Type AI Error")

    async def run_content_plan(self, input_text: str, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the demo graph to generate a content plan."""
        return await self._run(self.demo_graph, _initial_state(input_text, grounding_context), "AI Orchestration Error")

    async def run_content_selection(self, input_text: str, approved_content_type: str | None = None, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the content selection graph to generate content opportunities."""
        state = _initial_state(input_text, grounding_context, approved_content_type)
        return await self._run(self.content_selection_graph, state, "Content Selection AI Error")

    async def run_platform_strategy(self, input_text: str, selected_opportunity: dict, approved_content_type: str | None = None, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the platform strategy graph to generate platform recommendations."""
        state = _initial_state(input_text, grounding_context, approved_content_type, selected_opportunity=selected_opportunity)
        return await self._run(self.platform_strategy_graph, state, "Platform Strategy AI Error")

    async def run_topic_angle(self, input_text: str, selected_opportunity: dict, selected_platforms: List[dict], approved_content_type: str | None = None, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the topic angle graph to generate content angles."""
        state = _initial_state(
            input_text, grounding_context, approved_content_type,
            selected_opportunity=selected_opportunity, selected_platforms=selected_platforms,
        )
        return await self._run(self.topic_angle_graph, state, "Topic Angle AI Error")

    async def run_content_strategy(self, input_text: str, selected_opportunity: dict, selected_platforms: List[dict], selected_angle: dict, approved_content_type: str | None = None, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the content strategy graph to generate a full strategy."""
        state = _initial_state(
            input_text, grounding_context, approved_content_type,
            selected_opportunity=selected_opportunity, selected_platforms=selected_platforms, selected_angle=selected_angle,
        )
        return await self._run(self.content_strategy_graph, state, "Content Strategy AI Error")

    async def run_storyboard(self, input_text: str, selected_opportunity: dict, selected_platforms: List[dict], selected_angle: dict, approved_strategy: dict, approved_content_type: str | None = None, grounding_context: dict | None = None) -> Dict[str, Any]:
        """Executes the storyboard graph to generate scenes."""
        state = _initial_state(
            input_text, grounding_context, approved_content_type,
            selected_opportunity=selected_opportunity, selected_platforms=selected_platforms,
            selected_angle=selected_angle, approved_strategy=approved_strategy,
        )
        return await self._run(self.storyboard_graph, state, "Storyboard AI Error")

    async def run_script(
        self,
        input_text: str,
        selected_opportunity: dict,
        selected_platforms: List[dict],
        selected_angle: dict,
        approved_strategy: dict,
        approved_storyboard: dict,
        approved_content_type: str | None = None,
        grounding_context: dict | None = None
    ) -> Dict[str, Any]:
        """
        Executes the script graph to generate a final, publish-ready script
        by expanding each approved storyboard scene into a full script section.
        """
        state = _initial_state(
            input_text, grounding_context, approved_content_type,
            selected_opportunity=selected_opportunity, selected_platforms=selected_platforms,
            selected_angle=selected_angle, approved_strategy=approved_strategy, approved_storyboard=approved_storyboard,
        )
        return await self._run(self.script_graph, state, "Script AI Error")
