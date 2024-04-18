"""increase max length of campaign slug

Revision ID: b3cb4a2f8231
Revises: 7058002812c0
Create Date: 2023-01-17 11:36:16.392015

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b3cb4a2f8231"
down_revision = "7058002812c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "campaign", "slug", existing_type=sa.VARCHAR(length=32), type_=sa.String(length=100), existing_nullable=False
    )


def downgrade() -> None:
    pass
