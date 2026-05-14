"""Membership service layer - business logic for membresia management."""
from datetime import datetime, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from flask import current_app
from ..extensions import db
from ..models import Membresia, Cliente, Plan, EstadoMembresia, Pago
from ..utils import _compute_monto_total_for_membresia


def get_membership_status(cliente_id, horizon_days=7):
    """Get current membership status for a client.

    Returns dict with:
    - has: bool (client has active membership)
    - soon: bool (expires within horizon_days)
    - last_id: id of last/active membership
    - last_fecha_fin: expiration date of last
    - last_estado: state of last
    """
    try:
        membresias = Membresia.query.filter_by(cliente_id=cliente_id).all()
    except Exception as e:
        try:
            current_app.logger.exception(
                f"Error fetching memberships for cliente {cliente_id}: {e}"
            )
        except Exception:
            pass
        return {
            "has": False,
            "soon": False,
            "last_id": None,
            "last_fecha_fin": None,
            "last_estado": None,
        }

    if not membresias:
        return {
            "has": False,
            "soon": False,
            "last_id": None,
            "last_fecha_fin": None,
            "last_estado": None,
        }

    # Dynamically resolve status IDs
    activa_ids = {2}
    espera_ids = {5}
    try:
        activa_objs = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("activ%")).all()
        espera_objs = EstadoMembresia.query.filter(
            EstadoMembresia.nombre.ilike("%espera%") | EstadoMembresia.nombre.ilike("%en espera%")
        ).all()
        if activa_objs:
            activa_ids = {e.id for e in activa_objs if getattr(e, "id", None) is not None}
        if espera_objs:
            espera_ids = {e.id for e in espera_objs if getattr(e, "id", None) is not None}
    except Exception:
        pass

    # Build candidate list: active or en espera (fully paid)
    candidates = []
    for m in membresias:
        try:
            if m.estado_id in activa_ids:
                candidates.append(m)
                continue
            if m.estado_id in espera_ids:
                total_due = _compute_monto_total_for_membresia(m)
                total_paid = Decimal("0")
                for pago in m.pagos:
                    for hist in pago.historial:
                        try:
                            total_paid += Decimal(hist.monto_pagado)
                        except Exception:
                            pass
                if total_due and total_paid >= total_due:
                    candidates.append(m)
        except Exception:
            continue

    # Select membership with the furthest fecha_fin among valid candidates
    best_membresia = None
    if candidates:
        best_membresia = max(candidates, key=lambda mm: mm.fecha_fin or datetime.min.date())
    else:
        # fallback to most recent by fecha_inicio when none are active/paid
        best_membresia = max(membresias, key=lambda mm: mm.fecha_inicio or datetime.min)

    has_active = bool(candidates)

    # Check if expires soon (only meaningful when active/paid)
    soon = False
    if has_active and best_membresia and best_membresia.fecha_fin:
        days_until = (best_membresia.fecha_fin - datetime.now().date()).days
        if 0 <= days_until <= horizon_days:
            soon = True

    return {
        "has": has_active,
        "soon": soon,
        "last_id": best_membresia.id if best_membresia else None,
        "last_fecha_fin": best_membresia.fecha_fin if best_membresia else None,
        "last_estado": best_membresia.estado_id if best_membresia else None,
    }


def compute_end_date(fecha_inicio, duracion_str):
    """Compute membership end date given start date and plan duration string.

    Plan duration string: 'Mensual', 'Trimestral', 'Semestral', 'Anual'
    Adjusts to next Monday if falls on weekend.
    """
    try:
        if not fecha_inicio or not duracion_str:
            return None

        # Map duracion string to months
        duracion_map = {
            'Mensual': 1,
            'mensual': 1,
            'Trimestral': 3,
            'trimestral': 3,
            'Semestral': 6,
            'semestral': 6,
            'Anual': 12,
            'anual': 12,
        }
        months = duracion_map.get(duracion_str, 1)

        # Add exact months using relativedelta
        end_date = fecha_inicio + relativedelta(months=months)

        # Adjust to Monday if on weekend
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
        fecha_fin = compute_end_date(fecha_inicio, plan.duracion)
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

        # Compute end date from plan unless explicitly provided (admin/manual override)
        if not fecha_fin:
            fecha_fin = compute_end_date(fecha_inicio, plan.duracion)
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
            new_fecha_fin = compute_end_date(new_fecha_inicio, new_plan.duracion)
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
