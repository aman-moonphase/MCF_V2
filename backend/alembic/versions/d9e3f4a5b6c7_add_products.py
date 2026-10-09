"""add products (one product -> many projects)

Revision ID: d9e3f4a5b6c7
Revises: c7d2e8f1a4b6
Create Date: 2026-10-08 20:10:00.000000

Schema-only preparation for the Product Understanding phase. projects.product_id is nullable,
so every existing project keeps working unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd9e3f4a5b6c7'
down_revision: Union[str, None] = 'c7d2e8f1a4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'products',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_products_user_id'), 'products', ['user_id'], unique=False)

    op.add_column('projects', sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_projects_product_id', 'projects', 'products', ['product_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index(op.f('ix_projects_product_id'), 'projects', ['product_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_projects_product_id'), table_name='projects')
    op.drop_constraint('fk_projects_product_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'product_id')
    op.drop_index(op.f('ix_products_user_id'), table_name='products')
    op.drop_table('products')
