"""add periodo to planes and set fecha_creacion default

Revision ID: b2f7d3a9c1e4
Revises: 84fdce92bda4
Create Date: 2025-10-08 16:30:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2f7d3a9c1e4"
down_revision = "84fdce92bda4"
branch_labels = None
depends_on = None


def upgrade():
    # Añadir columna 'periodo' con valor por defecto 'Mensual'
    op.add_column(
        "planes",
        sa.Column(
            "periodo",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'Mensual'"),
        ),
    )
    # Nota: algunos servidores MySQL antiguos no aceptan CURRENT_TIMESTAMP en columnas DATETIME.
    # Para evitar fallos en la migración en entornos con versiones antiguas de MySQL, no
    # forzamos aquí el server_default. El modelo ya define un default a nivel de aplicación
    # (datetime.utcnow). Si quieres aplicar CURRENT_TIMESTAMP en el servidor, edita esta
    # migración manualmente según la versión de MySQL y tus necesidades.
    pass


def downgrade():
    # Revertir cambios
    try:
        op.alter_column(
            "planes", "fecha_creacion", existing_type=sa.DateTime(), server_default=None
        )
    except Exception:
        pass
    op.drop_column("planes", "periodo")
