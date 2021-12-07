"""campaign balances tasks

Revision ID: 5f7726d12bc5
Revises: 1583840ffde6
Create Date: 2021-12-06 14:33:31.262815

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "5f7726d12bc5"
down_revision = "ed1ba3d8bc45"
branch_labels = None
depends_on = None


task_names = ("create-campaign-balances", "delete-campaign-balances")


def get_tables(conn: sa.engine.Connection) -> tuple[sa.Table, sa.Table]:
    metadata = sa.MetaData()
    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)
    return task_type, task_type_key


def upgrade() -> None:
    conn = op.get_bind()
    task_type, task_type_key = get_tables(conn)

    for task_name in task_names:
        inserted_obj = conn.execute(
            sa.insert(task_type).values(
                name=task_name,
                path="app.tasks.campaign_balances.update_campaign_balances",
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
                    {"name": "campaign_slug", "type": "STRING"},
                )
            ],
        )


def downgrade() -> None:
    conn = op.get_bind()
    task_type, _ = get_tables(conn)
    conn.execute(task_type.delete().where(task_type.c.name.in_(task_names)))
