"""configuração OpenAI para relatórios gerenciais

Revision ID: 54a2f9c80d71
Revises: dc44c67d28fb
Create Date: 2026-10-14 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "54a2f9c80d71"
down_revision = "dc44c67d28fb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "configuracao_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_key_cifrada", sa.Text(), nullable=True),
        sa.Column("modelo", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_configuracao_ia")),
    )


def downgrade():
    op.drop_table("configuracao_ia")
