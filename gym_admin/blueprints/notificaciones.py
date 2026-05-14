from flask import Blueprint, render_template, jsonify, request
from ..models import Notificacion, Cliente, Sucursal
from ..extensions import db
from datetime import datetime, date, timedelta

notif_bp = Blueprint(
    "notificaciones", __name__, template_folder="../templates/notificaciones"
)


@notif_bp.route("/")
def list_notifs():
    items = (
        Notificacion.query.order_by(Notificacion.fecha_creacion.desc()).limit(50).all()
    )
    return render_template("notificaciones/list.html", notificaciones=items)


@notif_bp.route("/api/list")
def api_list():
    items = (
        Notificacion.query.order_by(Notificacion.fecha_creacion.desc()).limit(50).all()
    )
    out = []
    for n in items:
        out.append(
            {
                "id": n.id,
                "tipo": n.tipo,
                "mensaje": n.mensaje,
                "fecha": n.fecha_creacion.isoformat(),
                "leido": bool(n.leido),
                "cliente_id": n.cliente_id,
            }
        )
    return jsonify(out)


@notif_bp.route("/api/birthdays")
def api_birthdays():
    """Return detailed list of clients with birthdays this week (json).
    Respects current user's `sucursal_id` (user.sucursal_id or session['sucursal_id']).
    """
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    results = []
    try:
        sucursal_id = None
        from flask_login import current_user
        from flask import session

        if current_user and getattr(current_user, "is_authenticated", False):
            if getattr(current_user, "sucursal_id", None):
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        q = Cliente.query.filter(Cliente.fecha_nacimiento != None)
        if sucursal_id:
            q = q.filter(Cliente.sucursal_id == int(sucursal_id))
        clients = q.all()
    except Exception:
        clients = Cliente.query.filter(Cliente.fecha_nacimiento != None).all()

    for c in clients:
        try:
            b = c.fecha_nacimiento
            # map birthday to current year; handle feb 29 on non-leap years by mapping to Feb 28
            try:
                b_this = b.replace(year=start.year)
            except ValueError:
                b_this = date(start.year, 2, 28)
            if start <= b_this <= end:
                results.append(
                    {
                        "id": c.id,
                        "nombre": c.nombre,
                        "apellido": c.apellido,
                        "telefono": getattr(c, "telefono", None),
                        "fecha_nacimiento": c.fecha_nacimiento.isoformat(),
                        "fecha_formateada": b_this.isoformat(),
                        "nombre_completo": f"{c.nombre} {c.apellido}",
                    }
                )
        except Exception:
            continue
    return jsonify(results)


@notif_bp.route("/api/force_create")
def api_force_create():
    """Force creation of birthday notifications (development helper)."""
    # restrict to development env
    from flask import current_app

    if not (
        current_app.config.get("ENV") == "development"
        or current_app.config.get("FLASK_ENV") == "development"
    ):
        return (
            jsonify({"created": False, "error": "not allowed in this environment"}),
            403,
        )
    try:
        created = create_birthday_notifications_for_week()
        return jsonify({"created": bool(created)})
    except Exception as e:
        return jsonify({"created": False, "error": str(e)}), 500


@notif_bp.route("/api/mark_read/<int:notif_id>", methods=["POST"])
def api_mark_read(notif_id):
    """Mark a notification as read and return success."""
    n = Notificacion.query.get(notif_id)
    if not n:
        return jsonify({"ok": False, "error": "not found"}), 404
    try:
        n.leido = True
        db.session.add(n)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@notif_bp.route("/api/unread_count")
def api_unread_count():
    c = Notificacion.query.filter_by(leido=False).count()
    return jsonify({"unread": c})


@notif_bp.route("/api/detail/<int:notif_id>")
def api_detail(notif_id):
    n = Notificacion.query.get(notif_id)
    if not n:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify(
        {
            "ok": True,
            "id": n.id,
            "tipo": n.tipo,
            "mensaje": n.mensaje,
            "fecha": n.fecha_creacion.isoformat(),
            "leido": bool(n.leido),
            "cliente_id": n.cliente_id,
        }
    )


def create_birthday_notifications_for_week(
    force: bool = False, sucursal_id: int = None
):
    """Create a notification about birthdays in the current week.
    If `sucursal_id` is provided, notifications are created only for that branch
    and the notification record will have `sucursal_id` set. If not provided,
    behavior falls back to global (all clients).
    """
    today = date.today()
    # logging
    try:
        from flask import current_app

        current_app.logger.debug(
            f"create_birthday_notifications_for_week called force={force} start={today} sucursal_id={sucursal_id}"
        )
    except Exception:
        pass
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)

    # If a specific sucursal_id is provided, create a notification only for that branch.
    # If no sucursal_id is provided, create one notification per existing Sucursal (so sucursal_id is never NULL).
    created_any = False
    try:
        target_sucursales = []
        if sucursal_id:
            try:
                s = Sucursal.query.get(int(sucursal_id))
                if s:
                    target_sucursales = [s]
            except Exception:
                target_sucursales = []
        else:
            target_sucursales = Sucursal.query.order_by(Sucursal.id).all()

        # If there are no sucursales in DB, fall back to creating no notification (avoid NULL sucursal_id)
        if not target_sucursales:
            return False

        for suc in target_sucursales:
            try:
                q = Cliente.query.filter(Cliente.fecha_nacimiento != None)
                q = q.filter(Cliente.sucursal_id == suc.id)
                clients = q.all()
            except Exception:
                clients = Cliente.query.filter(
                    Cliente.fecha_nacimiento != None, Cliente.sucursal_id == suc.id
                ).all()

            names = []
            for c in clients:
                try:
                    b = c.fecha_nacimiento
                    try:
                        b_this = b.replace(year=start.year)
                    except ValueError:
                        b_this = date(start.year, 2, 28)
                    if start <= b_this <= end:
                        names.append(f"{c.nombre} {c.apellido}")
                except Exception:
                    continue
            if not names:
                continue

            # avoid creating duplicate weekly notification for this sucursal unless force is True
            try:
                existing = Notificacion.query.filter(
                    Notificacion.tipo == "cumpleanos",
                    Notificacion.mensaje.like(f"%{start.isoformat()}%"),
                    Notificacion.sucursal_id == suc.id,
                )
                recent = existing.first()
                if recent and not force:
                    continue
            except Exception:
                recent = None

            msg = (
                "Clientes cumpliendo esta semana ("
                + start.isoformat()
                + " - "
                + end.isoformat()
                + "): "
                + ", ".join(names)
            )
            n = Notificacion(
                cliente_id=None, tipo="cumpleanos", mensaje=msg, sucursal_id=suc.id
            )
            db.session.add(n)
            created_any = True

        if created_any:
            db.session.commit()
        else:
            db.session.rollback()
        return created_any
    except Exception:
        # on any unexpected error, rollback and return False
        try:
            db.session.rollback()
        except Exception:
            pass
        return False
    try:
        from flask import current_app

        current_app.logger.debug(
            f"Notificacion creada: id={n.id} tipo={n.tipo} sucursal_id={n.sucursal_id}"
        )
    except Exception:
        pass
    return True
