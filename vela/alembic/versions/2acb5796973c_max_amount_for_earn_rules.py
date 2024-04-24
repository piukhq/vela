"""max amount for earn rules

Revision ID: 2acb5796973c
Revises: 3b5af0db00a6
Create Date: 2022-04-11 12:33:22.777334

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "2acb5796973c"
down_revision = "3b5af0db00a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("earn_rule", sa.Column("max_amount", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("earn_rule", "max_amount")
