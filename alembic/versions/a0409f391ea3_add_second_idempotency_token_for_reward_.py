"""add second idempotency token for reward-adjustments

Revision ID: a0409f391ea3
Revises: e81c2a872f88
Create Date: 2022-01-19 09:16:51.965174

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a0409f391ea3"
down_revision = "e81c2a872f88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    op.execute(
        sa.update(TaskTypeKey)
        .where(TaskType.c.name == "reward-adjustment", TaskTypeKey.c.name == "idempotency_token")
        .values(name="inc_adjustment_idempotency_token")
    )
    op.bulk_insert(
        TaskTypeKey,
        [
            {
                "task_type_id": conn.scalar(
                    sa.select(TaskType.c.task_type_id).where(TaskType.c.name == "reward-adjustment")
                ),
                "name": name,
                "type": "STRING",
            }
            for name in ("dec_adjustment_idempotency_token", "allocation_idempotency_token")
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
            TaskTypeKey.c.name.in_(["dec_adjustment_idempotency_token", "allocation_idempotency_token"]),
        )
    )
    op.execute(
        sa.update(TaskTypeKey)
        .where(
            TaskType.c.name == "reward-adjustment",
            TaskTypeKey.c.name == "inc_adjustment_idempotency_token",
        )
        .values(name="idempotency_token")
    )
