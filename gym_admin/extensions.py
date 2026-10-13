try:
    from flask_sqlalchemy import SQLAlchemy
except Exception:
    SQLAlchemy = None
try:
    from flask_migrate import Migrate
except Exception:
    Migrate = None
try:
    from flask_login import LoginManager
except Exception:
    LoginManager = None
try:
    from flask_wtf.csrf import CSRFProtect
except Exception:
    CSRFProtect = None
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:
    Limiter = None
    get_remote_address = None

# Crear instancias sólo si las clases están disponibles. Esto permite importar
# la aplicación incluso cuando las dependencias no están instaladas (útil
# para tareas de edición/inspección); en producción instala los paquetes.
db = SQLAlchemy() if SQLAlchemy else None
migrate = Migrate() if Migrate else None
login_manager = LoginManager() if LoginManager else None
csrf = CSRFProtect() if CSRFProtect else None
# El almacenamiento se define en Config.RATELIMIT_STORAGE_URI (Redis en producción
# para que los procesos de Gunicorn compartan los contadores).
limiter = Limiter(key_func=get_remote_address, default_limits=[]) if Limiter else None
