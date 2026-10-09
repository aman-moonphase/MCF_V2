"""Canonical workflow stage definition — the single source of truth for stage keys, order and labels.

Everything else derives from WORKFLOW_STAGES:
- new projects get one stage row per definition (ProjectService.create_project);
- stages are returned in this order and carry `label`/`order` in API responses, which the
  frontend renders directly (no stage list is duplicated in the frontend);
- stage writes are validated against these keys.

Adding a stage later (e.g. "product-understanding", "competitor-analysis", "promotion-strategy",
"evaluate") means inserting one StageDefinition at the right position here, then giving it a UI
component in frontend/src/components/projects/stage-registry.tsx and, if it is AI-driven, an
endpoint. Existing projects will need a data migration to add the new rows (see
WorkflowStageService.ensure_project_stages).
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class StageDefinition:
    key: str
    label: str
    description: str


WORKFLOW_STAGES: Tuple[StageDefinition, ...] = (
    StageDefinition("source-grounding", "Source Grounding", "Ingest and ground the project's source material."),
    StageDefinition("product-understanding", "Product Understanding", "Learn and approve a structured Product Profile from the sources."),
    StageDefinition("competitor-analysis", "Competitor Analysis", "Analyse competitors from supplied evidence and compare them with the approved product."),
    StageDefinition("promotion-strategy", "Promotion Strategy", "Plan how to promote the product, grounded in the profile and competitor intelligence."),
    StageDefinition("content-type", "Content Type", "Choose the one content type this project will produce."),
    StageDefinition("content-selection", "Content Selection", "Pick a content opportunity from the source."),
    StageDefinition("platform-strategy", "Platform Strategy", "Choose the platforms for the approved content type."),
    StageDefinition("topic-angle", "Topic & Angle", "Choose the angle and hook."),
    StageDefinition("content-strategy", "Content Strategy", "Define the blueprint for this piece of content."),
    StageDefinition("storyboard", "Storyboard", "Plan the ordered units (scenes, slides, sections)."),
    StageDefinition("final-script", "Final Script", "Produce the publish-ready copy."),
    StageDefinition("review-approval", "Review Approval", "Human review and approval."),
)

# Stage types that exist in older databases but can no longer be created through the API.
LEGACY_STAGE_KEYS = frozenset({"script"})

_DEFINITIONS: Dict[str, StageDefinition] = {stage.key: stage for stage in WORKFLOW_STAGES}
_ORDER: Dict[str, int] = {stage.key: index for index, stage in enumerate(WORKFLOW_STAGES)}

FIRST_STAGE_STATUS = "Not Started"
LOCKED_STAGE_STATUS = "Locked"


def get_stage_definition(key: str) -> Optional[StageDefinition]:
    return _DEFINITIONS.get(key)


def is_known_stage(key: str) -> bool:
    return key in _DEFINITIONS


def stage_order(key: str) -> int:
    """Position of a stage in the workflow; unknown/legacy stages sort after all known ones."""
    return _ORDER.get(key, len(WORKFLOW_STAGES))


def stage_label(key: str) -> str:
    definition = _DEFINITIONS.get(key)
    if definition:
        return definition.label
    return " ".join(part.capitalize() for part in key.split("-"))


def initial_status(index: int) -> str:
    return FIRST_STAGE_STATUS if index == 0 else LOCKED_STAGE_STATUS
