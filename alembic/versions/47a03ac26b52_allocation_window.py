"""allocation window

Revision ID: 47a03ac26b52
Revises: 6480cdb258da
Create Date: 2022-02-02 12:28:55.022778

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "47a03ac26b52"
down_revision = "6480cdb258da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reward_rule", sa.Column("allocation_window", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("reward_rule", "allocation_window")
