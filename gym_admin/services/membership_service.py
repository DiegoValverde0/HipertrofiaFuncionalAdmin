"""Membership service layer - business logic for membresia management."""
from datetime import datetime, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta
import re
from flask import current_app
from ..extensions import db
from ..models import Membresia, Cliente, Plan, EstadoMembresia
from ..utils import _compute_monto_total_for_membresia
from ..utils_timezone import to_bolivia


def local_today():
    """Fecha actual en hora de Bolivia (el servidor corre en UTC)."""
    return to_bolivia(datetime.utcnow()).date()


def is_paid_in_full(membresia):
    """True si la suma de los pagos cubre el monto total de la membresía."""
    try:
        total_due = _compute_monto_total_for_membresia(membresia)
    except Exception:
        return False
    if not total_due or total_due <= 0:
        return False
    total_paid = Decimal("0")
    for pago in membresia.pagos:
        for hist in pago.historial:
            try:
                total_paid += Decimal(hist.monto_pagado)
            except Exception:
                pass
    return total_paid >= total_due


def is_valid_membership(membresia):
    """Una membresía cubre al cliente si está Activa o En espera y pagada."""
    if not getattr(membresia, "fecha_fin", None):
        return False
    if membresia.is_activa:
        return True
    return bool(membresia.is_en_espera and is_paid_in_full(membresia))


def compute_coverage(membresias, horizon_days=7, today=None):
    """Calcula hasta cuándo está cubierto un cliente.

    La cobertura llega hasta la fecha_fin más lejana entre sus membresías
    válidas, de modo que una renovación ya pagada que está en espera evita que
    el cliente figure como "por vencer".

    Returns dict:
    - has: bool, tiene al menos una membresía válida
    - soon: bool, la cobertura termina dentro de ``horizon_days``
    - coverage_end: date | None, último día cubierto
    - current: Membresia | None, membresía válida que termina en coverage_end
    """
    today = today or local_today()
    valid = [m for m in membresias if is_valid_membership(m)]
    if not valid:
        return {"has": False, "soon": False, "coverage_end": None, "current": None}

    current = max(valid, key=lambda m: m.fecha_fin)
    coverage_end = current.fecha_fin
    soon = 0 <= (coverage_end - today).days <= horizon_days
    return {"has": True, "soon": soon, "coverage_end": coverage_end, "current": current}


def get_membership_status(cliente_id, horizon_days=7):
    """Get current membership status for a client.

    Returns dict with:
    - has: bool (client has active membership or a paid one waiting)
    - soon: bool (coverage ends within horizon_days)
    - last_id: id of the membership that ends the coverage (or latest one)
    - last_fecha_fin: expiration date of last
    - last_estado: state of last
    """
    empty = {
        "has": False,
        "soon": False,
        "last_id": None,
        "last_fecha_fin": None,
        "last_estado": None,
    }
    try:
        membresias = Membresia.query.filter_by(cliente_id=cliente_id).all()
    except Exception as e:
        try:
            current_app.logger.exception(
                f"Error fetching memberships for cliente {cliente_id}: {e}"
            )
        except Exception:
            pass
        return empty

    if not membresias:
        return empty

    coverage = compute_coverage(membresias, horizon_days=horizon_days)
    best = coverage["current"]
    if best is None:
        # sin membresías válidas: informar la más reciente
        best = max(membresias, key=lambda m: (m.fecha_inicio, m.id))

    return {
        "has": coverage["has"],
        "soon": coverage["soon"],
        "last_id": best.id,
        "last_fecha_fin": best.fecha_fin,
        "last_estado": best.estado_id,
    }


def _extract_positive_int(value, default=1):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _resolve_duration_config(duration_source, duracion_tipo=None, duracion_valor=None):
    """Resolve a plan duration into unit and amount.

    Supports Plan objects with explicit duration config, dicts and legacy strings.
    """
    tipo = str(duracion_tipo or "").strip().lower()
    valor = duracion_valor
    legacy = ""

    if isinstance(duration_source, Plan):
        legacy = getattr(duration_source, "duracion", "") or ""
        tipo = str(getattr(duration_source, "duracion_tipo", tipo) or "").strip().lower()
        valor = getattr(duration_source, "duracion_valor", valor)
    elif isinstance(duration_source, dict):
        legacy = str(duration_source.get("duracion") or "")
        tipo = str(duration_source.get("duracion_tipo") or tipo).strip().lower()
        valor = duration_source.get("duracion_valor", valor)
    else:
        legacy = str(duration_source or "")

    amount = _extract_positive_int(valor, default=1)
    normalized = legacy.strip().lower()

    # Compatibility rule:
    # - When the new config is still generic (1 month) but the legacy label is specific,
    #   keep honoring the legacy label so old plans do not silently change behavior.
    if isinstance(duration_source, Plan) and tipo == "meses" and amount == 1:
        legacy_months = {
            "mensual": 1,
            "trimestral": 3,
            "semestral": 6,
            "anual": 12,
        }
        if normalized in legacy_months:
            return "meses", legacy_months[normalized]
        match = re.search(r"(\d+)\s*(mes|meses|month|months)", normalized)
        if match:
            return "meses", _extract_positive_int(match.group(1), default=1)
        if "día" in normalized or "dias" in normalized or "day" in normalized:
            match = re.search(r"(\d+)\s*(día|dias|día[s]?|day|days)", normalized)
            if match:
                return "dias", _extract_positive_int(match.group(1), default=1)

    if tipo in {"dia", "dias", "day", "days", "manual"}:
        return "dias", amount
    if tipo in {"mes", "meses", "month", "months"}:
        return "meses", amount

    preset_months = {
        "mensual": 1,
        "trimestral": 3,
        "semestral": 6,
        "anual": 12,
    }
    if normalized in preset_months:
        return "meses", preset_months[normalized]

    match = re.search(r"(\d+)\s*(día|dias|día[s]?|day|days)", normalized)
    if match:
        return "dias", _extract_positive_int(match.group(1), default=1)

    match = re.search(r"(\d+)\s*(mes|meses|month|months)", normalized)
    if match:
        return "meses", _extract_positive_int(match.group(1), default=1)

    if "día" in normalized or "dias" in normalized or "day" in normalized:
        return "dias", amount

    return "meses", amount


def _resolve_usage_config(plan):
    """Resolve usage mode settings for a plan."""
    try:
        tipo_uso = str(getattr(plan, "tipo_uso", "tiempo") or "tiempo").strip().lower()
    except Exception:
        tipo_uso = "tiempo"
    try:
        cupo_marcajes = getattr(plan, "cupo_marcajes", None)
        cupo_marcajes = int(cupo_marcajes) if cupo_marcajes is not None else None
        if cupo_marcajes is not None and cupo_marcajes <= 0:
            cupo_marcajes = None
    except Exception:
        cupo_marcajes = None
    return tipo_uso, cupo_marcajes


def compute_end_date(fecha_inicio, duracion_source, duracion_tipo=None, duracion_valor=None):
    """Compute membership end date given a duration configuration.

    Monthly durations preserve the current weekend-to-Monday adjustment.
    Day-based durations keep the exact day count.
    """
    try:
        if not fecha_inicio or not duracion_source:
            return None

        unidad, amount = _resolve_duration_config(
            duracion_source,
            duracion_tipo=duracion_tipo,
            duracion_valor=duracion_valor,
        )

        if unidad == "dias":
            end_date = fecha_inicio + timedelta(days=max(amount, 1) - 1)
        else:
            end_date = fecha_inicio + relativedelta(months=max(amount, 1))

            weekday = end_date.weekday()
            if weekday == 5:  # Saturday
                end_date = end_date + timedelta(days=2)
            elif weekday == 6:  # Sunday
                end_date = end_date + timedelta(days=1)

        return end_date
    except Exception as e:
        try:
            current_app.logger.exception(f"Error computing end date: {e}")
        except Exception:
            pass
        return None


def preview_membership_dates(fecha_inicio, plan_id, opcion='new', cliente_id=None):
    """
    Preview de fechas sin crear membresía. Se usa para validar antes de guardar.
    
    Args:
        fecha_inicio (date|str): Fecha de inicio propuesta (formato YYYY-MM-DD si es string)
        plan_id (int): ID del plan
        opcion (str): 'new' o 'extend'
        cliente_id (int): Opcional, para opcion='extend', toma última fecha_fin
    
    Returns:
        dict: {
            'fecha_inicio': str (YYYY-MM-DD),
            'fecha_fin': str (YYYY-MM-DD),
            'dias_vigencia': int,
            'duracion_plan': str,
            'estado': 'valido' | 'warning' | 'error',
            'mensaje': str or None
        }
    """
    try:
        from datetime import date as date_type
        
        # Parsear fecha_inicio si viene como string
        if isinstance(fecha_inicio, str):
            try:
                fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
            except ValueError:
                return {
                    'estado': 'error',
                    'mensaje': 'Formato de fecha de inicio inválido. Debe ser YYYY-MM-DD'
                }
        
        # Obtener plan
        plan = Plan.query.get(plan_id)
        if not plan or plan.estado != 'Activo':
            return {
                'estado': 'error',
                'mensaje': 'Plan no existe o está inactivo'
            }
        
        # Manejar opcion 'extend': obtener fecha_fin de última membresía activa
        if opcion == 'extend' and cliente_id:
            status = get_membership_status(cliente_id)
            if status.get('last_fecha_fin'):
                fecha_inicio = status['last_fecha_fin'] + timedelta(days=1)
                # Ajustar fin de semana
                if fecha_inicio.weekday() == 5:  # Sábado
                    fecha_inicio += timedelta(days=2)
                elif fecha_inicio.weekday() == 6:  # Domingo
                    fecha_inicio += timedelta(days=1)
        
        # Validar que fecha_inicio sea razonable
        today = date_type.today()
        if fecha_inicio < today - timedelta(days=30):  # Pasado lejano
            return {
                'estado': 'warning',
                'fecha_inicio': fecha_inicio.isoformat(),
                'fecha_fin': None,
                'mensaje': 'Fecha de inicio es más de 30 días en el pasado'
            }
        
        if fecha_inicio > today + timedelta(days=365*5):  # Muy futuro
            return {
                'estado': 'warning',
                'fecha_inicio': fecha_inicio.isoformat(),
                'fecha_fin': None,
                'mensaje': 'Fecha de inicio es muy lejana (>5 años)'
            }
        
        # Calcular fecha_fin
        fecha_fin = compute_end_date(fecha_inicio, plan)
        if not fecha_fin:
            return {
                'estado': 'error',
                'mensaje': 'No se pudo calcular fecha de fin'
            }
        
        # Calcular días de vigencia
        dias = (fecha_fin - fecha_inicio).days + 1  # +1 para incluir día 1
        
        return {
            'estado': 'valido',
            'fecha_inicio': fecha_inicio.isoformat(),
            'fecha_fin': fecha_fin.isoformat(),
            'dias_vigencia': dias,
            'duracion_plan': plan.duracion,
            'mensaje': None
        }
        
    except Exception as e:
        try:
            current_app.logger.exception(f"Error in preview_membership_dates: {e}")
        except Exception:
            pass
        return {
            'estado': 'error',
            'mensaje': f'Error al procesar: {str(e)}'
        }


def cancel_pending_memberships(cliente_id):
    """Cancel all pending (estado=1) memberships for a client.

    Returns count of cancelled memberships.
    """
    try:
        pending_membresias = Membresia.query.filter_by(cliente_id=cliente_id, estado_id=1).all()

        count = 0
        for m in pending_membresias:
            try:
                m.estado_id = 3  # Anulada
                count += 1
            except Exception:
                pass

        if count > 0:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                try:
                    current_app.logger.exception(
                        f"Error cancelling pending memberships: {e}"
                    )
                except Exception:
                    pass
                return 0

        return count
    except Exception as e:
        try:
            current_app.logger.exception(
                f"Error in cancel_pending_memberships: {e}"
            )
        except Exception:
            pass
        return 0


def create_membership(
    cliente_id,
    plan_id,
    fecha_inicio,
    estado_id,
    sucursal_id=None,
    promocion_id=None,
    fecha_fin=None,
    tipo_creacion='new',
):
    """Create a new membership with validations.

    Args:
        cliente_id (int): ID del cliente
        plan_id (int): ID del plan
        fecha_inicio (date|str): Fecha de inicio de membresía
        estado_id (int): ID del estado de membresía
        sucursal_id (int, optional): ID de sucursal
        promocion_id (int, optional): ID de promoción
        fecha_fin (date, optional): Fecha de fin (se calcula si no se proporciona)
        tipo_creacion (str, optional): 'new' o 'extend' para auditoría

    Returns (success: bool, membresia: Membresia or None, error_msg: str or None)
    """
    try:
        # Validate cliente
        cliente = Cliente.query.get(cliente_id)
        if not cliente:
            return False, None, "Cliente no existe"

        # Validate plan
        plan = Plan.query.get(plan_id)
        if not plan or plan.estado != 'Activo':
            return False, None, "Plan no existe o inactivo"

        if isinstance(fecha_inicio, str):
            try:
                fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
            except ValueError:
                return False, None, "Formato de fecha de inicio inválido. Debe ser YYYY-MM-DD"

        # Validate estado
        try:
            estado = EstadoMembresia.query.get(estado_id)
            if not estado:
                return False, None, "Estado de membresía no válido"
        except Exception:
            return False, None, "Error validando estado"

        # Resolve plan usage mode so memberships inherit the intended behavior.
        tipo_uso, cupo_marcajes = _resolve_usage_config(plan)

        # Compute end date from plan unless explicitly provided (admin/manual override)
        if not fecha_fin:
            fecha_fin = compute_end_date(fecha_inicio, plan)
            if not fecha_fin:
                return False, None, "No se pudo calcular fecha de fin"

        # Validate fecha_fin > fecha_inicio
        if fecha_fin <= fecha_inicio:
            return False, None, "Fecha fin debe ser posterior a fecha inicio"

        # Cancel pending memberships
        cancel_pending_memberships(cliente_id)

        # Create membresia
        membresia = Membresia(
            cliente_id=cliente_id,
            plan_id=plan_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            estado_id=estado_id,
            sucursal_id=sucursal_id or cliente.sucursal_id,
            promocion_id=promocion_id,
            tipo_uso=tipo_uso,
            cupo_marcajes=cupo_marcajes,
            marcajes_usados=0,
            tipo_creacion=tipo_creacion,
        )

        db.session.add(membresia)
        db.session.commit()

        return True, membresia, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error creating membership: {e}")
        except Exception:
            pass
        return False, None, str(e)


def update_membership(membresia_id, **kwargs):
    """Update membership fields with validation.

    Allowed fields: plan_id, fecha_inicio, fecha_fin, estado_id, promocion_id
    Returns (success: bool, error_msg: str or None)
    """
    try:
        membresia = Membresia.query.get(membresia_id)
        if not membresia:
            return False, "Membresía no existe"

        allowed_fields = {"plan_id", "fecha_inicio", "fecha_fin", "estado_id", "promocion_id"}
        updates = {key: value for key, value in kwargs.items() if key in allowed_fields}

        new_plan = membresia.plan
        if "plan_id" in updates and updates.get("plan_id"):
            new_plan = Plan.query.get(updates.get("plan_id"))
            if not new_plan or getattr(new_plan, "estado", None) != "Activo":
                return False, "Plan no válido o inactivo"
            tipo_uso, cupo_marcajes = _resolve_usage_config(new_plan)
            updates["tipo_uso"] = tipo_uso
            updates["cupo_marcajes"] = cupo_marcajes
            updates["marcajes_usados"] = 0

        new_fecha_inicio = updates.get("fecha_inicio", membresia.fecha_inicio)
        if isinstance(new_fecha_inicio, str):
            try:
                new_fecha_inicio = datetime.strptime(new_fecha_inicio, "%Y-%m-%d").date()
                updates["fecha_inicio"] = new_fecha_inicio
            except ValueError:
                return False, "Formato de fecha de inicio inválido. Debe ser YYYY-MM-DD"

        explicit_fecha_fin = "fecha_fin" in updates
        new_fecha_fin = updates.get("fecha_fin", membresia.fecha_fin)
        if isinstance(new_fecha_fin, str):
            try:
                new_fecha_fin = datetime.strptime(new_fecha_fin, "%Y-%m-%d").date()
                updates["fecha_fin"] = new_fecha_fin
            except ValueError:
                return False, "Formato de fecha de fin inválido. Debe ser YYYY-MM-DD"

        if ("plan_id" in updates or "fecha_inicio" in updates) and not explicit_fecha_fin:
            if not new_plan:
                return False, "Plan no válido o inactivo"
            new_fecha_fin = compute_end_date(new_fecha_inicio, new_plan)
            if not new_fecha_fin:
                return False, "No se pudo calcular fecha de fin"
            updates["fecha_fin"] = new_fecha_fin

        if new_fecha_inicio and new_fecha_fin and new_fecha_fin <= new_fecha_inicio:
            return False, "Fecha fin debe ser posterior a fecha inicio"

        if "estado_id" in updates and updates.get("estado_id"):
            estado = EstadoMembresia.query.get(updates.get("estado_id"))
            if not estado:
                return False, "Estado no válido"

        for key, value in updates.items():
            setattr(membresia, key, value)

        db.session.commit()
        return True, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error updating membership: {e}")
        except Exception:
            pass
        return False, str(e)
