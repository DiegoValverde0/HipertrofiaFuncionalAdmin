"""Payment service layer - business logic for payment management."""
from flask import current_app
from ..extensions import db
from ..models import Pago, HistorialPago, Membresia
from ..utils import process_membership_states
from ..utils_timezone import utcnow


def create_payment(membresia_id, monto_total, metodo_pago="", comentarios=""):
    """Create a new payment record for a membership.

    Validates that membership is in estado_id=1 (Pendiente).
    Returns (success: bool, pago: Pago or None, error_msg: str or None)
    """
    try:
        # Validate membership exists and is in Pendiente state
        membresia = db.session.get(Membresia, membresia_id)
        if not membresia:
            return False, None, "Membresía no existe"

        if not getattr(membresia, "is_pendiente", False):
            return False, None, f"Membresía debe estar Pendiente, estado actual: {membresia.estado_membresia.nombre if membresia.estado_membresia else membresia.estado_id}"

        # Check if payment already exists
        existing_pago = Pago.query.filter_by(membresia_id=membresia_id).first()
        if existing_pago:
            return False, None, "Membresía ya tiene un pago registrado"

        # Validate monto_total > 0
        if not monto_total or monto_total <= 0:
            return False, None, "Monto debe ser mayor a 0"

        # Create payment
        pago = Pago(
            membresia_id=membresia_id,
            monto_total=monto_total,
            metodo_pago=metodo_pago,
            comentarios=comentarios,
            sucursal_id=membresia.sucursal_id,
        )

        db.session.add(pago)
        db.session.commit()

        return True, pago, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error creating payment: {e}")
        except Exception:
            pass
        return False, None, str(e)


def add_payment_history(pago_id, abono, metodo_pago="", comentarios=""):
    """Register a payment (abono) for a pago record.

    Supports partial payments and split methods (e.g., Efectivo + QR).
    Updates pago.monto_pagado and creates HistorialPago record.

    Returns (success: bool, historial: HistorialPago or None, error_msg: str or None)
    """
    try:
        pago = db.session.get(Pago, pago_id)
        if not pago:
            return False, None, "Pago no existe"

        # Validate abono
        if not abono or abono <= 0:
            return False, None, "Abono debe ser mayor a 0"

        # Check that total pagado doesn't exceed monto_total
        total_pagado = sum(
            h.monto_pagado for h in pago.historial if h.monto_pagado
        )
        nuevo_total = total_pagado + abono
        if nuevo_total > pago.monto_total:
            return False, None, (
                f"Abono excede monto total. Pagado: {total_pagado}, "
                f"Monto: {pago.monto_total}, Abono: {abono}"
            )

        # Create historial record
        historial = HistorialPago(
            pago_id=pago_id,
            monto_pagado=abono,
            metodo_pago=metodo_pago,
            comentarios=comentarios,
            fecha_pago=utcnow(),
        )

        if metodo_pago:
            pago.metodo_pago = metodo_pago
        if comentarios:
            pago.comentarios = comentarios

        db.session.add(historial)
        db.session.commit()

        return True, historial, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error adding payment history: {e}")
        except Exception:
            pass
        return False, None, str(e)


def ensure_membership_state_after_payment(membresia_id):
    """Transition membership state after payment.

    If pago.monto_pagado >= pago.monto, change membresia estado to 5 (En espera).
    Then call process_membership_states() to finalize transitions.

    Returns (success: bool, new_estado_id: int or None, error_msg: str or None)
    """
    try:
        membresia = db.session.get(Membresia, membresia_id)
        if not membresia:
            return False, None, "Membresía no existe"

        pago = Pago.query.filter_by(membresia_id=membresia_id).first()
        if not pago:
            return False, None, "Pago no existe para membresía"

        # Check if payment is complete
        total_pagado = sum(
            h.monto_pagado for h in pago.historial if h.monto_pagado
        )
        if total_pagado >= pago.monto_total:
            # Transition to "En espera"
            from ..models import EstadoMembresia
            espera_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("%espera%")).first()
            espera_id = espera_estado.id if espera_estado else 5
            
            if membresia.estado_id != espera_id:
                membresia.estado_id = espera_id
                db.session.commit()

        # Trigger process_membership_states to finalize
        try:
            process_membership_states()
        except Exception as e:
            try:
                current_app.logger.exception(
                    f"Error in process_membership_states: {e}"
                )
            except Exception:
                pass

        return True, membresia.estado_id, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(
                f"Error ensuring membership state after payment: {e}"
            )
        except Exception:
            pass
        return False, None, str(e)


def get_payment_with_history(pago_id):
    """Get payment record with full history.

    Returns dict with pago info and historial records ordered by date DESC.
    """
    try:
        pago = db.session.get(Pago, pago_id)
        if not pago:
            return None

        historial = (
            HistorialPago.query.filter_by(pago_id=pago_id)
            .order_by(HistorialPago.fecha_pago.desc())
            .all()
        )

        total_abonado = sum(h.monto_pagado for h in historial if h.monto_pagado)

        return {
            "pago": pago,
            "historial": historial,
            "total_abonado": total_abonado,
            "pendiente": max(0, pago.monto_total - total_abonado) if pago.monto_total else 0,
        }

    except Exception as e:
        try:
            current_app.logger.exception(f"Error fetching payment: {e}")
        except Exception:
            pass
        return None
