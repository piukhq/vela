"""v1 release squashed init

Revision ID: 3b5af0db00a6
Revises: 
Create Date: 2022-03-05 10:59:55.653417

"""
from collections import namedtuple

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "3b5af0db00a6"
down_revision = None
branch_labels = None
depends_on = None

STRING = "STRING"
INTEGER = "INTEGER"
BOOLEAN = "BOOLEAN"

QUEUE_NAME = "vela:default"

TaskTypeKeyData = namedtuple("TaskTypeKeyData", ["name", "type"])
TaskTypeData = namedtuple("TaskTypeData", ["name", "path", "error_handler_path", "keys"])
task_type_data = [
    TaskTypeData(
        name="reward-adjustment",
        path="app.tasks.reward_adjustment.adjust_balance",
        error_handler_path="app.tasks.error_handlers.handle_adjust_balance_error",
        keys=[
            TaskTypeKeyData(name="account_holder_uuid", type=STRING),
            TaskTypeKeyData(name="retailer_slug", type=STRING),
            TaskTypeKeyData(name="campaign_slug", type=STRING),
            TaskTypeKeyData(name="adjustment_amount", type=INTEGER),
            TaskTypeKeyData(name="processed_transaction_id", type=INTEGER),
            TaskTypeKeyData(name="allocation_token", type=STRING),
            TaskTypeKeyData(name="pre_allocation_token", type=STRING),
            TaskTypeKeyData(name="post_allocation_token", type=STRING),
            TaskTypeKeyData(name="reward_only", type=BOOLEAN),
            TaskTypeKeyData(name="secondary_reward_retry_task_id", type=INTEGER),
        ],
    ),
    TaskTypeData(
        name="reward-status-adjustment",
        path="app.tasks.reward_status_adjustment.reward_status_adjustment",
        error_handler_path="app.tasks.error_handlers.handle_retry_task_request_error",
        keys=[
            TaskTypeKeyData(name="retailer_slug", type=STRING),
            TaskTypeKeyData(name="reward_slug", type=STRING),
            TaskTypeKeyData(name="status", type=STRING),
        ],
    ),
    TaskTypeData(
        name="create-campaign-balances",
        path="app.tasks.campaign_balances.update_campaign_balances",
        error_handler_path="app.tasks.error_handlers.handle_retry_task_request_error",
        keys=[
            TaskTypeKeyData(name="retailer_slug", type=STRING),
            TaskTypeKeyData(name="campaign_slug", type=STRING),
        ],
    ),
    TaskTypeData(
        name="delete-campaign-balances",
        path="app.tasks.campaign_balances.update_campaign_balances",
        error_handler_path="app.tasks.error_handlers.handle_retry_task_request_error",
        keys=[
            TaskTypeKeyData(name="retailer_slug", type=STRING),
            TaskTypeKeyData(name="campaign_slug", type=STRING),
        ],
    ),
]


def add_task_data() -> None:
    metadata = sa.MetaData()
    conn = op.get_bind()
    TaskType = sa.Table("task_type", metadata, autoload_with=conn)
    TaskTypeKey = sa.Table("task_type_key", metadata, autoload_with=conn)
    for data in task_type_data:
        inserted_obj = conn.execute(
            TaskType.insert().values(
                name=data.name,
                path=data.path,
                error_handler_path=data.error_handler_path,
                queue_name=QUEUE_NAME,
            )
        )
        task_type_id = inserted_obj.inserted_primary_key[0]
        for key in data.keys:
            conn.execute(TaskTypeKey.insert().values(name=key.name, type=key.type, task_type_id=task_type_id))


def upgrade() -> None:
    op.create_table(
        "retailer_rewards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_retailer_rewards_slug"), "retailer_rewards", ["slug"], unique=True)
    op.create_table(
        "task_type",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("error_handler_path", sa.String(), nullable=False),
        sa.Column("queue_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("task_type_id"),
    )
    op.create_index(op.f("ix_task_type_name"), "task_type", ["name"], unique=True)
    op.create_table(
        "campaign",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DRAFT", "CANCELLED", "ENDED", name="campaignstatuses"),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("retailer_id", sa.Integer(), nullable=False),
        sa.Column(
            "loyalty_type",
            sa.Enum("ACCUMULATOR", "STAMPS", name="loyaltytypes"),
            server_default="STAMPS",
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer_rewards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaign_slug"), "campaign", ["slug"], unique=True)
    op.create_table(
        "processed_transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=128), nullable=False),
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("account_holder_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.Integer(), nullable=True),
        sa.Column("campaign_slugs", postgresql.ARRAY(sa.String(length=128)), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer_rewards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "retailer_id", name="process_transaction_retailer_unq"),
    )
    op.create_index(
        op.f("ix_processed_transaction_transaction_id"), "processed_transaction", ["transaction_id"], unique=False
    )
    op.create_table(
        "retry_task",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("retry_task_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("audit_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_attempt_time", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "RETRYING",
                "FAILED",
                "SUCCESS",
                "WAITING",
                "CANCELLED",
                "REQUEUED",
                name="retrytaskstatuses",
            ),
            nullable=False,
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_type_id"], ["task_type.task_type_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("retry_task_id"),
    )
    op.create_table(
        "task_type_key",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("task_type_key_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("STRING", "INTEGER", "FLOAT", "BOOLEAN", "DATE", "DATETIME", name="taskparamskeytypes"),
            nullable=False,
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_type_id"], ["task_type.task_type_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_type_key_id"),
        sa.UniqueConstraint("name", "task_type_id", name="name_task_type_id_unq"),
    )
    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=128), nullable=False),
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("account_holder_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer_rewards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "retailer_id", name="transaction_retailer_unq"),
    )
    op.create_index(op.f("ix_transaction_transaction_id"), "transaction", ["transaction_id"], unique=False)
    op.create_table(
        "earn_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("increment", sa.Integer(), nullable=True),
        sa.Column("increment_multiplier", sa.Numeric(scale=2), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reward_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("reward_goal", sa.Integer(), nullable=False),
        sa.Column("reward_slug", sa.String(length=32), nullable=False),
        sa.Column("allocation_window", sa.Integer(), server_default="0", nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reward_rule_reward_slug"), "reward_rule", ["reward_slug"], unique=True)
    op.create_table(
        "task_type_key_value",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("retry_task_id", sa.Integer(), nullable=False),
        sa.Column("task_type_key_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["retry_task_id"], ["retry_task.retry_task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_type_key_id"], ["task_type_key.task_type_key_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("retry_task_id", "task_type_key_id"),
    )
    add_task_data()


def downgrade() -> None:
    op.drop_table("task_type_key_value")
    op.drop_index(op.f("ix_reward_rule_reward_slug"), table_name="reward_rule")
    op.drop_table("reward_rule")
    op.drop_table("earn_rule")
    op.drop_index(op.f("ix_transaction_transaction_id"), table_name="transaction")
    op.drop_table("transaction")
    op.drop_table("task_type_key")
    op.drop_table("retry_task")
    op.drop_index(op.f("ix_processed_transaction_transaction_id"), table_name="processed_transaction")
    op.drop_table("processed_transaction")
    op.drop_index(op.f("ix_campaign_slug"), table_name="campaign")
    op.drop_table("campaign")
    op.drop_index(op.f("ix_task_type_name"), table_name="task_type")
    op.drop_table("task_type")
    op.drop_index(op.f("ix_retailer_rewards_slug"), table_name="retailer_rewards")
    op.drop_table("retailer_rewards")
