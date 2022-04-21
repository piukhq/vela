"""add retry_task.status index

Revision ID: 8ae0833855f3
Revises: 2acb5796973c
Create Date: 2022-04-20 16:42:54.629399

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "8ae0833855f3"
down_revision = "2acb5796973c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_retry_task_status"), "retry_task", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_retry_task_status"), table_name="retry_task")
