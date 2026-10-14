"""Content images: creative image assets associated with generated post versions

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-10-12 00:00:00.000000

Adds content_images table for optional creative visual assets tied to post versions.
No existing data is altered; approved posts, evaluations, and workflow stages are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'content_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_content_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('content_version', sa.Integer(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('alt_text', sa.String(length=500), nullable=False),
        sa.Column('image_url', sa.Text(), nullable=False),
        sa.Column('aspect_ratio', sa.String(length=20), nullable=False, server_default='16:9'),
        sa.Column('style', sa.String(length=50), nullable=False, server_default='professional'),
        sa.Column('provider', sa.String(length=30), nullable=False, server_default='demo'),
        sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='generated'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['generated_content_id'], ['generated_contents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_content_images_project_id'), 'content_images', ['project_id'])
    op.create_index(op.f('ix_content_images_generated_content_id'), 'content_images', ['generated_content_id'])
    op.create_index(op.f('ix_content_images_content_version'), 'content_images', ['content_version'])


def downgrade() -> None:
    op.drop_index(op.f('ix_content_images_content_version'), table_name='content_images')
    op.drop_index(op.f('ix_content_images_generated_content_id'), table_name='content_images')
    op.drop_index(op.f('ix_content_images_project_id'), table_name='content_images')
    op.drop_table('content_images')
