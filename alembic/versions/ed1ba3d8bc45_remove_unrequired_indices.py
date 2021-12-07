"""remove unrequired indices

Revision ID: ed1ba3d8bc45
Revises: 1583840ffde6
Create Date: 2021-12-06 11:39:42.907162

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "ed1ba3d8bc45"
down_revision = "1583840ffde6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_campaign_id", table_name="campaign")
    op.drop_index("ix_earn_rule_id", table_name="earn_rule")
    op.drop_index("ix_processed_transaction_id", table_name="processed_transaction")
    op.drop_index("ix_retailer_rewards_id", table_name="retailer_rewards")
    op.drop_index("ix_reward_rule_id", table_name="reward_rule")
    op.drop_index("ix_transaction_id", table_name="transaction")


def downgrade() -> None:
    op.create_index("ix_transaction_id", "transaction", ["id"], unique=False)
    op.create_index("ix_reward_rule_id", "reward_rule", ["id"], unique=False)
    op.create_index("ix_retailer_rewards_id", "retailer_rewards", ["id"], unique=False)
    op.create_index("ix_processed_transaction_id", "processed_transaction", ["id"], unique=False)
    op.create_index("ix_earn_rule_id", "earn_rule", ["id"], unique=False)
    op.create_index("ix_campaign_id", "campaign", ["id"], unique=False)
