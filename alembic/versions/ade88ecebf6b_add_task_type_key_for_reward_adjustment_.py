"""add task_type_key for reward-adjustment task

Revision ID: ade88ecebf6b
Revises: aebe2746a51d
Create Date: 2022-07-14 09:38:15.221239

"""
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "ade88ecebf6b"
down_revision = "aebe2746a51d"
branch_labels = None
depends_on = None


reward_adjustment_task_name = "reward-adjustment"
key_type_list = [
    {"name": "transaction_datetime", "type": "DATETIME"},
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
