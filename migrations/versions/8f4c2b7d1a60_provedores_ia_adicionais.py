"""suporte a vários provedores de IA

Revision ID: 8f4c2b7d1a60
Revises: 54a2f9c80d71
Create Date: 2026-10-14 15:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "8f4c2b7d1a60"
down_revision = "54a2f9c80d71"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("configuracao_ia", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("provedor", sa.String(length=30), nullable=False, server_default="openai")
        )
        batch_op.add_column(sa.Column("url_compativel", sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table("configuracao_ia", schema=None) as batch_op:
        batch_op.drop_column("url_compativel")
        batch_op.drop_column("provedor")
