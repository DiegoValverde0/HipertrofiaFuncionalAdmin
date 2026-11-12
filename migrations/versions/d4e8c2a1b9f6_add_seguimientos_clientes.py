"""Add seguimientos_clientes table for interactive remarketing contact tracking.

Revision ID: d4e8c2a1b9f6
Revises: a1d4e7c9b3f0
Create Date: 2026-11-12 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e8c2a1b9f6"
down_revision = "a1d4e7c9b3f0"
branch_labels = None
depends_on = None


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    if "seguimientos_clientes" not in _tables(bind):
        op.create_table(
            "seguimientos_clientes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cliente_id", sa.Integer(), nullable=False),
            sa.Column("sucursal_id", sa.Integer(), nullable=False),
            sa.Column("usuario_id", sa.Integer(), nullable=True),
            sa.Column("canal", sa.String(length=30), nullable=False),
            sa.Column("resultado", sa.String(length=40), nullable=False),
            sa.Column("fecha_contacto", sa.DateTime(), nullable=False),
            sa.Column("fecha_recontacto", sa.Date(), nullable=True),
            sa.Column("nota", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
            sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"]),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_seguimientos_clientes_cliente_id",
            "seguimientos_clientes",
            ["cliente_id"],
            unique=False,
        )
        op.create_index(
            "ix_seguimientos_clientes_resultado",
            "seguimientos_clientes",
            ["resultado"],
            unique=False,
        )
        op.create_index(
            "ix_seguimientos_clientes_fecha_contacto",
            "seguimientos_clientes",
            ["fecha_contacto"],
            unique=False,
        )
        op.create_index(
            "ix_seguimientos_clientes_fecha_recontacto",
            "seguimientos_clientes",
            ["fecha_recontacto"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    if "seguimientos_clientes" in _tables(bind):
        op.drop_index("ix_seguimientos_clientes_fecha_recontacto", table_name="seguimientos_clientes")
        op.drop_index("ix_seguimientos_clientes_fecha_contacto", table_name="seguimientos_clientes")
        op.drop_index("ix_seguimientos_clientes_resultado", table_name="seguimientos_clientes")
        op.drop_index("ix_seguimientos_clientes_cliente_id", table_name="seguimientos_clientes")
        op.drop_table("seguimientos_clientes")

