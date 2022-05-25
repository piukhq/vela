"""transaction.status column

Revision ID: 80f584ab1fcc
Revises: 56f574e9e809
Create Date: 2022-05-25 09:05:55.810806

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "80f584ab1fcc"
down_revision = "56f574e9e809"
branch_labels = None
depends_on = None

transactionprocessingstatuses = sa.Enum(
    "PROCESSED", "DUPLICATE", "NO_ACTIVE_CAMPAIGNS", name="transactionprocessingstatuses"
)


def upgrade() -> None:
    transactionprocessingstatuses.create(op.get_bind())
    op.add_column(
        "transaction",
        sa.Column(
            "status",
            transactionprocessingstatuses,
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_transaction_status"), "transaction", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_transaction_status"), table_name="transaction")
    op.drop_column("transaction", "status")
    transactionprocessingstatuses.drop(op.get_bind())
