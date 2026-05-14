"""Crear o asegurar el esquema actual de la aplicación.

Uso:
  python ./scripts/bootstrap_local_db.py

Lee DATABASE_URL desde `.env` o desde las variables de entorno.
Si no se define, usa la base SQLite local por defecto del proyecto.
"""

from run import create_app
from gym_admin.extensions import db


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        print(
            "Esquema creado o verificado en:", app.config.get("SQLALCHEMY_DATABASE_URI")
        )
        print("Tablas disponibles:", len(db.metadata.tables))


if __name__ == "__main__":
    main()
