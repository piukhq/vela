"""reward_slug not unique

Revision ID: 02b35d82ec64
Revises: ba653772a35c
Create Date: 2022-10-04 13:48:17.305125

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "02b35d82ec64"
down_revision = "ba653772a35c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_reward_rule_reward_slug", table_name="reward_rule")
    op.create_index(op.f("ix_reward_rule_reward_slug"), "reward_rule", ["reward_slug"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reward_rule_reward_slug"), table_name="reward_rule")
    op.create_index("ix_reward_rule_reward_slug", "reward_rule", ["reward_slug"], unique=True)
