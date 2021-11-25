"""update retrytasks library tasktype model

Revision ID: b51685975bb0
Revises: 1b9f316f24cc
Create Date: 2021-11-23 10:47:34.351252

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b51685975bb0"
down_revision = "1b9f316f24cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column("task_type", sa.Column("error_handler_path", sa.String(), nullable=True))
    task_type = sa.Table("task_type", sa.MetaData(), autoload_with=conn)
    conn.execute(sa.update(task_type).where(task_type.c.name == "reward-adjustment").values(
        queue_name="vela:default", error_handler_path="app.tasks.error_handlers.handle_adjust_balance_error"
    ))
    op.alter_column("task_type", "error_handler_path", nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_column("task_type", "error_handler_path")
    task_type = sa.Table("task_type", sa.MetaData(), autoload_with=conn)
    conn.execute(sa.update(task_type).where(task_type.c.name == "reward-adjustment").values(
        queue_name="bpl_reward_adjustments"
    ))
