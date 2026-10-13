# Hipertrofia Funcional Admin

Sistema de administración del gimnasio: clientes, membresías, pagos, asistencia
manual, productos e inventario, ventas, gastos, finanzas, notificaciones y
auditoría, con soporte para varias sucursales.

**Stack:** Python 3.11 · Flask 3 · SQLAlchemy 2 · MySQL 8 · Alembic
(Flask-Migrate) · Gunicorn · Docker · Tailwind (CDN) · WeasyPrint para PDF.

## Estructura

```
gym_admin/
  blueprints/   rutas por módulo (clientes, membresias, pagos, ...)
  services/     lógica de negocio (membresías, pagos, asistencia, ...)
  templates/    vistas Jinja
  static/       JS y CSS
  models.py     modelos SQLAlchemy
  config.py     configuración (lee variables de entorno / .env)
migrations/     migraciones Alembic
tests/          tests con pytest
run.py          servidor de desarrollo
wsgi.py         entrada para Gunicorn (wsgi:application)
```

## Desarrollo local

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
```

Crear un `.env` en la raíz (ver variables abajo). Para empezar basta con
`SECRET_KEY`; sin `DATABASE_URL` se usa SQLite (`gym.db`).

```bash
flask --app run db upgrade      # crear / actualizar el esquema
python run.py                   # http://localhost:5000
pytest                          # tests
```

## Variables de entorno

| Variable | Uso |
|---|---|
| `SECRET_KEY` | **Obligatoria.** Firma sesiones y tokens. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | p. ej. `mysql+pymysql://usuario:clave@db:3306/gym_prod?charset=utf8mb4` |
| `FLASK_DEBUG` | `1` sólo en desarrollo (desactiva cookies `Secure`) |
| `ADMIN_TOKEN` | Token del cron de mantenimiento (ver abajo) |
| `RATELIMIT_STORAGE_URI` | `memory://` (defecto) o `redis://redis:6379/0` en producción |
| `LOG_LEVEL` / `SQL_LOG` | Nivel de log (`INFO` por defecto); `SQL_LOG=1` registra cada consulta |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_SSL`, `SMTP_USE_TLS`, `SMTP_TIMEOUT`, `SMTP_TLS_SKIP_VERIFY`, `EMAIL_FROM` | Envío de correos (recuperación de contraseña) |
| `PORT` | Puerto de `python run.py` (5000 por defecto) |

El `.env` nunca se sube al repositorio.

## Producción (VPS Oracle)

La app corre con Docker Compose (`gym_app` + `gym_db` MySQL 8) detrás de Nginx.
Al arrancar, el contenedor ejecuta `flask db upgrade` y luego Gunicorn.

**Desplegar cambios:**

```bash
cd ~/proyectos/HipertrofiaFuncionalAdmin
# respaldo previo de la base
docker exec gym_db sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --all-databases' > ~/respaldo-$(date +%F).sql
git pull origin main
docker compose up -d --build
docker compose logs -f app      # salir con Ctrl+C
```

Reglas:

- Los cambios de código se hacen en local, se suben con `git push` y en el VPS
  sólo se hace `git pull`. En el VPS sólo se edita el `.env`.
- Nunca usar `docker compose down -v` ni `docker volume rm`: borran la base.
- Antes de una migración revisar la versión de la base:
  `SELECT * FROM alembic_version;` debe coincidir con una revisión de
  `migrations/versions/`.

**Mantenimiento diario (cron):** actualiza estados de membresías y genera las
notificaciones de cumpleaños. Reemplazar `TU_ADMIN_TOKEN` por el valor de `ADMIN_TOKEN` del `.env` (cron no lee ese archivo).

```
0 4 * * * curl -fsS -H "Authorization: Bearer TU_ADMIN_TOKEN" http://127.0.0.1:8000/membresias/admin/run_maintenance >> /home/ubuntu/backups/maintenance.log 2>&1
```

## Reglas de negocio importantes

- **Cobertura de un cliente:** está cubierto hasta la `fecha_fin` más lejana
  entre sus membresías *Activas* y *En espera* totalmente pagadas
  (`services/membership_service.compute_coverage`). Por eso un cliente con
  una renovación pagada no figura como "por vencer".
- **Asistencia manual:** un marcaje por día (hora de Bolivia); los
  administradores pueden registrar más. Al agotar el cupo la membresía pasa a
  Inactiva.
- Las fechas se guardan en UTC y se muestran en hora de Bolivia
  (`utils_timezone`).
