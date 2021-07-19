"""update status enum

Revision ID: 95e386af3cb0
Revises: 4eadb28814a1
Create Date: 2021-07-19 14:22:41.191618

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "95e386af3cb0"
down_revision = "4eadb28814a1"
branch_labels = None
depends_on = None


old_options = ("PENDING", "IN_PROGRESS", "FAILED", "SUCCESS")
new_options = sorted(old_options + ("ACCOUNT_HOLDER_DELETED",))

old_type = sa.Enum(*old_options, name="rewardadjustmentstatuses")
new_type = sa.Enum(*new_options, name="rewardadjustmentstatuses")
tmp_type = sa.Enum(*new_options, name="_rewardadjustmentstatuses")

tcr = sa.sql.table("reward_adjustment", sa.Column("status", new_type, nullable=False))


def upgrade() -> None:
    # Create a tempoary "_status" type, convert and drop the "old" type
    tmp_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE reward_adjustment ALTER COLUMN status TYPE _rewardadjustmentstatuses"
        " USING status::text::_rewardadjustmentstatuses"
    )
    old_type.drop(op.get_bind(), checkfirst=False)
    # Create and convert to the "new" status type
    new_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE reward_adjustment ALTER COLUMN status TYPE rewardadjustmentstatuses"
        " USING status::text::rewardadjustmentstatuses"
    )
    tmp_type.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    # Convert 'ACCOUNT_HOLDER_DELETED' status into 'FAILED'
    op.execute(tcr.update().where(tcr.c.status == u"ACCOUNT_HOLDER_DELETED").values(status="FAILED"))
    # Create a tempoary "_status" type, convert and drop the "new" type
    tmp_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE reward_adjustment ALTER COLUMN status TYPE _rewardadjustmentstatuses"
        " USING status::text::_rewardadjustmentstatuses"
    )
    new_type.drop(op.get_bind(), checkfirst=False)
    # Create and convert to the "old" status type
    old_type.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE reward_adjustment ALTER COLUMN status TYPE rewardadjustmentstatuses"
        " USING status::text::rewardadjustmentstatuses"
    )
    tmp_type.drop(op.get_bind(), checkfirst=False)
