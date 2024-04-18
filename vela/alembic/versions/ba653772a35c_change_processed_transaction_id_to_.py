"""change processed transaction id to string

Revision ID: ba653772a35c
Revises: 823f35823186
Create Date: 2022-09-20 13:48:18.801600

"""
import sqlalchemy as sa

from alembic import op
from retry_tasks_lib.enums import TaskParamsKeyTypes

from vela import settings

# revision identifiers, used by Alembic.
revision = "ba653772a35c"
down_revision = "31aa97c88ea9"
branch_labels = None
depends_on = None


task_type_name = settings.REWARD_ADJUSTMENT_TASK_NAME


def upgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    op.execute(
        sa.update(TaskTypeKey)
        .where(TaskType.c.name == task_type_name, TaskTypeKey.c.name == "processed_transaction_id")
        .values(type=TaskParamsKeyTypes.STRING.name)
    )


def downgrade() -> None:
    conn = op.get_bind()
    meta = sa.MetaData()
    TaskType = sa.Table("task_type", meta, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", meta, autoload_with=conn)
    op.execute(
        sa.update(TaskTypeKey)
        .where(TaskType.c.name == task_type_name, TaskTypeKey.c.name == "processed_transaction_id")
        .values(type=TaskParamsKeyTypes.INTEGER.name)
    )
