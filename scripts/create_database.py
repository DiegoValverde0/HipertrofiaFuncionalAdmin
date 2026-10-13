"""Script simple para crear la base de datos MySQL indicada en la variable
de entorno DATABASE_URL si no existe. Usa PyMySQL.

Uso:
  setx DATABASE_URL "mysql+pymysql://usuario:contraseña@localhost:3306/gym_db"
  python .\scripts\create_database.py
"""

import os
import sys
from urllib.parse import urlparse, unquote

try:
    import pymysql
except ImportError:
    print("pymysql no está instalado. Ejecuta: pip install PyMySQL")
    sys.exit(1)


def create_mysql_db_from_url(database_url: str):
    parsed = urlparse(database_url)
    scheme = parsed.scheme
    if not scheme.startswith("mysql"):
        print("DATABASE_URL no es MySQL; nada que crear.")
        return

    user = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""
    host = parsed.hostname or "localhost"
    port = parsed.port or 3306
    # path tiene la forma /dbname
    dbname = parsed.path.lstrip("/") or None
    if not dbname:
        print("No se encontró el nombre de la base de datos en DATABASE_URL.")
        return

    print(f'Conectando a MySQL en {host}:{port} como {user or "(sin usuario)"}...')
    conn = pymysql.connect(
        host=host, user=user, password=password, port=port, charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            sql = f"CREATE DATABASE IF NOT EXISTS `{dbname}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            cur.execute(sql)
            print(f"Base de datos `{dbname}` creada/asegurada.")
        conn.commit()
    finally:
        conn.close()


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Por favor exporta la variable DATABASE_URL. Ejemplo:")
        print(
            ' setx DATABASE_URL "mysql+pymysql://usuario:contraseña@localhost:3306/gym_db"'
        )
        sys.exit(1)

    create_mysql_db_from_url(database_url)


if __name__ == "__main__":
    main()
