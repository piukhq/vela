"""alter reward-adjustment token param names

Revision ID: 02a7b4c44f52
Revises: 6480cdb258da
Create Date: 2022-02-01 16:21:55.450642

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "02a7b4c44f52"
down_revision = "6480cdb258da"
branch_labels = None
depends_on = None

task_type_name = "reward-adjustment"
token_renames = [
    ("inc_adjustment_idempotency_token", "pre_allocation_token"),
    ("dec_adjustment_idempotency_token", "post_allocation_token"),
    ("allocation_idempotency_token", "allocation_token"),
]
new_params = [("reward_only", "BOOLEAN"), ("secondary_reward_retry_task_id", "INTEGER")]


def upgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    for old, new in token_renames:
        op.execute(
            sa.update(TaskTypeKey).where(TaskType.c.name == task_type_name, TaskTypeKey.c.name == old).values(name=new)
        )
    task_type_id = conn.scalar(sa.select(TaskType.c.task_type_id).where(TaskType.c.name == task_type_name))
    op.bulk_insert(
        TaskTypeKey,
        [
            {
                "task_type_id": task_type_id,
                "name": name,
                "type": param_type,
            }
            for name, param_type in new_params
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    op.execute(
        sa.delete(TaskTypeKey).where(
            TaskType.c.name == "reward-adjustment",
            TaskTypeKey.c.name.in_([name for (name, _) in new_params]),
        )
    )
    for new, old in token_renames:
        op.execute(
            sa.update(TaskTypeKey).where(TaskType.c.name == task_type_name, TaskTypeKey.c.name == old).values(name=new)
        )
