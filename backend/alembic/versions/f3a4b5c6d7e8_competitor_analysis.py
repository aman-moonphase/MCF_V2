"""competitor analysis: competitors, competitor evidence, product-level analysis state

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'competitors',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('website_url', sa.String(length=1024), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('origin', sa.String(length=30), nullable=False),
        sa.Column('suggestion_reason', sa.Text(), nullable=True),
        sa.Column('analysis_status', sa.String(length=30), nullable=False),
        sa.Column('analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('analysis_error', sa.Text(), nullable=True),
        sa.Column('last_analyzed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'name', name='uq_competitors_product_name'),
    )
    op.create_index(op.f('ix_competitors_product_id'), 'competitors', ['product_id'], unique=False)

    op.create_table(
        'competitor_evidence',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('competitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('evidence_type', sa.String(length=20), nullable=False),
        sa.Column('source_url', sa.String(length=1024), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['competitor_id'], ['competitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_competitor_evidence_competitor_id'), 'competitor_evidence', ['competitor_id'], unique=False)
    op.create_index(op.f('ix_competitor_evidence_product_id'), 'competitor_evidence', ['product_id'], unique=False)

    op.add_column('products', sa.Column('competitor_analysis_status', sa.String(length=50), nullable=False, server_default='not_started'))
    op.add_column('products', sa.Column('competitor_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('products', sa.Column('competitor_comparison', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('products', sa.Column('competitor_comparison_version', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('competitor_comparison_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('products', sa.Column('competitor_approved_version', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('competitor_approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for column in ('competitor_approved_at', 'competitor_approved_version', 'competitor_comparison_at',
                   'competitor_comparison_version', 'competitor_comparison', 'competitor_version',
                   'competitor_analysis_status'):
        op.drop_column('products', column)
    op.drop_index(op.f('ix_competitor_evidence_product_id'), table_name='competitor_evidence')
    op.drop_index(op.f('ix_competitor_evidence_competitor_id'), table_name='competitor_evidence')
    op.drop_table('competitor_evidence')
    op.drop_index(op.f('ix_competitors_product_id'), table_name='competitors')
    op.drop_table('competitors')
