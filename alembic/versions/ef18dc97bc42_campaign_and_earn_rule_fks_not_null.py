"""campaign and earn rule fks not null

Revision ID: ef18dc97bc42
Revises: 06138a675f48
Create Date: 2021-05-27 09:40:41.133811

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "ef18dc97bc42"
down_revision = "06138a675f48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("campaign", "retailer_id", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("earn_rule", "campaign_id", existing_type=sa.INTEGER(), nullable=False)


def downgrade() -> None:
    op.alter_column("earn_rule", "campaign_id", existing_type=sa.INTEGER(), nullable=True)
    op.alter_column("campaign", "retailer_id", existing_type=sa.INTEGER(), nullable=True)
