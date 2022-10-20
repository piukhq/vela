"""new cancel account holder rewards task


Revision ID: 6f65ef0de5de
Revises: b5161b249af5
Create Date: 2022-10-18 14:13:37.659111

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "6f65ef0de5de"
down_revision = "b5161b249af5"
branch_labels = None
depends_on = None

cancel_rewards_task_name = "cancel-account-holder-rewards"
key_type_list = [
    {"name": "retailer_slug", "type": "STRING"},
    {"name": "campaign_slug", "type": "STRING"},
]


def upgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()

    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)

    # cancel account holder rewards task
    inserted_obj = conn.execute(
        sa.insert(task_type).values(
            name=cancel_rewards_task_name,
            path="vela.tasks.reward_cancellation.cancel_account_holder_rewards",
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
        task_type_key.delete().where(
            task_type_key.c.name.in_(k["name"] for k in key_type_list),
            task_type.c.task_type_id == task_type_key.c.task_type_id,
            task_type.c.name == cancel_rewards_task_name,
        )
    )
    conn.execute(sa.delete(task_type).where(task_type.c.name == cancel_rewards_task_name))
