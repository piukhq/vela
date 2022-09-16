"""Add new proccess pending rewards task

Revision ID: aebe2746a51d
Revises: 8ae0833855f3
Create Date: 2022-05-13 11:48:12.788198

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "aebe2746a51d"
down_revision = "fc93be5fcde2"
branch_labels = None
depends_on = None


pending_rewards_task_name = "convert-or-delete-pending-rewards"
key_type_list = [
    {"name": "retailer_slug", "type": "STRING"},
    {"name": "campaign_slug", "type": "STRING"},
    {"name": "issue_pending_rewards", "type": "BOOLEAN"},
]


def upgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)

    # Convert or delete pending rewards task
    inserted_obj = conn.execute(
        sa.insert(task_type).values(
            name=pending_rewards_task_name,
            path="vela.tasks.pending_rewards.convert_or_delete_pending_rewards",
            error_handler_path="vela.tasks.error_handlers.handle_retry_task_request_error",
            queue_name="vela:default",
        )
    )
    task_type_id = inserted_obj.inserted_primary_key[0]
    key_data_list = [key_type | {"task_type_id": task_type_id} for key_type in key_type_list]
    op.bulk_insert(task_type_key, key_data_list)


def downgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)
    conn.execute(
        sa.delete(task_type_key)
        .where(task_type_key.c.name.in_(k["name"] for k in key_type_list))
        .where(task_type.c.task_type_id == task_type_key.c.task_type_id)
        .where(task_type.c.name == pending_rewards_task_name)
    )
    conn.execute(sa.delete(task_type).where(task_type.c.name == pending_rewards_task_name))
