import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # python-dotenv no está instalado o .env no es necesario; continuar
    pass


class Config:
    # SECRET_KEY DEBE estar definida como variable de entorno.
    # En desarrollo: se usa el valor del .env
    # En producción: generar con `python -c "import secrets; print(secrets.token_hex(32))"`
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY no está definida. Defina la variable de entorno SECRET_KEY."
        )

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///gym.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Seguridad de cookies de sesión ---
    SESSION_COOKIE_HTTPONLY = True          # Previene acceso desde JavaScript (XSS)
    SESSION_COOKIE_SECURE = os.getenv("FLASK_DEBUG", "0") != "1"  # True en producción (HTTPS)
    SESSION_COOKIE_SAMESITE = "Lax"        # Protección CSRF adicional
    SESSION_COOKIE_NAME = "gym_session"    # Nombre no-default reduce fingerprinting
    PERMANENT_SESSION_LIFETIME = 3600      # 1 hora de inactividad máxima

    # --- CSRF ---
    WTF_CSRF_TIME_LIMIT = 3600             # 1 hora de validez del token CSRF

