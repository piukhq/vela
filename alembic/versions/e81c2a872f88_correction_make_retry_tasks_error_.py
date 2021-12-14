"""correction - make retry_tasks.error_handler_path not null

Revision ID: e81c2a872f88
Revises: 5f7726d12bc5
Create Date: 2021-12-14 16:19:50.655555

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e81c2a872f88"
down_revision = "5f7726d12bc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("task_type", "error_handler_path", existing_type=sa.VARCHAR(), nullable=False)


def downgrade() -> None:
    pass
