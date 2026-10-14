"""Promotion strategy version history and last workflow run trace

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-14 00:00:00.000000

Adds promotion_strategy_versions (one row per strategy version, so approved versions survive later edits) and
projects.last_workflow_run (trace of the latest workflow run). Existing strategies are backfilled with one row for
their CURRENT version only (earlier versions were overwritten in place and cannot be recovered). No existing
strategy, post, evaluation or approval is modified.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'promotion_strategy_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('strategy', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edited_sections', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('basis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'version', name='uq_strategy_version_product_version'),
    )
    op.create_index(op.f('ix_promotion_strategy_versions_product_id'), 'promotion_strategy_versions', ['product_id'], unique=False)
    op.add_column('projects', sa.Column('last_workflow_run', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # Backfill: the current version of every existing strategy (earlier versions no longer exist).
    op.execute(
        """
        INSERT INTO promotion_strategy_versions
            (id, product_id, version, strategy, status, approved_at, edited_sections, basis, provider, created_at, updated_at)
        SELECT gen_random_uuid(), product_id, version, strategy,
               CASE WHEN status = 'approved' AND approved_version = version THEN 'approved' ELSE 'draft' END,
               CASE WHEN status = 'approved' AND approved_version = version THEN approved_at ELSE NULL END,
               edited_sections, basis, provider, created_at, updated_at
        FROM promotion_strategies
        """
    )


def downgrade() -> None:
    op.drop_column('projects', 'last_workflow_run')
    op.drop_index(op.f('ix_promotion_strategy_versions_product_id'), table_name='promotion_strategy_versions')
    op.drop_table('promotion_strategy_versions')
