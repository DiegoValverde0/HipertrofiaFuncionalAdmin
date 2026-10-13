"""Sync multi-sucursal schema with models

Agrega las tablas y columnas que los modelos usan pero que ninguna migración
anterior creaba (inventario, api_keys y los sucursal_id de pagos, gastos,
ventas, notificaciones y usuarios). Es idempotente: sólo crea lo que falta,
por lo que es segura tanto en bases nuevas como en la base de producción que
ya tenía estos cambios aplicados manualmente.

Revision ID: a1d4e7c9b3f0
Revises: 5c8d6a1f7b2c
Create Date: 2026-10-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1d4e7c9b3f0"
down_revision = "5c8d6a1f7b2c"
branch_labels = None
depends_on = None


# tabla -> nullable que define el modelo
SUCURSAL_COLUMNS = {
    "usuarios": True,
    "pagos": False,
    "gastos": False,
    "ventas": False,
    "notificaciones": False,
}


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _first_sucursal_id(bind):
    return bind.execute(sa.text("SELECT MIN(id) FROM sucursales")).scalar()


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)

    if "api_keys" not in tables:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("sucursal_id", sa.Integer(), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=True),
            sa.Column("fecha_creacion", sa.DateTime(), nullable=True),
            sa.Column("ultimo_uso", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_api_keys_key", "api_keys", ["key"], unique=True)

    if "inventario" not in tables:
        op.create_table(
            "inventario",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("producto_id", sa.Integer(), nullable=False),
            sa.Column("sucursal_id", sa.Integer(), nullable=False),
            sa.Column("cantidad", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["producto_id"], ["productos.id"]),
            sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "producto_id", "sucursal_id", name="uq_inventario_producto_sucursal"
            ),
        )
        # Conservar el stock antiguo (columna productos.stock) en la primera sucursal
        suc_id = _first_sucursal_id(bind)
        if suc_id is not None and "stock" in _columns(bind, "productos"):
            bind.execute(
                sa.text(
                    "INSERT INTO inventario (producto_id, sucursal_id, cantidad) "
                    "SELECT id, :suc, COALESCE(stock, 0) FROM productos"
                ),
                {"suc": suc_id},
            )

    if "historial_pagos" in tables:
        existing = _columns(bind, "historial_pagos")
        with op.batch_alter_table("historial_pagos", schema=None) as batch_op:
            if "metodo_pago" not in existing:
                batch_op.add_column(
                    sa.Column("metodo_pago", sa.String(length=50), nullable=True)
                )
            if "comentarios" not in existing:
                batch_op.add_column(
                    sa.Column("comentarios", sa.String(length=255), nullable=True)
                )

    suc_id = _first_sucursal_id(bind)
    for table, nullable in SUCURSAL_COLUMNS.items():
        if table not in tables or "sucursal_id" in _columns(bind, table):
            continue

        # Se agrega como NULL, se rellena con la primera sucursal y luego se
        # vuelve NOT NULL si el modelo lo exige y no quedan filas sin sucursal.
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("sucursal_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table}_sucursal_id", "sucursales", ["sucursal_id"], ["id"]
            )

        if suc_id is not None:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET sucursal_id = :suc WHERE sucursal_id IS NULL"
                ),
                {"suc": suc_id},
            )

        if not nullable:
            pending = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE sucursal_id IS NULL")
            ).scalar()
            if not pending:
                with op.batch_alter_table(table, schema=None) as batch_op:
                    batch_op.alter_column(
                        "sucursal_id", existing_type=sa.Integer(), nullable=False
                    )

    # clientes.sucursal_id ya existía pero como NULL; el modelo la exige NOT NULL
    if "clientes" in tables:
        col = next(
            c
            for c in sa.inspect(bind).get_columns("clientes")
            if c["name"] == "sucursal_id"
        )
        if col["nullable"]:
            if suc_id is not None:
                bind.execute(
                    sa.text(
                        "UPDATE clientes SET sucursal_id = :suc WHERE sucursal_id IS NULL"
                    ),
                    {"suc": suc_id},
                )
            pending = bind.execute(
                sa.text("SELECT COUNT(*) FROM clientes WHERE sucursal_id IS NULL")
            ).scalar()
            if not pending:
                with op.batch_alter_table("clientes", schema=None) as batch_op:
                    batch_op.alter_column(
                        "sucursal_id", existing_type=sa.Integer(), nullable=False
                    )

    # productos.stock se conserva a propósito: el stock ahora vive en inventario,
    # pero la columna antigua no se elimina para no perder datos históricos.


def downgrade():
    # Migración de sincronización: no se revierte para no perder datos que
    # producción ya tenía antes de que existiera esta revisión.
    pass
