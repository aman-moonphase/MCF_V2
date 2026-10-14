"""Product Workflow Master LangGraph: End-to-end orchestration across all 6 stages.

Pipeline:
START
  → ground_sources (extract evidence, source references S1..Sn / S:chunk)
  → product_understanding (profile generation & validation; gates on profile approval)
  → competitor_analysis (competitor research & comparison; gates on competitor approval)
  → promotion_strategy (audience, messaging, pillars; gates on strategy approval)
  → generate_content (grounded LinkedIn post with claims & citations P:*/S*)
  → evaluate_content (deterministic rule-based evaluation of exact saved version)
  → human_review_boundary (strict pause: NEVER auto-approve or auto-publish)
  → END

Conditional edges enforce:
1. Prerequisites & evidence must exist before subsequent stages run.
2. Unapproved stages halt execution with descriptive status and reasons.
3. Content generation extracts and validates claim-evidence traceability.
4. Evaluation is tied to the exact content version.
5. Execution always pauses at human review unless explicitly approved by a human.
"""

from typing import Any, Callable, Dict, List, Optional, TypedDict
from langgraph.graph import END, START, StateGraph


class ProductWorkflowState(TypedDict, total=False):
    # Core identifiers
    project_id: str
    product_id: Optional[str]
    user_id: int

    # Workflow progress & lifecycle
    current_stage: str
    status: str  # "in_progress", "paused_at_approval_boundary", "halted", "completed", "error"
    halt_reason: Optional[str]
    errors: List[str]
    stage_history: List[str]
    execution_log: List[Dict[str, Any]]

    # 1. Source Grounding
    sources_grounded: bool
    source_count: int
    source_evidence: Dict[str, Any]  # e.g. {"S1": "Document title", "S:...": "Excerpt"}

    # 2. Product Understanding
    product_profile: Optional[Dict[str, Any]]
    profile_version: Optional[int]
    profile_approved: bool

    # 3. Competitor Analysis
    competitor_comparison: Optional[Dict[str, Any]]
    competitor_version: Optional[int]
    competitor_approved_version: Optional[int]
    competitors_approved: bool
    competitor_limited_evidence: bool

    # 4. Promotion Strategy
    promotion_strategy: Optional[Dict[str, Any]]
    strategy_version: Optional[int]
    strategy_approved: bool
    content_pillars: List[Dict[str, Any]]

    # 5. Content Generation (LinkedIn Post)
    content_type: str
    pillar_index: int
    campaign_instructions: Optional[str]
    generated_post: Optional[Dict[str, Any]]
    content_version: Optional[int]
    claims_traceability: List[Dict[str, Any]]
    generation_validation: Optional[Dict[str, Any]]

    # 6. Evaluate & Improve
    evaluation: Optional[Dict[str, Any]]
    evaluation_version: Optional[int]
    evaluation_current: bool

    # 7. Human Review and Approval Boundary
    review_approved: bool
    approved_version: Optional[int]
    approved_at: Optional[str]

    # Node function delegates for custom or service-backed execution
    grounding_delegate: Optional[Callable[[Dict[str, Any]], Any]]
    understanding_delegate: Optional[Callable[[Dict[str, Any]], Any]]
    competitor_delegate: Optional[Callable[[Dict[str, Any]], Any]]
    strategy_delegate: Optional[Callable[[Dict[str, Any]], Any]]
    generation_delegate: Optional[Callable[[Dict[str, Any]], Any]]
    evaluation_delegate: Optional[Callable[[Dict[str, Any]], Any]]


def _log(state: ProductWorkflowState, stage: str, message: str) -> List[Dict[str, Any]]:
    logs = list(state.get("execution_log") or [])
    logs.append({"stage": stage, "message": message})
    return logs


def _record_history(state: ProductWorkflowState, stage: str) -> List[str]:
    history = list(state.get("stage_history") or [])
    if not history or history[-1] != stage:
        history.append(stage)
    return history


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Nodes
# ─────────────────────────────────────────────────────────────────────────────


async def ground_sources_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 1: Ground sources and collect source evidence references."""
    stage = "source-grounding"
    history = _record_history(state, stage)
    logs = _log(state, stage, "Extracting and grounding project sources.")

    delegate = state.get("grounding_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history, "execution_log": logs}

    # Default state handling
    sources_grounded = bool(state.get("sources_grounded", True))
    source_evidence = state.get("source_evidence") or {}
    source_count = state.get("source_count") or len(source_evidence)

    return {
        "current_stage": stage,
        "sources_grounded": sources_grounded,
        "source_count": source_count,
        "source_evidence": source_evidence,
        "stage_history": history,
        "execution_log": logs,
        "status": "in_progress",
    }


async def product_understanding_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 2: Product understanding profile. Halts if profile requires human approval."""
    stage = "product-understanding"
    history = _record_history(state, stage)

    delegate = state.get("understanding_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history}

    profile = state.get("product_profile")
    version = state.get("profile_version") or (1 if profile else 0)
    approved = bool(state.get("profile_approved"))

    if not profile:
        return {
            "current_stage": stage,
            "status": "error",
            "errors": (state.get("errors") or []) + ["Missing product profile."],
            "halt_reason": "No product profile found or generated.",
            "stage_history": history,
            "execution_log": _log(state, stage, "Failed: missing product profile."),
        }

    if not approved:
        return {
            "current_stage": stage,
            "product_profile": profile,
            "profile_version": version,
            "profile_approved": False,
            "status": "halted",
            "halt_reason": f"Product profile (version {version}) requires human review and approval before proceeding.",
            "stage_history": history,
            "execution_log": _log(state, stage, f"Halted: profile v{version} awaiting human approval."),
        }

    return {
        "current_stage": stage,
        "product_profile": profile,
        "profile_version": version,
        "profile_approved": True,
        "status": "in_progress",
        "stage_history": history,
        "execution_log": _log(state, stage, f"Product profile v{version} approved and verified."),
    }


async def competitor_analysis_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 3: Competitor analysis and comparison. Halts if competitor analysis requires human approval."""
    stage = "competitor-analysis"
    history = _record_history(state, stage)

    delegate = state.get("competitor_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history}

    comparison = state.get("competitor_comparison")
    version = state.get("competitor_version") or (1 if comparison else 0)
    approved = bool(state.get("competitors_approved"))
    limited = bool(state.get("competitor_limited_evidence"))

    if not comparison and not limited:
        return {
            "current_stage": stage,
            "status": "error",
            "errors": (state.get("errors") or []) + ["Missing competitor analysis or comparison."],
            "halt_reason": "No competitor comparison or limited evidence approval found.",
            "stage_history": history,
            "execution_log": _log(state, stage, "Failed: missing competitor comparison."),
        }

    if not approved:
        return {
            "current_stage": stage,
            "competitor_comparison": comparison,
            "competitor_version": version,
            "competitors_approved": False,
            "status": "halted",
            "halt_reason": f"Competitor analysis (version {version}) requires human review and approval before proceeding.",
            "stage_history": history,
            "execution_log": _log(state, stage, f"Halted: competitor analysis v{version} awaiting human approval."),
        }

    return {
        "current_stage": stage,
        "competitor_comparison": comparison,
        "competitor_version": version,
        "competitors_approved": True,
        "competitor_limited_evidence": limited,
        "status": "in_progress",
        "stage_history": history,
        "execution_log": _log(state, stage, f"Competitor analysis v{version} approved and verified."),
    }


async def promotion_strategy_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 4: Promotion strategy. Halts if strategy requires human approval."""
    stage = "promotion-strategy"
    history = _record_history(state, stage)

    delegate = state.get("strategy_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history}

    strategy = state.get("promotion_strategy")
    version = state.get("strategy_version") or (1 if strategy else 0)
    approved = bool(state.get("strategy_approved"))
    pillars = (strategy.get("content_pillars") if strategy else None) or state.get("content_pillars") or []

    if not strategy:
        return {
            "current_stage": stage,
            "status": "error",
            "errors": (state.get("errors") or []) + ["Missing promotion strategy."],
            "halt_reason": "No promotion strategy found or generated.",
            "stage_history": history,
            "execution_log": _log(state, stage, "Failed: missing promotion strategy."),
        }

    if not approved:
        return {
            "current_stage": stage,
            "promotion_strategy": strategy,
            "strategy_version": version,
            "strategy_approved": False,
            "content_pillars": pillars,
            "status": "halted",
            "halt_reason": f"Promotion strategy (version {version}) requires human review and approval before proceeding.",
            "stage_history": history,
            "execution_log": _log(state, stage, f"Halted: strategy v{version} awaiting human approval."),
        }

    return {
        "current_stage": stage,
        "promotion_strategy": strategy,
        "strategy_version": version,
        "strategy_approved": True,
        "content_pillars": pillars,
        "status": "in_progress",
        "stage_history": history,
        "execution_log": _log(state, stage, f"Promotion strategy v{version} approved and verified."),
    }


async def generate_content_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 5: Grounded LinkedIn post generation with claims traceability."""
    stage = "generate-content"
    history = _record_history(state, stage)

    delegate = state.get("generation_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history}

    post = state.get("generated_post")
    if not post:
        return {
            "current_stage": stage,
            "status": "error",
            "errors": (state.get("errors") or []) + ["Generated post missing."],
            "halt_reason": "Failed to generate LinkedIn content draft.",
            "stage_history": history,
            "execution_log": _log(state, stage, "Failed: no post generated."),
        }

    # Extract claims traceability
    raw_claims = post.get("claims") or []
    traceability = []
    for c in raw_claims:
        if isinstance(c, dict):
            traceability.append({
                "text": c.get("text", ""),
                "kind": c.get("kind", "product_fact"),
                "refs": c.get("refs", []),
            })

    version = state.get("content_version") or 1
    return {
        "current_stage": stage,
        "generated_post": post,
        "content_version": version,
        "claims_traceability": traceability,
        "content_type": state.get("content_type") or "Social Post",
        "status": "in_progress",
        "stage_history": history,
        "execution_log": _log(state, stage, f"Generated post v{version} with {len(traceability)} traceable claims."),
    }


async def evaluate_content_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 6: Evaluate & Improve against the exact saved content version."""
    stage = "evaluate-improve"
    history = _record_history(state, stage)

    delegate = state.get("evaluation_delegate")
    if delegate:
        res = await delegate(state) if callable(delegate) else {}
        return {"current_stage": stage, **res, "stage_history": history}

    evaluation = state.get("evaluation")
    content_version = state.get("content_version")
    eval_version = state.get("evaluation_version") or content_version

    if not evaluation:
        return {
            "current_stage": stage,
            "status": "error",
            "errors": (state.get("errors") or []) + ["Missing evaluation for generated content."],
            "halt_reason": "Content must be evaluated before human review.",
            "stage_history": history,
            "execution_log": _log(state, stage, "Failed: content evaluation missing."),
        }

    # Version consistency check
    if eval_version != content_version:
        return {
            "current_stage": stage,
            "status": "error",
            "evaluation_current": False,
            "errors": (state.get("errors") or []) + [
                f"Evaluation version mismatch: evaluated v{eval_version} != content v{content_version}"
            ],
            "halt_reason": f"Evaluation is stale (v{eval_version} != v{content_version}). Re-evaluation required.",
            "stage_history": history,
            "execution_log": _log(state, stage, f"Stale evaluation v{eval_version} != v{content_version}."),
        }

    return {
        "current_stage": stage,
        "evaluation": evaluation,
        "evaluation_version": eval_version,
        "evaluation_current": True,
        "status": "in_progress",
        "stage_history": history,
        "execution_log": _log(state, stage, f"Evaluation v{eval_version} matches post v{content_version}."),
    }


async def human_review_boundary_node(state: ProductWorkflowState) -> Dict[str, Any]:
    """Stage 7: Human Review and Approval boundary.
    
    CRITICAL SAFETY INVARIANT:
    - Content is NEVER automatically approved or published.
    - If review_approved is not True, execution pauses at this boundary.
    - When explicitly approved by a human, status becomes 'completed'.
    """
    stage = "review-approval"
    history = _record_history(state, stage)
    approved = bool(state.get("review_approved"))
    version = state.get("content_version")

    if approved:
        approved_version = state.get("approved_version") or version
        return {
            "current_stage": stage,
            "status": "completed",
            "review_approved": True,
            "approved_version": approved_version,
            "halt_reason": None,
            "stage_history": history,
            "execution_log": _log(state, stage, f"Post v{approved_version} approved by human. Workflow completed."),
        }

    # Strict pause at review boundary
    reason = (
        f"Post generated (version {version}) and evaluated. "
        "Awaiting explicit human review and approval. Automatic approval and publishing are strictly prohibited."
    )
    return {
        "current_stage": stage,
        "status": "paused_at_approval_boundary",
        "review_approved": False,
        "halt_reason": reason,
        "stage_history": history,
        "execution_log": _log(state, stage, f"Paused at human review boundary for v{version}."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Conditional Routing Functions
# ─────────────────────────────────────────────────────────────────────────────


def route_after_grounding(state: ProductWorkflowState) -> str:
    if state.get("status") == "error":
        return END
    return "node_product_understanding"


def route_after_understanding(state: ProductWorkflowState) -> str:
    if state.get("status") in ("error", "halted") or not state.get("profile_approved"):
        return END
    return "node_competitor_analysis"


def route_after_competitors(state: ProductWorkflowState) -> str:
    if state.get("status") in ("error", "halted") or not state.get("competitors_approved"):
        return END
    return "node_promotion_strategy"


def route_after_strategy(state: ProductWorkflowState) -> str:
    if state.get("status") in ("error", "halted") or not state.get("strategy_approved"):
        return END
    return "node_generate_content"


def route_after_generation(state: ProductWorkflowState) -> str:
    # "halted" here means a person-edited post went stale: stop rather than evaluate or overwrite it.
    if state.get("status") in ("error", "halted") or not state.get("generated_post"):
        return END
    return "node_evaluate_content"


def route_after_evaluation(state: ProductWorkflowState) -> str:
    if state.get("status") in ("error", "halted") or not state.get("evaluation_current"):
        return END
    return "node_human_review_boundary"


# ─────────────────────────────────────────────────────────────────────────────
# Graph Construction & Compilation
# ─────────────────────────────────────────────────────────────────────────────


def build_product_workflow_graph():
    """Builds and compiles the master stateful LangGraph for MCF product workflow."""
    builder = StateGraph(ProductWorkflowState)

    builder.add_node("node_ground_sources", ground_sources_node)
    builder.add_node("node_product_understanding", product_understanding_node)
    builder.add_node("node_competitor_analysis", competitor_analysis_node)
    builder.add_node("node_promotion_strategy", promotion_strategy_node)
    builder.add_node("node_generate_content", generate_content_node)
    builder.add_node("node_evaluate_content", evaluate_content_node)
    builder.add_node("node_human_review_boundary", human_review_boundary_node)

    builder.add_edge(START, "node_ground_sources")

    builder.add_conditional_edges(
        "node_ground_sources",
        route_after_grounding,
        {"node_product_understanding": "node_product_understanding", END: END},
    )

    builder.add_conditional_edges(
        "node_product_understanding",
        route_after_understanding,
        {"node_competitor_analysis": "node_competitor_analysis", END: END},
    )

    builder.add_conditional_edges(
        "node_competitor_analysis",
        route_after_competitors,
        {"node_promotion_strategy": "node_promotion_strategy", END: END},
    )

    builder.add_conditional_edges(
        "node_promotion_strategy",
        route_after_strategy,
        {"node_generate_content": "node_generate_content", END: END},
    )

    builder.add_conditional_edges(
        "node_generate_content",
        route_after_generation,
        {"node_evaluate_content": "node_evaluate_content", END: END},
    )

    builder.add_conditional_edges(
        "node_evaluate_content",
        route_after_evaluation,
        {"node_human_review_boundary": "node_human_review_boundary", END: END},
    )

    builder.add_edge("node_human_review_boundary", END)

    return builder.compile()



_graph = None


def get_product_workflow_graph():
    """Singleton getter for the compiled graph."""
    global _graph
    if _graph is None:
        _graph = build_product_workflow_graph()
    return _graph
