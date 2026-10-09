"""store full extracted source text on source_documents

Revision ID: b4f1c2a9d3e7
Revises: 7302286f21d7
Create Date: 2026-10-08 20:00:00.000000

The AI pipeline used projects.source_reference (VARCHAR(500)) as its source text, so long inputs
were truncated. The full extracted text now lives on the source document it came from.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f1c2a9d3e7'
down_revision: Union[str, None] = '7302286f21d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('source_documents', sa.Column('extracted_text', sa.Text(), nullable=True))
    # Text sources already kept their full text in metadata; copy it into the new column.
    # Other existing sources fall back to their ordered chunks at read time.
    op.execute(
        """
        UPDATE source_documents
        SET extracted_text = metadata->>'raw_text'
        WHERE extracted_text IS NULL AND metadata ? 'raw_text'
        """
    )


def downgrade() -> None:
    op.drop_column('source_documents', 'extracted_text')
