"""store table

Revision ID: fc93be5fcde2
Revises: 80f584ab1fcc
Create Date: 2022-05-30 12:16:17.630195

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "fc93be5fcde2"
down_revision = "80f584ab1fcc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retailer_store",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("store_name", sa.String(), nullable=False),
        sa.Column("mid", sa.String(), nullable=False),
        sa.Column("retailer_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer_rewards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mid"),
    )


def downgrade() -> None:
    op.drop_table("retailer_store")
