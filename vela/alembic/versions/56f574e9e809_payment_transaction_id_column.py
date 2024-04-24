"""payment_transaction_id_column

Revision ID: 56f574e9e809
Revises: 8ae0833855f3
Create Date: 2022-05-09 10:35:10.394353

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "56f574e9e809"
down_revision = "8ae0833855f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processed_transaction", sa.Column("payment_transaction_id", sa.String(length=128), nullable=True))
    op.create_index(
        op.f("ix_processed_transaction_payment_transaction_id"),
        "processed_transaction",
        ["payment_transaction_id"],
        unique=False,
    )
    op.add_column("transaction", sa.Column("payment_transaction_id", sa.String(length=128), nullable=True))
    op.create_index(
        op.f("ix_transaction_payment_transaction_id"), "transaction", ["payment_transaction_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transaction_payment_transaction_id"), table_name="transaction")
    op.drop_column("transaction", "payment_transaction_id")
    op.drop_index(op.f("ix_processed_transaction_payment_transaction_id"), table_name="processed_transaction")
    op.drop_column("processed_transaction", "payment_transaction_id")
