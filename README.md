# Gym Admin

Aplicación Flask para administración de gimnasio, preparada para correr en desarrollo local con variables de entorno.

## Arranque Local

1. Crear y activar el entorno virtual.
2. Instalar dependencias.
3. Editar `.env` con tu `DATABASE_URL` y `SECRET_KEY`.
4. Crear el esquema en la base de datos.
5. Ejecutar la app en `localhost`.

Ejemplo en Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Opcional: si quieres usar MySQL local, ajusta primero .env
python .\scripts\bootstrap_local_db.py
python .\run.py
```

## Variables de Entorno

El archivo `.env` del proyecto incluye valores base para desarrollo. Ajusta al menos:

- `SECRET_KEY`
- `DATABASE_URL`

Si vas a usar MySQL local, un valor típico es:

```text
mysql+pymysql://usuario:password@127.0.0.1:3306/gymdb?charset=utf8mb4
```

## Notas De Revisión

- El blueprint de autenticación ya quedó con una ruta portátil para templates.
- Las migraciones del backup no cubren por completo todos los modelos actuales; para una base nueva conviene usar el bootstrap local del esquema.
- Si tu base viene de un dump de producción, también puedes apuntar `DATABASE_URL` a esa instancia y trabajar sobre una copia local.

## Archivos Clave

- `gym_admin/__init__.py` - app factory y registro de blueprints
- `gym_admin/config.py` - carga de `.env` y configuración de base de datos
- `gym_admin/models.py` - modelo de datos actual
- `scripts/bootstrap_local_db.py` - crea el esquema desde los modelos actuales
# HipertrofiaFuncionalAdmin
