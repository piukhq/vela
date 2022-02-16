"""nullable campaign start date

Revision ID: c6f1f3c7d09d
Revises: 02a7b4c44f52
Create Date: 2022-02-15 13:18:19.716803

"""
from datetime import datetime, timezone

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "c6f1f3c7d09d"
down_revision = "02a7b4c44f52"
branch_labels = None
depends_on = None

datetime_zero = datetime.fromtimestamp(0, tz=timezone.utc)


def upgrade() -> None:
    op.alter_column("campaign", "start_date", existing_type=postgresql.TIMESTAMP(), nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    Campaign = sa.Table("campaign", sa.MetaData(), autoload_with=conn)
    conn.execute(sa.update(Campaign).values(start_date=datetime_zero).where(Campaign.c.start_date.is_(None)))
    op.alter_column("campaign", "start_date", existing_type=postgresql.TIMESTAMP(), nullable=False)
