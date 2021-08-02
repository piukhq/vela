"""reward adjustment

Revision ID: 4eadb28814a1
Revises: f00aa9d2ba8d
Create Date: 2021-07-05 14:51:49.093651

"""
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "4eadb28814a1"
down_revision = "f00aa9d2ba8d"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "reward_adjustment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "IN_PROGRESS", "FAILED", "SUCCESS", name="rewardadjustmentstatuses"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("adjustment_amount", sa.Integer(), nullable=False),
        sa.Column("campaign_slug", sa.String(), nullable=False),
        sa.Column("next_attempt_time", sa.DateTime(), nullable=True),
        sa.Column("response_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_token", sa.String(), nullable=False),
        sa.Column("processed_transaction_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["processed_transaction_id"], ["processed_transaction.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reward_adjustment_id"), "reward_adjustment", ["id"], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_reward_adjustment_id"), table_name="reward_adjustment")
    op.drop_table("reward_adjustment")
    op.execute("DROP TYPE rewardadjustmentstatuses")
    # ### end Alembic commands ###