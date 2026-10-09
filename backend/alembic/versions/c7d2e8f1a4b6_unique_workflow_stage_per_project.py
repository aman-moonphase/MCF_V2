"""one workflow stage row per (project, stage_type)

Revision ID: c7d2e8f1a4b6
Revises: b4f1c2a9d3e7
Create Date: 2026-10-08 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c7d2e8f1a4b6'
down_revision: Union[str, None] = 'b4f1c2a9d3e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove pre-existing duplicates (if any) before adding the constraint: keep the row that has
    # data, then the most recently updated one.
    op.execute(
        """
        DELETE FROM workflow_stages ws
        USING (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY project_id, stage_type
                       ORDER BY (data IS NULL), updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                   ) AS rn
            FROM workflow_stages
        ) ranked
        WHERE ws.id = ranked.id AND ranked.rn > 1
        """
    )
    op.create_unique_constraint(
        'uq_workflow_stages_project_stage', 'workflow_stages', ['project_id', 'stage_type']
    )


def downgrade() -> None:
    op.drop_constraint('uq_workflow_stages_project_stage', 'workflow_stages', type_='unique')
