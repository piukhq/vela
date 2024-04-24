"""alter task paths

Revision ID: 31aa97c88ea9
Revises: 823f35823186
Create Date: 2022-09-21 17:14:57.043345

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "31aa97c88ea9"
down_revision = "823f35823186"
branch_labels = None
depends_on = None


old = "app.tasks"
new = "vela.tasks"


def upgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    TaskType = sa.Table("task_type", metadata, autoload_with=conn)
    conn.execute(TaskType.update(values={TaskType.c.path: sa.func.replace(TaskType.c.path, old, new)}))
    conn.execute(
        TaskType.update(
            values={TaskType.c.error_handler_path: sa.func.replace(TaskType.c.error_handler_path, old, new)}
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    TaskType = sa.Table("task_type", metadata, autoload_with=conn)
    conn.execute(TaskType.update(values={TaskType.c.path: sa.func.replace(TaskType.c.path, new, old)}))
    conn.execute(
        TaskType.update(
            values={TaskType.c.error_handler_path: sa.func.replace(TaskType.c.error_handler_path, new, old)}
        )
    )
