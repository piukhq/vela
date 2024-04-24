"""add reward_cap enum column to reward_rule table

Revision ID: 823f35823186
Revises: ade88ecebf6b
Create Date: 2022-08-23 13:39:01.204573

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "823f35823186"
down_revision = "ade88ecebf6b"
branch_labels = None
depends_on = None


rewardcaps = sa.Enum("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", name="rewardcaps")


def upgrade() -> None:
    rewardcaps.create(op.get_bind())
    op.add_column(
        "reward_rule",
        sa.Column("reward_cap", rewardcaps, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reward_rule", "reward_cap")
    rewardcaps.drop(op.get_bind())
