"""Evaluate & Improve: content evaluation history + the new stage for in-progress product projects

Revision ID: e5f6a7b8c9d0
Revises: d0e1f2a3b4c5
Create Date: 2026-10-10 14:00:00.000000

Stage backfill rules (existing data is never changed, only a stage row is added):
- only product-workflow projects (they have a product-understanding row) without an evaluate-improve row;
- never completed work: skipped when the project is Completed, its Review Approval is Completed, or its post is
  approved — those keep exactly the stages they were completed with;
- the new row is Locked, or In Progress when Generate Content is already Completed (so the user can evaluate
  before Review Approval). No other row, status, post or approval is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL_EVALUATE_STAGE_SQL = """
INSERT INTO workflow_stages (id, project_id, stage_type, status, created_at, updated_at)
SELECT gen_random_uuid(), p.id, 'evaluate-improve',
       CASE WHEN EXISTS (SELECT 1 FROM workflow_stages g WHERE g.project_id = p.id
                         AND g.stage_type = 'generate-content' AND g.status = 'Completed')
            THEN 'In Progress' ELSE 'Locked' END,
       now(), now()
FROM projects p
WHERE EXISTS (SELECT 1 FROM workflow_stages m WHERE m.project_id = p.id AND m.stage_type = 'product-understanding')
  AND NOT EXISTS (SELECT 1 FROM workflow_stages e WHERE e.project_id = p.id AND e.stage_type = 'evaluate-improve')
  AND p.status <> 'Completed'
  AND NOT EXISTS (SELECT 1 FROM workflow_stages r WHERE r.project_id = p.id
                  AND r.stage_type = 'review-approval' AND r.status = 'Completed')
  AND NOT EXISTS (SELECT 1 FROM generated_contents c WHERE c.project_id = p.id AND c.status = 'approved')
"""


def upgrade() -> None:
    op.create_table(
        'content_evaluations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_content_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('content_version', sa.Integer(), nullable=False),
        sa.Column('evaluator', sa.String(length=50), nullable=False),
        sa.Column('mode', sa.String(length=30), nullable=False),
        sa.Column('overall', sa.String(length=40), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['generated_content_id'], ['generated_contents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_content_evaluations_generated_content_id'), 'content_evaluations', ['generated_content_id'])
    op.create_index(op.f('ix_content_evaluations_project_id'), 'content_evaluations', ['project_id'])
    op.execute(BACKFILL_EVALUATE_STAGE_SQL)


def downgrade() -> None:
    op.execute("DELETE FROM workflow_stages WHERE stage_type = 'evaluate-improve'")
    op.drop_index(op.f('ix_content_evaluations_project_id'), table_name='content_evaluations')
    op.drop_index(op.f('ix_content_evaluations_generated_content_id'), table_name='content_evaluations')
    op.drop_table('content_evaluations')
