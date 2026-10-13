from datetime import datetime, date
from decimal import Decimal
from .extensions import db
from .models import Membresia, APIKey
from flask import current_app, request, jsonify, g, session, abort
from functools import wraps
from flask import redirect, url_for


def get_user_sucursal_id():
    """Obtiene la sucursal_id efectiva del usuario actual.
    Prioridad: 1) sucursal fija del usuario, 2) sucursal seleccionada en sesión.
    Retorna None si el usuario es admin sin sucursal fija y no seleccionó ninguna (acceso a todas).
    """
    try:
        try:
            from flask_login import current_user
        except Exception:
            from .blueprints.auth import current_user

        if current_user and getattr(current_user, "is_authenticated", False):
            # Si el usuario tiene sucursal fija, es la única verdad
            if getattr(current_user, "sucursal_id", None):
                return current_user.sucursal_id
            # Si es admin (rol_id == 1) sin sucursal fija, usar la de sesión o None (todas)
            if getattr(current_user, "rol_id", None) == 1:
                return session.get("sucursal_id")  # puede ser None = todas
            # Empleado sin sucursal fija: usar sesión
            return session.get("sucursal_id")
    except Exception:
        pass
    return session.get("sucursal_id")


def verify_sucursal_access(resource):
    """Verifica que el usuario actual tenga permiso para acceder a un recurso
    basándose en la sucursal del recurso.

    - Admins (rol_id == 1) pueden acceder a todo.
    - Empleados solo pueden acceder a recursos de su sucursal.

    Args:
        resource: Objeto de modelo que tiene atributo `sucursal_id`.

    Retorna: True si tiene acceso, False si no.
    Llama abort(403) si no tiene acceso.
    """
    if resource is None:
        return True

    resource_sucursal = getattr(resource, "sucursal_id", None)
    if resource_sucursal is None:
        return True  # recurso sin sucursal asignada, acceso libre

    try:
        try:
            from flask_login import current_user
        except Exception:
            from .blueprints.auth import current_user

        if not (current_user and getattr(current_user, "is_authenticated", False)):
            return True  # sin sesión, el before_request lo redirigirá

        # Obtener sucursal del usuario
        user_sucursal = getattr(current_user, "sucursal_id", None)
        
        # Si el usuario NO tiene sucursal asignada (Super Admin), tiene acceso total
        if user_sucursal is None:
            return True

        # Si el usuario TIENE sucursal asignada (Admin de sede o Empleado), 
        # debe coincidir con la del recurso.
        if resource_sucursal != user_sucursal:
            abort(403)
            return False
            
    except Exception as e:
        # Si es un abort(403), re-lanzarlo
        if hasattr(e, "code") and getattr(e, "code", None) == 403:
            raise

    return True


def admin_required(func):
    """Decorator para rutas que sólo deben ser accesibles por administradores (rol_id == 1).
    Usa el `current_user` expuesto en el contexto (flask-login o fallback del blueprint auth).
    Redirige a la página principal si no autorizado y muestra flash.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # importar en tiempo de ejecución para evitar dependencias cíclicas
            try:
                from flask_login import current_user
            except Exception:
                try:
                    from .blueprints.auth import current_user
                except Exception:
                    current_user = None
            # Si el usuario de sesión no es admin, permitir alternativa por API Key
            if not (
                current_user
                and current_user.is_authenticated
                and getattr(current_user, "rol_id", None) == 1
            ):
                # Intentar validar API Key en header Authorization: Bearer <key>
                try:
                    auth_header = request.headers.get("Authorization", "")
                    if auth_header.startswith("Bearer "):
                        api_key_string = auth_header[7:]
                        if api_key_string:
                            api_key = APIKey.query.filter_by(
                                key=api_key_string, activo=True
                            ).first()
                            if (
                                api_key
                                and api_key.usuario
                                and getattr(api_key.usuario, "rol_id", None) == 1
                                and getattr(api_key.usuario, "estado", True)
                            ):
                                # permitir acceso y exponer el usuario en g
                                try:
                                    api_key.ultimo_uso = datetime.utcnow()
                                    db.session.commit()
                                except Exception:
                                    try:
                                        db.session.rollback()
                                    except Exception:
                                        pass
                                g.api_key_user = api_key.usuario
                                g.api_key_sucursal_id = api_key.sucursal_id
                                return func(*args, **kwargs)
                except Exception:
                    # si falla la validación por API key, seguir al comportamiento por defecto
                    pass

                try:
                    from flask import flash

                    flash("No autorizado: requerir permisos de administrador")
                except Exception:
                    pass
                return redirect(url_for("index"))
        except Exception:
            # en caso de error conservador, denegar
            return redirect(url_for("index"))
        return func(*args, **kwargs)

    return wrapper


def login_exempt(func):
    """Marca una vista para que el before_request global no exija sesión.

    La vista queda a cargo de validar su propio acceso.
    """
    func._login_exempt = True
    return func


def api_key_required(func):
    """
    Decorador para proteger endpoints API con validación de API key.
    Espera un header: Authorization: Bearer sk_live_...

    Valida la key y almacena en g.api_key_user el objeto Usuario y g.api_key_sucursal_id la sucursal.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Permitir acceso si hay sesión válida (navegador autenticado)
            try:
                from flask_login import current_user
            except Exception:
                try:
                    from .blueprints.auth import current_user
                except Exception:
                    current_user = None

            if current_user and getattr(current_user, "is_authenticated", False):
                # Exponer el usuario en g para que la ruta use el contexto igual que con API key
                g.api_key_user = current_user
                g.api_key_sucursal_id = getattr(current_user, "sucursal_id", None)
                return func(*args, **kwargs)

            # Si no hay sesión, validar API key en header Authorization: Bearer <key>
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "API key no proporcionada. Use: Authorization: Bearer sk_live_...",
                            "data": None,
                        }
                    ),
                    401,
                )

            # Extraer la key
            api_key_string = auth_header[7:]
            if not api_key_string:
                return (
                    jsonify({"success": False, "error": "API key vacía", "data": None}),
                    401,
                )

            # Buscar la key en la BD
            api_key = APIKey.query.filter_by(key=api_key_string, activo=True).first()
            if not api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "API key inválida o revocada",
                            "data": None,
                        }
                    ),
                    401,
                )

            # Verificar que el usuario está activo
            usuario = api_key.usuario
            if not usuario or not getattr(usuario, "estado", False):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Usuario asociado a la API key está inactivo",
                            "data": None,
                        }
                    ),
                    401,
                )

            # Actualizar último uso
            try:
                api_key.ultimo_uso = datetime.utcnow()
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass

            # Almacenar en g para uso posterior en la ruta
            g.api_key_user = usuario
            g.api_key_sucursal_id = api_key.sucursal_id

            # Llamar a la función protegida
            return func(*args, **kwargs)

        except Exception as e:
            try:
                current_app.logger.exception(
                    "Error en validación de API key: %s", str(e)
                )
            except Exception:
                pass

            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Error al validar la API key",
                        "data": None,
                    }
                ),
                500,
            )

    # Permite que el before_request global deje pasar sin sesión sólo a estas vistas
    wrapper._api_key_protected = True
    return wrapper


# State IDs expected in DB:
# 1 Pendiente de pago
# 2 Activa
# 3 Anulada
# 4 Inactiva
# 5 En espera


def _compute_monto_total_for_membresia(membresia: Membresia) -> Decimal:
    # try to compute price via plan and promotion; fallback to 0
    try:
        precio = Decimal(membresia.plan.precio)
    except Exception:
        return Decimal("0.00")
    promo = getattr(membresia, "promocion", None)
    # Ahora `promocion.descuento` se interpreta como un monto fijo a restar
    if promo and getattr(promo, "descuento", None) is not None:
        try:
            desc = Decimal(promo.descuento)
        except Exception:
            desc = Decimal("0")
        # restar el descuento fijo, sin permitir valor negativo
        final = precio - desc
        if final < Decimal("0"):
            final = Decimal("0.00")
        return final.quantize(Decimal("0.01"))
    return precio.quantize(Decimal("0.01"))


def process_membership_states(target_membresia_id: int = None, client_id: int = None):
    """Delegates to membership_state_service.process_membership_states().
    
    Process automatic state changes for memberships.
    For backwards compatibility, remains in utils but delegates to service.
    """
    try:
        from .services.membership_state_service import process_membership_states as _process
        return _process(target_membresia_id, client_id)
    except Exception:
        current_app.logger.exception("Error in process_membership_states")
        return None


def sync_client_states(target_ids: set = None):
    """Delegates to membership_state_service.sync_client_states().
    For backwards compatibility, remains in utils but delegates to service.
    """
    try:
        from .services.membership_state_service import sync_client_states as _sync
        return _sync(target_ids)
    except Exception:
        current_app.logger.exception("Error in sync_client_states")
        return None


def ensure_membership_state_after_payment(membresia_id: int):
    """
    Calcula el total debido y lo pagado para la membresía indicada.
    Si los pagos completan el total, actualiza inmediatamente el registro de
    `Membresia.estado_id` a Activa (2) o En espera (5) según las reglas.
    Retorna el nuevo estado_id (o None si no hubo cambio).
    """
    try:
        m = Membresia.query.get(membresia_id)
        if not m:
            return None
        total_due = _compute_monto_total_for_membresia(m)
        total_paid = Decimal("0")
        for p in m.pagos:
            for h in p.historial:
                try:
                    total_paid += Decimal(h.monto_pagado)
                except Exception:
                    current_app.logger.debug(
                        "Invalid historial monto for pago %s hist %s",
                        getattr(p, "id", None),
                        getattr(h, "id", None),
                    )

        # si no hay monto debido, no cambiamos
        if total_due <= 0:
            return None

        from .models import EstadoMembresia
        activa_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("activ%")).first()
        espera_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("%espera%")).first()
        activa_id = activa_estado.id if activa_estado else 2
        espera_id = espera_estado.id if espera_estado else 5

        today = date.today()
        desired = None
        if total_paid >= total_due:
            # fecha inicio en el futuro -> En espera
            if m.fecha_inicio and m.fecha_inicio > today:
                desired = espera_id
            else:
                # si existe otra activa distinta -> En espera
                active_other = Membresia.query.filter(
                    Membresia.cliente_id == m.cliente_id,
                    Membresia.estado_id == activa_id,
                    Membresia.id != m.id,
                ).first()
                if active_other:
                    desired = espera_id
                else:
                    desired = activa_id

        if desired and m.estado_id != desired:
            # actualizar directamente el registro
            try:
                m.estado_id = desired
                db.session.add(m)
                # si marcamos activa, también actualizar cliente
                if desired == activa_id:
                    try:
                        m.cliente.estado = "Activo"
                        db.session.add(m.cliente)
                    except Exception:
                        pass
                db.session.commit()
                return desired
            except Exception:
                db.session.rollback()
                current_app.logger.exception(
                    "Error actualizando estado de membresia %s", m.id
                )
                return None
    except Exception:
        current_app.logger.exception(
            "Error asegurando estado para membresia %s", membresia_id
        )
    return None


def cancel_pending_memberships_with_past_start():
    """Delegates to membership_state_service.cancel_pending_memberships_with_past_start().
    For backwards compatibility, remains in utils but delegates to service.
    """
    try:
        from .services.membership_state_service import cancel_pending_memberships_with_past_start as _cancel
        return _cancel()
    except Exception:
        current_app.logger.exception("Error in cancel_pending_memberships_with_past_start")
        return 0


def sync_promociones_by_date(today: date = None):
    """Delegates to promotion_service.sync_promociones_by_date().
    For backwards compatibility, remains in utils but delegates to service.
    """
    try:
        from .services.promotion_service import sync_promociones_by_date as _sync
        return _sync(today)
    except Exception:
        current_app.logger.exception("Error in sync_promociones_by_date")
        return ([], [])
