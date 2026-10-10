"""generated content: grounded LinkedIn post drafts + Generate Content stage for product projects

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_contents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('platform', sa.String(length=30), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('edited', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('context_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('is_demo', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'content_type', 'platform', name='uq_generated_content_project_type_platform'),
    )
    op.create_index(op.f('ix_generated_contents_project_id'), 'generated_contents', ['project_id'])
    op.create_index(op.f('ix_generated_contents_product_id'), 'generated_contents', ['product_id'])
    # Product-workflow projects created before this stage existed get a (Locked) Generate Content row.
    op.execute("""
        INSERT INTO workflow_stages (id, project_id, stage_type, status, created_at, updated_at)
        SELECT gen_random_uuid(), ws.project_id, 'generate-content', 'Locked', now(), now()
        FROM workflow_stages ws
        WHERE ws.stage_type = 'product-understanding'
          AND NOT EXISTS (SELECT 1 FROM workflow_stages g
                          WHERE g.project_id = ws.project_id AND g.stage_type = 'generate-content')
    """)


def downgrade() -> None:
    op.execute("DELETE FROM workflow_stages WHERE stage_type = 'generate-content'")
    op.drop_index(op.f('ix_generated_contents_product_id'), table_name='generated_contents')
    op.drop_index(op.f('ix_generated_contents_project_id'), table_name='generated_contents')
    op.drop_table('generated_contents')
