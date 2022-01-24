"""rename voucher_type_slug

Revision ID: 6480cdb258da
Revises: 142af407012d
Create Date: 2022-01-24 18:42:05.412221

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "6480cdb258da"
down_revision = "142af407012d"
branch_labels = None
depends_on = None


def alter_task(
    old_task_name: str,
    new_task_name: str,
    new_task_path: str,
    old_key_name: str,
    new_key_name: str,
) -> None:
    meta = sa.MetaData()
    conn = op.get_bind()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    task_type_key_id = conn.execute(
        sa.future.select(TaskTypeKey.c.task_type_key_id).where(
            TaskTypeKey.c.name == old_key_name,
            TaskTypeKey.c.task_type_id == TaskType.c.task_type_id,
            TaskType.c.name == old_task_name,
        )
    ).scalar_one()
    op.execute(TaskType.update().where(TaskType.c.name == old_task_name).values(name=new_task_name, path=new_task_path))
    op.execute(TaskTypeKey.update().where(TaskTypeKey.c.task_type_key_id == task_type_key_id).values(name=new_key_name))


def upgrade() -> None:
    op.add_column("reward_rule", sa.Column("reward_slug", sa.String(length=32), nullable=True))
    op.execute("UPDATE reward_rule SET reward_slug = voucher_type_slug")
    op.alter_column("reward_rule", "reward_slug", nullable=False)
    op.drop_index("ix_reward_rule_voucher_type_slug", table_name="reward_rule")
    op.create_index(op.f("ix_reward_rule_reward_slug"), "reward_rule", ["reward_slug"], unique=True)
    op.drop_column("reward_rule", "voucher_type_slug")

    alter_task(
        "voucher-status-adjustment",
        "reward-status-adjustment",
        "app.tasks.reward_status_adjustment.reward_status_adjustment",
        "voucher_type_slug",
        "reward_slug",
    )


def downgrade() -> None:
    op.add_column(
        "reward_rule", sa.Column("voucher_type_slug", sa.VARCHAR(length=32), autoincrement=False, nullable=True)
    )
    op.execute("UPDATE reward_rule SET voucher_type_slug = reward_slug")
    op.alter_column("reward_rule", "voucher_type_slug", nullable=False)
    op.drop_index(op.f("ix_reward_rule_reward_slug"), table_name="reward_rule")
    op.create_index("ix_reward_rule_voucher_type_slug", "reward_rule", ["voucher_type_slug"], unique=False)
    op.drop_column("reward_rule", "reward_slug")

    alter_task(
        "reward-status-adjustment",
        "voucher-status-adjustment",
        "app.tasks.voucher_status_adjustment.voucher_status_adjustment",
        "reward_slug",
        "voucher_type_slug",
    )
