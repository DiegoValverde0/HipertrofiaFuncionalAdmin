"""Add configurable duration fields to planes

Revision ID: 5c8d6a1f7b2c
Revises: 3f8e5a2b6d1c
Create Date: 2026-07-22 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5c8d6a1f7b2c"
down_revision = "3f8e5a2b6d1c"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    # Idempotente: en algunas bases estas columnas ya se crearon fuera de Alembic.
    bind = op.get_bind()
    planes_cols = _columns(bind, "planes")
    membresias_cols = _columns(bind, "membresias")

    with op.batch_alter_table("planes", schema=None) as batch_op:
        if "duracion_tipo" not in planes_cols:
            batch_op.add_column(
                sa.Column(
                    "duracion_tipo",
                    sa.String(length=20),
                    nullable=False,
                    server_default=sa.text("'meses'"),
                )
            )
        if "duracion_valor" not in planes_cols:
            batch_op.add_column(
                sa.Column(
                    "duracion_valor",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
        if "tipo_uso" not in planes_cols:
            batch_op.add_column(
                sa.Column(
                    "tipo_uso",
                    sa.String(length=30),
                    nullable=False,
                    server_default=sa.text("'tiempo'"),
                )
            )
        if "cupo_marcajes" not in planes_cols:
            batch_op.add_column(
                sa.Column(
                    "cupo_marcajes",
                    sa.Integer(),
                    nullable=True,
                )
            )

    with op.batch_alter_table("membresias", schema=None) as batch_op:
        if "tipo_uso" not in membresias_cols:
            batch_op.add_column(
                sa.Column(
                    "tipo_uso",
                    sa.String(length=30),
                    nullable=False,
                    server_default=sa.text("'tiempo'"),
                )
            )
        if "cupo_marcajes" not in membresias_cols:
            batch_op.add_column(
                sa.Column(
                    "cupo_marcajes",
                    sa.Integer(),
                    nullable=True,
                )
            )
        if "marcajes_usados" not in membresias_cols:
            batch_op.add_column(
                sa.Column(
                    "marcajes_usados",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    connection = bind
    planes_table = sa.table(
        "planes",
        sa.column("id", sa.Integer()),
        sa.column("duracion", sa.String()),
        sa.column("duracion_tipo", sa.String()),
        sa.column("duracion_valor", sa.Integer()),
    )

    # Sólo convertir duraciones antiguas cuando las columnas se acaban de crear
    rows = []
    if "duracion_tipo" not in planes_cols:
        rows = connection.execute(
            sa.select(planes_table.c.id, planes_table.c.duracion)
        ).fetchall()
    legacy_months = {
        "mensual": 1,
        "1 mes": 1,
        "1 meses": 1,
        "trimestral": 3,
        "3 mes": 3,
        "3 meses": 3,
        "semestral": 6,
        "6 mes": 6,
        "6 meses": 6,
        "anual": 12,
        "12 mes": 12,
        "12 meses": 12,
    }

    for row in rows:
        raw = str(row.duracion or "").strip().lower()
        if not raw:
            continue
        if raw in legacy_months:
            connection.execute(
                sa.update(planes_table)
                .where(planes_table.c.id == row.id)
                .values(duracion_tipo="meses", duracion_valor=legacy_months[raw])
            )
            continue

        if "día" in raw or "dias" in raw or "day" in raw:
            digits = "".join(ch for ch in raw if ch.isdigit())
            if digits:
                connection.execute(
                    sa.update(planes_table)
                    .where(planes_table.c.id == row.id)
                    .values(duracion_tipo="dias", duracion_valor=int(digits))
                )

    if "marcajes_asistencia" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "marcajes_asistencia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("membresia_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("fecha_registro", sa.DateTime(), nullable=False),
        sa.Column("tipo_registro", sa.String(length=20), nullable=False),
        sa.Column("observacion", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["membresia_id"], ["membresias.id"]),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("marcajes_asistencia")
    with op.batch_alter_table("membresias", schema=None) as batch_op:
        batch_op.drop_column("marcajes_usados")
        batch_op.drop_column("cupo_marcajes")
        batch_op.drop_column("tipo_uso")

    with op.batch_alter_table("planes", schema=None) as batch_op:
        batch_op.drop_column("cupo_marcajes")
        batch_op.drop_column("tipo_uso")
        batch_op.drop_column("duracion_valor")
        batch_op.drop_column("duracion_tipo")
