from flask import (
    Blueprint,
    request,
    jsonify,
    current_app,
    render_template,
    redirect,
    url_for,
)
from ..models import APIKey, Sucursal
from ..extensions import db
from ..utils import admin_required
import secrets

api_auth_bp = Blueprint(
    "api_auth",
    __name__,
    url_prefix="/api/auth",
    template_folder="../templates/api_auth",
)


def generar_api_key(largo=32):
    """Genera una API key única con formato sk_live_..."""
    return f"sk_live_{secrets.token_urlsafe(largo)}"


@api_auth_bp.route("/", methods=["GET"])
@admin_required
def dashboard_api_keys():
    """
    Dashboard para administrar API keys del usuario autenticado.
    Solo admins pueden acceder.

    Retorna: HTML con lista de API keys y formulario para crear nuevas
    """
    try:
        from flask_login import current_user
    except Exception:
        try:
            from .auth import current_user
        except Exception:
            current_user = None

    if not (current_user and getattr(current_user, "is_authenticated", False)):
        return redirect(url_for("auth.login"))

    try:
        # Vista admin: mostrar todas las API keys del sistema.
        api_keys = APIKey.query.order_by(APIKey.fecha_creacion.desc()).all()

        # Obtener todas las sucursales para el selector
        sucursales = Sucursal.query.order_by(Sucursal.nombre).all()

        return render_template(
            "api_auth/list.html",
            api_keys=api_keys,
            sucursales=sucursales,
            current_user=current_user,
        )

    except Exception as e:
        try:
            current_app.logger.exception("Error en dashboard_api_keys: %s", str(e))
        except Exception:
            pass

        return render_template(
            "api_auth/list.html",
            api_keys=[],
            sucursales=[],
            error="Error al cargar las API keys",
        )


@api_auth_bp.route("/generate-key", methods=["POST"])
@admin_required
def generate_api_key():
    """
    Endpoint para generar una nueva API key.
    Requiere autenticación de usuario admin.

    Body JSON:
    {
        "nombre": "WATI Integration",
        "sucursal_id": 1 (opcional, si no se proporciona usa la del usuario autenticado)
    }

    Retorna: JSON con la API key generada
    """
    try:
        from flask_login import current_user
    except Exception:
        try:
            from .auth import current_user
        except Exception:
            current_user = None

    if not (current_user and getattr(current_user, "is_authenticated", False)):
        return (
            jsonify(
                {"success": False, "error": "Autenticación requerida", "data": None}
            ),
            401,
        )

    try:
        data = request.get_json() or {}
        nombre = (data.get("nombre") or "").strip()

        if not nombre:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "El nombre de la API key es requerido",
                        "data": None,
                    }
                ),
                400,
            )

        # Determinar sucursal
        sucursal_id = None
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif data.get("sucursal_id"):
            try:
                sucursal_id = int(data.get("sucursal_id"))
            except (ValueError, TypeError):
                sucursal_id = None

        # Generar key única
        key = generar_api_key()

        # Crear registro
        api_key = APIKey(
            key=key,
            nombre=nombre,
            usuario_id=current_user.id,
            sucursal_id=sucursal_id,
            activo=True,
        )

        db.session.add(api_key)
        db.session.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "error": None,
                    "data": {
                        "id": api_key.id,
                        "key": api_key.key,
                        "nombre": api_key.nombre,
                        "usuario_id": api_key.usuario_id,
                        "sucursal_id": api_key.sucursal_id,
                        "activo": api_key.activo,
                        "fecha_creacion": api_key.fecha_creacion.isoformat(),
                    },
                }
            ),
            201,
        )

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception("Error generando API key: %s", str(e))
        except Exception:
            pass

        return (
            jsonify(
                {"success": False, "error": "Error al generar la API key", "data": None}
            ),
            500,
        )


@api_auth_bp.route("/revoke-key/<int:key_id>", methods=["POST"])
@admin_required
def revoke_api_key(key_id):
    """
    Endpoint para revocar/desactivar una API key.
    Requiere autenticación de usuario admin.
    Solo el propietario de la key o un admin puede revocarla.

    Retorna: JSON con estado de la operación
    """
    try:
        from flask_login import current_user
    except Exception:
        try:
            from .auth import current_user
        except Exception:
            current_user = None

    if not (current_user and getattr(current_user, "is_authenticated", False)):
        return (
            jsonify(
                {"success": False, "error": "Autenticación requerida", "data": None}
            ),
            401,
        )

    try:
        api_key = APIKey.query.get(key_id)

        if not api_key:
            return (
                jsonify(
                    {"success": False, "error": "API key no encontrada", "data": None}
                ),
                404,
            )

        # Verificar permisos: solo el propietario o admin puede revocar
        if (
            api_key.usuario_id != current_user.id
            and getattr(current_user, "rol_id", None) != 1
        ):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No autorizado para revocar esta API key",
                        "data": None,
                    }
                ),
                403,
            )

        # Desactivar (no eliminar para auditoría)
        api_key.activo = False
        db.session.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "error": None,
                    "data": {
                        "id": api_key.id,
                        "nombre": api_key.nombre,
                        "activo": api_key.activo,
                        "mensaje": "API key revocada correctamente",
                    },
                }
            ),
            200,
        )

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception("Error revocando API key: %s", str(e))
        except Exception:
            pass

        return (
            jsonify(
                {"success": False, "error": "Error al revocar la API key", "data": None}
            ),
            500,
        )


@api_auth_bp.route("/list-keys", methods=["GET"])
@admin_required
def list_api_keys():
    """
    Endpoint para listar las API keys del usuario autenticado.
    Requiere autenticación.
    Los admins pueden ver todas las keys pasando ?usuario_id=X

    Parámetros:
    - usuario_id: (opcional, solo para admins) filtrar por usuario

    Retorna: JSON con lista de API keys
    """
    try:
        from flask_login import current_user
    except Exception:
        try:
            from .auth import current_user
        except Exception:
            current_user = None

    if not (current_user and getattr(current_user, "is_authenticated", False)):
        return (
            jsonify(
                {"success": False, "error": "Autenticación requerida", "data": None}
            ),
            401,
        )

    try:
        # Determinar qué usuario listar
        usuario_id = current_user.id

        # Si es admin, puede filtrar por otro usuario
        query_usuario_id = request.args.get("usuario_id", type=int)
        if query_usuario_id and getattr(current_user, "rol_id", None) == 1:
            usuario_id = query_usuario_id

        # Obtener keys
        keys = (
            APIKey.query.filter_by(usuario_id=usuario_id)
            .order_by(APIKey.fecha_creacion.desc())
            .all()
        )

        keys_data = []
        for key in keys:
            keys_data.append(
                {
                    "id": key.id,
                    "nombre": key.nombre,
                    "key": f"{key.key[:15]}...{key.key[-8:]}",  # Mostrar inicio y final ofuscados
                    "sucursal_id": key.sucursal_id,
                    "activo": key.activo,
                    "fecha_creacion": key.fecha_creacion.isoformat(),
                    "ultimo_uso": (
                        key.ultimo_uso.isoformat() if key.ultimo_uso else None
                    ),
                }
            )

        return (
            jsonify(
                {
                    "success": True,
                    "error": None,
                    "data": {
                        "usuario_id": usuario_id,
                        "total": len(keys_data),
                        "keys": keys_data,
                    },
                }
            ),
            200,
        )

    except Exception as e:
        try:
            current_app.logger.exception("Error listando API keys: %s", str(e))
        except Exception:
            pass

        return (
            jsonify(
                {
                    "success": False,
                    "error": "Error al listar las API keys",
                    "data": None,
                }
            ),
            500,
        )
