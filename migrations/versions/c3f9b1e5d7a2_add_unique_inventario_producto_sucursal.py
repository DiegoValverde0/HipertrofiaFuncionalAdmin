"""Add unique constraint inventario(producto_id, sucursal_id)

En producción la tabla inventario se creó antes de que existiera la
migración a1d4e7c9b3f0, así que nunca recibió la restricción única que
define el modelo. Esta migración la agrega sólo si falta y si no hay filas
duplicadas; si las hay, no modifica nada y lo informa en el log.

Revision ID: c3f9b1e5d7a2
Revises: a1d4e7c9b3f0
Create Date: 2026-10-13 00:00:00.000000

"""

import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3f9b1e5d7a2"
down_revision = "a1d4e7c9b3f0"
branch_labels = None
depends_on = None

NAME = "uq_inventario_producto_sucursal"
COLUMNS = ["producto_id", "sucursal_id"]

log = logging.getLogger("alembic.runtime.migration")


def _has_unique(bind):
    insp = sa.inspect(bind)
    target = set(COLUMNS)
    for uc in insp.get_unique_constraints("inventario"):
        if set(uc["column_names"]) == target:
            return True
    for ix in insp.get_indexes("inventario"):
        if ix.get("unique") and set(ix["column_names"]) == target:
            return True
    return False


def upgrade():
    bind = op.get_bind()
    if "inventario" not in sa.inspect(bind).get_table_names() or _has_unique(bind):
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT producto_id, sucursal_id FROM inventario "
            "GROUP BY producto_id, sucursal_id HAVING COUNT(*) > 1) d"
        )
    ).scalar()
    if duplicates:
        log.warning(
            "inventario tiene %s combinaciones producto/sucursal duplicadas; "
            "no se agrega %s. Unifique esas filas y ejecute "
            "'flask db stamp a1d4e7c9b3f0' y 'flask db upgrade' para reintentar.",
            duplicates,
            NAME,
        )
        return

    with op.batch_alter_table("inventario", schema=None) as batch_op:
        batch_op.create_unique_constraint(NAME, COLUMNS)


def downgrade():
    # No se revierte: en bases nuevas la restricción la crea a1d4e7c9b3f0 y el
    # modelo la exige, así que quitarla dejaría el esquema desalineado.
    pass
