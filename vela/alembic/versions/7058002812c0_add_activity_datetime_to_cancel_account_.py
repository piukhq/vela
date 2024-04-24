"""add activity datetime to cancel-account-holder-rewards task params

Revision ID: 7058002812c0
Revises: 41021c7eea75
Create Date: 2022-12-07 17:13:51.301554

"""

from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "7058002812c0"
down_revision = "41021c7eea75"
branch_labels = None
depends_on = None


reward_adjustment_task_name = "cancel-account-holder-rewards"
key_type_list = [
    {"name": "cancel_datetime", "type": "DATETIME"},
]


def get_table_and_subquery(conn: sa.engine.Connection) -> tuple[sa.Table, Any]:
    metadata = sa.MetaData()
    TaskType = sa.Table("task_type", metadata, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", metadata, autoload_with=conn)

    task_type_id_subquery = (
        sa.future.select(TaskType.c.task_type_id)
        .where(TaskType.c.name == reward_adjustment_task_name)
        .scalar_subquery()
    )

    return TaskTypeKey, task_type_id_subquery


def upgrade() -> None:
    conn = op.get_bind()
    TaskTypeKey, task_type_id_subquery = get_table_and_subquery(conn)
    conn.execute(
        TaskTypeKey.insert().values(task_type_id=task_type_id_subquery),
        key_type_list,
    )


def downgrade() -> None:
    conn = op.get_bind()
    TaskTypeKey, task_type_id_subquery = get_table_and_subquery(conn)
    conn.execute(
        TaskTypeKey.delete().where(
            TaskTypeKey.c.task_type_id == task_type_id_subquery,
            TaskTypeKey.c.name.in_([key["name"] for key in key_type_list]),
        )
    )
