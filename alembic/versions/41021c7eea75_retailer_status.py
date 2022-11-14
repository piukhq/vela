"""retailer status

Revision ID: 41021c7eea75
Revises: 6f65ef0de5de
Create Date: 2022-11-14 16:37:51.102470

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "41021c7eea75"
down_revision = "6f65ef0de5de"
branch_labels = None
depends_on = None

retailerstatuses = sa.Enum("TEST", "ACTIVE", "INACTIVE", "DELETED", "ARCHIVED", "SUSPENDED", name="retailerstatuses")


def upgrade() -> None:
    retailerstatuses.create(op.get_bind(), checkfirst=False)
    op.add_column("retailer_rewards", sa.Column("status", retailerstatuses, nullable=True))
    op.execute("UPDATE retailer_rewards SET status = 'TEST' WHERE status is NULL;")
    op.alter_column("retailer_rewards", "status", nullable=False)
    op.create_index(op.f("ix_retailer_rewards_status"), "retailer_rewards", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_retailer_rewards_status"), table_name="retailer_rewards")
    op.drop_column("retailer_rewards", "status")
    retailerstatuses.drop(op.get_bind(), checkfirst=False)
