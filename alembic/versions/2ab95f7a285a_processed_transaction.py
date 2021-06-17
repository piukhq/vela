"""processed transaction

Revision ID: 2ab95f7a285a
Revises: 6435085f69d3
Create Date: 2021-06-15 13:56:51.934551

"""
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "2ab95f7a285a"
down_revision = "6435085f69d3"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "processed_transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=128), nullable=False),
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("account_holder_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.Integer(), nullable=True),
        sa.Column("campaign_slugs", postgresql.ARRAY(sa.String(length=128)), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer_rewards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "retailer_id", name="process_transaction_retailer_unq"),
    )
    op.create_index(op.f("ix_processed_transaction_id"), "processed_transaction", ["id"], unique=False)
    op.create_index(
        op.f("ix_processed_transaction_transaction_id"), "processed_transaction", ["transaction_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_processed_transaction_transaction_id"), table_name="processed_transaction")
    op.drop_index(op.f("ix_processed_transaction_id"), table_name="processed_transaction")
    op.drop_table("processed_transaction")
    # ### end Alembic commands ###