"""Business logic for manual attendance-based memberships."""

from datetime import date, datetime, timedelta
from flask import current_app
from ..extensions import db
from ..models import Membresia, MarcajeAsistencia, Usuario
from ..utils_timezone import to_bolivia, to_utc_naive


def _local_today():
    """Fecha actual en hora de Bolivia."""
    return to_bolivia(datetime.utcnow()).date()


def manual_attendance_summary(membresia, today=None):
    """Return a compact status summary for manual attendance memberships.

    ``today`` permite evaluar la membresía en una fecha concreta (hora local);
    por defecto se usa la fecha actual en Bolivia.
    """
    try:
        is_manual = bool(getattr(membresia, "is_manual_asistencia", False))
        cupo = int(getattr(membresia, "cupo_marcajes", 0) or 0)
        usados = int(getattr(membresia, "marcajes_usados", 0) or 0)
        restantes = max(cupo - usados, 0) if cupo else 0
        fecha_limite = getattr(membresia, "fecha_fin", None)
        today = today or _local_today()
        puede_marcar = bool(
            is_manual
            and getattr(membresia, "estado_id", None) == 2  # Solo si está Activa
            and fecha_limite
            and fecha_limite >= today
            and (not cupo or usados < cupo)
        )
        motivo = None
        if is_manual and not puede_marcar:
            estado_id = getattr(membresia, "estado_id", None)
            if cupo and usados >= cupo:
                motivo = "Se alcanzó el cupo de marcajes."
            elif fecha_limite and fecha_limite < today:
                motivo = "La ventana de uso ya venció."
            elif estado_id != 2:
                motivo = "La membresía no está Activa (estado actual no permite marcaje)."
            else:
                motivo = "La membresía no está habilitada para marcaje manual."
        return {
            "is_manual": is_manual,
            "cupo": cupo,
            "usados": usados,
            "restantes": restantes,
            "fecha_limite": fecha_limite,
            "puede_marcar": puede_marcar,
            "motivo": motivo,
        }
    except Exception as e:
        try:
            current_app.logger.exception(f"Error building manual attendance summary: {e}")
        except Exception:
            pass
        return {
            "is_manual": False,
            "cupo": 0,
            "usados": 0,
            "restantes": 0,
            "fecha_limite": None,
            "puede_marcar": False,
            "motivo": "Error generando resumen",
        }


def register_manual_attendance(membresia_id, usuario_id=None, sucursal_id=None, observacion=None, registered_at=None):
    """Register a manual attendance mark for a membership.

    Returns (success, payload, error_message).
    """
    try:
        membresia = Membresia.query.get(membresia_id)
        if not membresia:
            return False, None, "Membresía no existe"

        # fecha_registro se guarda como UTC naive; los límites diarios se
        # calculan sobre el día local (Bolivia) para no partir el día a las 20:00.
        mark_at = registered_at or datetime.utcnow()
        if isinstance(mark_at, date) and not isinstance(mark_at, datetime):
            mark_at = datetime.combine(mark_at, datetime.min.time())
        local_day = to_bolivia(mark_at).date()

        summary = manual_attendance_summary(membresia, today=local_day)
        if not summary["is_manual"]:
            return False, None, "La membresía no está configurada para asistencia manual"
        if not summary["puede_marcar"]:
            return False, summary, summary.get("motivo") or "No se puede registrar asistencia"

        user = Usuario.query.get(usuario_id) if usuario_id else None
        is_admin = bool(user and user.rol_id == 1)

        day_start = to_utc_naive(datetime.combine(local_day, datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        existing = MarcajeAsistencia.query.filter(
            MarcajeAsistencia.membresia_id == membresia.id,
            MarcajeAsistencia.fecha_registro >= day_start,
            MarcajeAsistencia.fecha_registro < day_end,
        ).first()
        if existing and not is_admin:
            return False, None, "Ya existe un marcaje registrado para esta membresía en el día de hoy (sólo administradores pueden hacer más de uno)."

        if (
            not is_admin
            and sucursal_id
            and membresia.sucursal_id
            and int(sucursal_id) != int(membresia.sucursal_id)
        ):
            return False, None, "La sucursal no coincide con la membresía"

        # El marcaje siempre queda en la sucursal de la membresía
        sucursal_id = membresia.sucursal_id or sucursal_id

        marcaje = MarcajeAsistencia(
            membresia_id=membresia.id,
            cliente_id=membresia.cliente_id,
            sucursal_id=sucursal_id,
            usuario_id=usuario_id,
            fecha_registro=mark_at,
            tipo_registro="manual",
            observacion=observacion,
        )
        db.session.add(marcaje)

        membresia.marcajes_usados = int(getattr(membresia, "marcajes_usados", 0) or 0) + 1
        if membresia.cupo_marcajes and membresia.marcajes_usados >= membresia.cupo_marcajes:
            membresia.estado_id = 4

        db.session.add(membresia)
        db.session.commit()

        summary = manual_attendance_summary(membresia, today=local_day)
        summary.update(
            {
                "marcaje_id": marcaje.id,
                "fecha_registro": marcaje.fecha_registro.isoformat() if marcaje.fecha_registro else None,
            }
        )
        return True, summary, None
    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error registering manual attendance: {e}")
        except Exception:
            pass
        return False, None, str(e)