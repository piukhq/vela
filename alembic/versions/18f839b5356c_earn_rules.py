"""earn rules

Revision ID: 18f839b5356c
Revises: 0f83098dbbd3
Create Date: 2021-05-14 15:29:16.369579

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "18f839b5356c"
down_revision = "0f83098dbbd3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "earn_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("increment", sa.Integer(), nullable=True),
        sa.Column("increment_multiplier", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_earn_rule_id"), "earn_rule", ["id"], unique=False)
    op.add_column("campaign", sa.Column("earn_inc_is_tx_value", sa.Boolean(), nullable=True))
    op.execute("UPDATE campaign SET earn_inc_is_tx_value=false")
    op.alter_column("campaign", "earn_inc_is_tx_value", nullable=False)


def downgrade() -> None:
    op.drop_column("campaign", "earn_inc_is_tx_value")
    op.drop_index(op.f("ix_earn_rule_id"), table_name="earn_rule")
    op.drop_table("earn_rule")
