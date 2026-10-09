"""product understanding: profile, clarifications, approval on products

Revision ID: e1f2a3b4c5d6
Revises: d9e3f4a5b6c7
Create Date: 2026-10-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd9e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('understanding_status', sa.String(length=50), nullable=False, server_default='not_started'))
    op.add_column('products', sa.Column('profile', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('products', sa.Column('clarification_questions', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('products', sa.Column('edited_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('products', sa.Column('profile_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('products', sa.Column('approved_version', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for column in ('approved_at', 'approved_version', 'profile_version', 'edited_fields',
                   'clarification_questions', 'profile', 'understanding_status'):
        op.drop_column('products', column)
