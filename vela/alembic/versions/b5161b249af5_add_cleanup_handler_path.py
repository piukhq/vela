"""add cleanup handler path

Revision ID: b5161b249af5
Revises: 02b35d82ec64
Create Date: 2022-10-06 16:53:13.053391

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b5161b249af5"
down_revision = "02b35d82ec64"
branch_labels = None
depends_on = None


old_options = ("PENDING", "IN_PROGRESS", "RETRYING", "FAILED", "SUCCESS", "WAITING", "CANCELLED", "REQUEUED")
new_options = (
    "PENDING",
    "IN_PROGRESS",
    "RETRYING",
    "FAILED",
    "SUCCESS",
    "WAITING",
    "CANCELLED",
    "REQUEUED",
    "CLEANUP",
    "CLEANUP_FAILED",
)
enum_name = "retrytaskstatuses"
old_type = sa.Enum(*old_options, name=enum_name)
new_type = sa.Enum(*new_options, name=enum_name)
tmp_type = sa.Enum(*new_options, name="_retrytaskstatuses_old")


def upgrade() -> None:
    # ADD CLEANUP TO ENUM
    tmp_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE retry_task ALTER COLUMN status TYPE _retrytaskstatuses_old USING status::text::_retrytaskstatuses_old"
    )
    old_type.drop(op.get_bind(), checkfirst=False)
    new_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE retry_task ALTER COLUMN status TYPE retrytaskstatuses USING status::text::retrytaskstatuses"
    )
    tmp_type.drop(op.get_bind(), checkfirst=False)

    # ADD COLUMN TO TASKTYPE
    op.add_column("task_type", sa.Column("cleanup_handler_path", sa.String(), nullable=True))


def downgrade() -> None:
    # REVERT ENUM
    tmp_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE retry_task ALTER COLUMN status TYPE _retrytaskstatuses_old USING status::text::_retrytaskstatuses_old"
    )
    new_type.drop(op.get_bind(), checkfirst=False)
    old_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE retry_task ALTER COLUMN status TYPE retrytaskstatuses USING status::text::retrytaskstatuses"
    )
    tmp_type.drop(op.get_bind(), checkfirst=False)

    # DROP NEW COLUMN ON TASKTYPE TABLE
    op.drop_column("task_type", "cleanup_handler_path")
