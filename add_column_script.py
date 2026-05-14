#!/usr/bin/env python
"""Script para agregar el campo tipo_creacion a membresias."""

from gym_admin.extensions import db
from gym_admin import create_app
from sqlalchemy import text
import sys

app = create_app()

def add_tipo_creacion_column():
    with app.app_context():
        try:
            # Intentar agregar la columna directamente usando text()
            sql = text(
                'ALTER TABLE membresias ADD COLUMN tipo_creacion VARCHAR(10) NOT NULL DEFAULT "new" '
                'COMMENT "new = nueva membresía, extend = extensión de anterior"'
            )
            db.session.execute(sql)
            db.session.commit()
            print('✓ Columna tipo_creacion agregada exitosamente')
            return True
        except Exception as e:
            error_str = str(e).lower()
            if 'already exists' in error_str or 'duplicate' in error_str or 'column' in error_str:
                print('✓ Columna tipo_creacion ya existe en la tabla o error esperado')
                db.session.rollback()
                return True
            else:
                print(f'✗ Error al agregar columna: {e}')
                db.session.rollback()
                return False

if __name__ == '__main__':
    success = add_tipo_creacion_column()
    sys.exit(0 if success else 1)

