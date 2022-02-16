"""alter earn_inc_is_tx_value col

Revision ID: 3b5af0db00a6
Revises: 02a7b4c44f52
Create Date: 2022-02-14 16:20:17.489283

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "3b5af0db00a6"
down_revision = "c6f1f3c7d09d"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("campaign", "earn_inc_is_tx_value", nullable=False, new_column_name="loyalty_type")
    op.execute("CREATE TYPE loyaltytypes AS ENUM ('ACCUMULATOR', 'STAMPS');")
    conn = op.get_bind()
    conn.execute(
        "ALTER TABLE campaign"
        " ALTER COLUMN loyalty_type"
        " SET DATA TYPE loyaltytypes"
        " USING ("
        " CASE loyalty_type"
        " WHEN true THEN 'ACCUMULATOR'::text::loyaltytypes"
        " WHEN false THEN 'STAMPS'::text::loyaltytypes"
        " END"
        " );"
    )
    conn.execute("ALTER TABLE ONLY campaign ALTER COLUMN loyalty_type SET DEFAULT 'STAMPS';")


def downgrade():
    op.alter_column("campaign", "loyalty_type", nullable=False, new_column_name="earn_inc_is_tx_value")
    op.execute("ALTER TABLE campaign ALTER COLUMN earn_inc_is_tx_value DROP DEFAULT;")
    op.execute(
        "ALTER TABLE campaign"
        " ALTER COLUMN earn_inc_is_tx_value "
        " SET DATA TYPE boolean "
        " USING ("
        " CASE earn_inc_is_tx_value"
        " WHEN 'ACCUMULATOR'::text::loyaltytypes THEN true"
        " WHEN 'STAMPS'::text::loyaltytypes THEN false"
        " END"
        ");"
    )
    op.execute("DROP TYPE loyaltytypes")
