from flask import Flask, render_template, session, request
from .config import Config
from .extensions import db, migrate, login_manager, csrf, limiter
from datetime import date


def create_app(config_object: str | None = None):
    app = Flask(__name__)
    app.config.from_object(Config if config_object is None else config_object)

    # ProxyFix para despliegues detrás de Nginx/Docker (VPS)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # init extensions (sólo si están disponibles en el entorno)
    from . import extensions

    if getattr(extensions, "db", None):
        extensions.db.init_app(app)
    if getattr(extensions, "migrate", None):
        # migrate requiere db; sólo inicializar si db existe
        if getattr(extensions, "db", None):
            extensions.migrate.init_app(app, extensions.db)
    if getattr(extensions, "login_manager", None):
        extensions.login_manager.init_app(app)
    if getattr(extensions, "csrf", None):
        extensions.csrf.init_app(app)
    if getattr(extensions, "limiter", None):
        extensions.limiter.init_app(app)

    # register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.api_auth import api_auth_bp
    from .blueprints.clientes import clientes_bp
    from .blueprints.usuarios import usuarios_bp
    from .blueprints.roles import roles_bp
    from .blueprints.sucursales import sucursales_bp
    from .blueprints.planes import planes_bp
    from .blueprints.promociones import promociones_bp
    from .blueprints.membresias import membresias_bp
    from .blueprints.pagos import pagos_bp
    from .blueprints.finanzas import finanzas_bp
    from .blueprints.estados_membresias import estados_bp
    from .blueprints.gastos import gastos_bp
    from .blueprints.notificaciones import (
        notif_bp,
        create_birthday_notifications_for_week,
    )
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.productos import productos_bp
    from .blueprints.ventas import ventas_bp
    from .blueprints.auditoria import auditoria_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(api_auth_bp)
    app.register_blueprint(clientes_bp, url_prefix="/clientes")
    app.register_blueprint(usuarios_bp, url_prefix="/usuarios")
    app.register_blueprint(roles_bp, url_prefix="/roles")
    app.register_blueprint(sucursales_bp, url_prefix="/sucursales")
    app.register_blueprint(planes_bp, url_prefix="/planes")
    app.register_blueprint(promociones_bp, url_prefix="/promociones")
    app.register_blueprint(membresias_bp, url_prefix="/membresias")
    app.register_blueprint(pagos_bp, url_prefix="/pagos")
    app.register_blueprint(finanzas_bp, url_prefix="/finanzas")
    app.register_blueprint(estados_bp, url_prefix="/estados_membresias")
    app.register_blueprint(gastos_bp, url_prefix="/gastos")
    app.register_blueprint(notif_bp, url_prefix="/notificaciones")
    app.register_blueprint(productos_bp, url_prefix="/productos")
    app.register_blueprint(ventas_bp, url_prefix="/ventas")
    app.register_blueprint(auditoria_bp, url_prefix="/auditoria")
    app.register_blueprint(dashboard_bp, url_prefix="")

    # simple index -> render home template with navbar
    @app.route("/")
    def index():
        return render_template("home.html")

    # --- Security Headers ---
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    # flask-login: loader
    from .models import Usuario

    # registrar sólo si login_manager está disponible
    if getattr(extensions, "login_manager", None):

        @extensions.login_manager.user_loader
        def load_user(user_id):
            try:
                return Usuario.query.get(int(user_id))
            except Exception:
                return None

    # asegurar que `current_user` esté disponible en templates incluso si
    # flask-login no está instalado: proveer un objeto dummy con is_authenticated=False
    try:
        from flask_login import current_user as _current_user
    except Exception:
        # si flask-login no está instalado, intentar usar el current_user fallback
        # definido en el blueprint de autenticación (usa session internamente)
        try:
            from .blueprints.auth import current_user as _current_user
        except Exception:

            class _Anon:
                is_authenticated = False
                nombre = None
                correo = None

            _current_user = _Anon()

    # agregar a contexto para que jinja lo vea (Flask ya lo expone cuando login_manager existe)
    @app.context_processor
    def expose_current_user():
        return dict(current_user=_current_user)

    # expose some utility functions to templates
    @app.context_processor
    def expose_helpers():
        # import here to avoid circular imports at module import time
        from . import utils as _utils

        return dict(
            _compute_monto_total_for_membresia=_utils._compute_monto_total_for_membresia,
            today=date.today(),
        )

    # register timezone formatting filter (mostrar en hora de Bolivia)
    try:
        from .utils_timezone import format_dt_local

        app.jinja_env.filters["local_dt"] = format_dt_local
    except Exception:
        # ignore if zoneinfo/backports not available
        pass

    # context processor para sucursales y sucursal actual
    from .models import Sucursal

    @app.context_processor
    def inject_sucursales():
        try:
            sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
        except Exception:
            sucursales = []
        sucursal_id = session.get("sucursal_id") if session is not None else None
        return dict(sucursales=sucursales, sucursal_actual_id=sucursal_id)

    # context processor para sucursales y sucursal actual
    from .models import Sucursal

    @app.context_processor
    def inject_sucursales():
        try:
            sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
        except Exception:
            sucursales = []
        sucursal_id = session.get("sucursal_id") if session is not None else None
        return dict(sucursales=sucursales, sucursal_actual_id=sucursal_id)

    # Requerir autenticación en todas las rutas por defecto (excluir auth y static)
    @app.before_request
    def require_login_all_routes():
        try:
            from flask import request

            # 1. PERMITIR RUTAS EXENTAS
            # Añadimos 'clientes.api_list_clientes' o cualquier ruta que empiece con 'api'
            exempt_blueprints = ["auth", "static", "api_auth"]
            if request.endpoint:
                # Si el blueprint está en la lista de exentos
                if any(
                    request.endpoint.startswith(bp + ".") for bp in exempt_blueprints
                ):
                    return None

                # EXCEPCIÓN CRÍTICA: No redirigir si es una ruta de API
                # Esto permite que @api_key_required haga su trabajo después
                if "api" in request.endpoint:
                    return None

            # 2. PERMITIR PDFS TOKENIZADOS
            if request.endpoint == "membresias.membresia_pdf_token":
                return None

            # 3. VERIFICAR AUTENTICACIÓN DE SESIÓN (Navegador)
            try:
                from flask_login import current_user as _cu
            except Exception:
                try:
                    from .blueprints.auth import current_user as _cu
                except Exception:
                    _cu = None

            if _cu and getattr(_cu, "is_authenticated", False):
                return None

            # 4. SI NO HAY SESIÓN Y NO ES API -> REDIRIGIR
            from flask import redirect, url_for

            return redirect(url_for("auth.login"))

        except Exception:
            # FAIL-CLOSED: si hay un error inesperado, denegar acceso
            # en vez de permitirlo (previene bypass de autenticación)
            try:
                from flask import redirect, url_for

                return redirect(url_for("auth.login"))
            except Exception:
                return ("Error del servidor", 500)

    return app
