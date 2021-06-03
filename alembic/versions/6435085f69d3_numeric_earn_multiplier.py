"""numeric earn multiplier

Revision ID: 6435085f69d3
Revises: ef18dc97bc42
Create Date: 2021-06-02 19:09:01.829476

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6435085f69d3"
down_revision = "ef18dc97bc42"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("earn_rule", "increment_multiplier", type_=sa.Numeric(scale=2), nullable=False)


def downgrade():
    op.alter_column("earn_rule", "increment_multiplier", type_=sa.Integer, nullable=False)
