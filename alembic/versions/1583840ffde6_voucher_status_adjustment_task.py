"""voucher status adjustment task

Revision ID: 1583840ffde6
Revises: b51685975bb0
Create Date: 2021-11-23 11:03:52.998821

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1583840ffde6"
down_revision = "b51685975bb0"
branch_labels = None
depends_on = None


def get_tables(conn: sa.engine.Connection) -> tuple[sa.Table, sa.Table]:
    metadata = sa.MetaData()
    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)
    return task_type, task_type_key


def upgrade() -> None:
    conn = op.get_bind()
    task_type, task_type_key = get_tables(conn)
    inserted_obj = conn.execute(
        sa.insert(task_type).values(
            name="voucher-status-adjustment",
            path="app.tasks.voucher_status_adjustment.voucher_status_adjustment",
            error_handler_path="app.tasks.error_handlers.handle_retry_task_request_error",
            queue_name="vela:default",
        )
    )
    task_type_id = inserted_obj.inserted_primary_key[0]
    op.bulk_insert(
        task_type_key,
        [
            {"task_type_id": task_type_id} | task_type_key_data
            for task_type_key_data in (
                {"name": "retailer_slug", "type": "STRING"},
                {"name": "voucher_type_slug", "type": "STRING"},
                {"name": "status", "type": "STRING"},
            )
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    task_type, _ = get_tables(conn)
    conn.execute(task_type.delete().where(task_type.c.name == "voucher-status-adjustment"))
