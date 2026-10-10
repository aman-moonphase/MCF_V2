"""Calendar & content planning, step 1: schedule fields that tie a plan to a saved post version

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-10 20:00:00.000000

Schema only, backward compatible. Existing (legacy) schedule rows keep every value: the new columns are nullable,
except lock_version, which existing rows receive as 1 through its server default (no row is rewritten or relabelled,
and no product/post link is invented). Nothing is published or scheduled by this migration.

- product_id / generated_content_id: the product and the saved post a plan refers to. ON DELETE SET NULL (like
  projects.product_id) so a plan's history survives; content_version / content_digest still record what was planned.
- uq_schedules_active_plan: one active (not cancelled) plan per post version, platform and time. Cancelled plans and
  legacy rows without a post do not take part.
- ck_schedules_post_version: a plan that references a post must name the version, so the unique index applies.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_PLAN_WHERE = "cancelled_at IS NULL AND generated_content_id IS NOT NULL"


def upgrade() -> None:
    op.add_column('schedules', sa.Column('product_id', sa.UUID(), nullable=True))
    op.add_column('schedules', sa.Column('generated_content_id', sa.UUID(), nullable=True))
    op.add_column('schedules', sa.Column('content_version', sa.Integer(), nullable=True))
    op.add_column('schedules', sa.Column('content_digest', sa.String(length=64), nullable=True))
    op.add_column('schedules', sa.Column('content_type', sa.String(length=50), nullable=True))
    op.add_column('schedules', sa.Column('timezone', sa.String(length=64), nullable=True))
    op.add_column('schedules', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('schedules', sa.Column('lock_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('schedules', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key('fk_schedules_product_id', 'schedules', 'products', ['product_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_schedules_generated_content_id', 'schedules', 'generated_contents',
                          ['generated_content_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_schedules_post_version', 'schedules',
                               'generated_content_id IS NULL OR content_version IS NOT NULL')

    op.create_index('ix_schedules_product_id', 'schedules', ['product_id'])
    op.create_index('ix_schedules_generated_content_id', 'schedules', ['generated_content_id'])
    op.create_index('ix_schedules_scheduled_at', 'schedules', ['scheduled_at'])
    op.create_index('ix_schedules_project_id_scheduled_at', 'schedules', ['project_id', 'scheduled_at'])
    op.create_index('uq_schedules_active_plan', 'schedules',
                    ['generated_content_id', 'content_version', 'platform', 'scheduled_at'],
                    unique=True, postgresql_where=sa.text(ACTIVE_PLAN_WHERE))


def downgrade() -> None:
    op.drop_index('uq_schedules_active_plan', table_name='schedules')
    op.drop_index('ix_schedules_project_id_scheduled_at', table_name='schedules')
    op.drop_index('ix_schedules_scheduled_at', table_name='schedules')
    op.drop_index('ix_schedules_generated_content_id', table_name='schedules')
    op.drop_index('ix_schedules_product_id', table_name='schedules')
    op.drop_constraint('ck_schedules_post_version', 'schedules', type_='check')
    op.drop_constraint('fk_schedules_generated_content_id', 'schedules', type_='foreignkey')
    op.drop_constraint('fk_schedules_product_id', 'schedules', type_='foreignkey')
    for column in ('cancelled_at', 'lock_version', 'notes', 'timezone', 'content_type', 'content_digest',
                   'content_version', 'generated_content_id', 'product_id'):
        op.drop_column('schedules', column)
