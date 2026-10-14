"""Generated post version history

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-14 00:00:00.000000

Adds generated_content_versions (one row per post version, including hand edits) so regenerating or editing a post
never loses the previous version. Existing posts are backfilled with one row for their CURRENT version only (earlier
versions were overwritten in place and cannot be recovered). No existing post, evaluation or approval is modified.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_content_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_content_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('edited', sa.Boolean(), nullable=False),
        sa.Column('context_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('is_demo', sa.Boolean(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['generated_content_id'], ['generated_contents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('generated_content_id', 'version', name='uq_generated_content_version'),
    )
    op.create_index(op.f('ix_generated_content_versions_generated_content_id'), 'generated_content_versions', ['generated_content_id'], unique=False)
    op.create_index(op.f('ix_generated_content_versions_project_id'), 'generated_content_versions', ['project_id'], unique=False)
    op.execute(
        """
        INSERT INTO generated_content_versions
            (id, generated_content_id, project_id, version, content, validation, status, edited, context_snapshot, provider,
             is_demo, generated_at, edited_at, approved_at, created_at, updated_at)
        SELECT gen_random_uuid(), id, project_id, version, content, validation,
               CASE WHEN status = 'approved' AND approved_version = version THEN 'approved' ELSE 'draft' END,
               COALESCE(edited, false), context_snapshot, provider, COALESCE(is_demo, false), generated_at, edited_at,
               CASE WHEN status = 'approved' AND approved_version = version THEN approved_at ELSE NULL END,
               created_at, updated_at
        FROM generated_contents
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_content_versions_project_id'), table_name='generated_content_versions')
    op.drop_index(op.f('ix_generated_content_versions_generated_content_id'), table_name='generated_content_versions')
    op.drop_table('generated_content_versions')
