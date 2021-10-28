"""retry tasks lib tables

Revision ID: 1b9f316f24cc
Revises: 95e386af3cb0
Create Date: 2021-10-27 14:20:41.305480

"""

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op
from app.tasks.reward_adjustment import adjust_balance

# revision identifiers, used by Alembic.
revision = "1b9f316f24cc"
down_revision = "95e386af3cb0"
branch_labels = None
depends_on = None


taskparamskeytypes = postgresql.ENUM(
    "STRING", "INTEGER", "FLOAT", "BOOLEAN", "DATE", "DATETIME", name="taskparamskeytypes"
)
retrytaskstatuses = postgresql.ENUM(
    "PENDING", "IN_PROGRESS", "FAILED", "SUCCESS", "WAITING", "CANCELLED", "REQUEUED", name="retrytaskstatuses"
)
rewardadjustmentstatuses = postgresql.ENUM(
    "ACCOUNT_HOLDER_DELETED", "FAILED", "IN_PROGRESS", "PENDING", "SUCCESS", name="rewardadjustmentstatuses"
)


def populate_task_type_and_keys(conn: sa.engine.Connection) -> None:
    metadata = sa.MetaData()
    task_type = sa.Table("task_type", metadata, autoload_with=conn)
    task_type_key = sa.Table("task_type_key", metadata, autoload_with=conn)

    inserted_obj = conn.execute(
        sa.insert(task_type).values(
            name="reward-adjustment",
            path=adjust_balance.__module__ + "." + adjust_balance.__name__,
            queue_name="bpl_reward_adjustments",
        )
    )
    task_type_id = inserted_obj.inserted_primary_key[0]
    op.bulk_insert(
        task_type_key,
        [
            {"task_type_id": task_type_id} | task_type_key_data
            for task_type_key_data in (
                {"name": "account_holder_uuid", "type": "STRING"},
                {"name": "retailer_slug", "type": "STRING"},
                {"name": "processed_transaction_id", "type": "INTEGER"},
                {"name": "campaign_slug", "type": "STRING"},
                {"name": "adjustment_amount", "type": "INTEGER"},
                {"name": "idempotency_token", "type": "STRING"},
            )
        ],
    )


def upgrade() -> None:
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
        sa.Column("queue_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("task_type_id"),
    )
    op.create_index(op.f("ix_task_type_name"), "task_type", ["name"], unique=True)
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
        sa.Column("status", retrytaskstatuses, nullable=False),
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
        sa.Column("type", taskparamskeytypes, nullable=False),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_type_id"], ["task_type.task_type_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_type_key_id"),
        sa.UniqueConstraint("name", "task_type_id", name="name_task_type_id_unq"),
    )
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
    op.drop_index("ix_reward_adjustment_id", table_name="reward_adjustment")
    op.drop_table("reward_adjustment")

    conn = op.get_bind()
    rewardadjustmentstatuses.drop(conn, checkfirst=False)
    populate_task_type_and_keys(conn)


def downgrade() -> None:
    op.create_table(
        "reward_adjustment",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("timezone('utc'::text, CURRENT_TIMESTAMP)"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("timezone('utc'::text, CURRENT_TIMESTAMP)"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("status", rewardadjustmentstatuses, autoincrement=False, nullable=False),
        sa.Column("attempts", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("adjustment_amount", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("campaign_slug", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("next_attempt_time", postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
        sa.Column(
            "response_data",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("idempotency_token", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("processed_transaction_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(
            ["processed_transaction_id"],
            ["processed_transaction.id"],
            name="reward_adjustment_processed_transaction_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="reward_adjustment_pkey"),
    )
    op.create_index("ix_reward_adjustment_id", "reward_adjustment", ["id"], unique=False)
    op.drop_table("task_type_key_value")
    op.drop_table("task_type_key")
    op.drop_table("retry_task")
    op.drop_index(op.f("ix_task_type_name"), table_name="task_type")
    op.drop_table("task_type")
    conn = op.get_bind()
    taskparamskeytypes.drop(conn, checkfirst=False)
    retrytaskstatuses.drop(conn, checkfirst=False)
