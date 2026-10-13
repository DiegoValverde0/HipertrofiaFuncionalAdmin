"""
Membership state batch processing service.

Handles automatic state transitions for memberships and clients based on:
- Membership expiry dates (fecha_fin)
- Payment completion
- Client membership statuses

Functions here run as background batch jobs, typically triggered post-login
or via scheduled tasks.
"""
from datetime import date
from decimal import Decimal
from flask import current_app
from ..extensions import db
from ..models import Membresia, Cliente, EstadoMembresia
from ..utils import _compute_monto_total_for_membresia


def process_membership_states(target_membresia_id=None, client_id=None):
    """
    Process automatic state changes for memberships:
    - Mark expired (fecha_fin < today) as 'Vencida' (estado_id=6)
    - Promote 'En espera' (5) to 'Activa' (2) when fecha_inicio <= today (if no active exists)
    - Update states based on payment completion

    Args:
        target_membresia_id: Process specific membership (int)
        client_id: Process all memberships for a client (int)
    """
    today = date.today()
    vencida_id = None

    # Ensure 'Vencida' estado exists
    try:
        vencida_obj = EstadoMembresia.query.filter(
            EstadoMembresia.nombre.ilike("vencid%")
        ).first()
        if not vencida_obj:
            vencida_obj = EstadoMembresia.query.filter_by(id=6).first()
        if not vencida_obj:
            vencida_obj = EstadoMembresia(nombre="Vencida")
            db.session.add(vencida_obj)
            db.session.flush()
        vencida_id = vencida_obj.id if vencida_obj else 6
    except Exception:
        vencida_id = 6

    # 1) Mark expired memberships as 'Vencida'
    try:
        exclusion = [3, 4, vencida_id] if vencida_id else [3, 4]
        updated = (
            db.session.query(Membresia)
            .filter(Membresia.fecha_fin < today, Membresia.estado_id.notin_(exclusion))
            .update({"estado_id": vencida_id}, synchronize_session="fetch")
        )
        current_app.logger.debug("Memberships marked expired: %d", updated)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error marking expired memberships")

    # 2) Promote 'En espera' to 'Activa' if fecha_inicio <= today
    try:
        waiting = Membresia.query.filter(
            Membresia.estado_id == 5, Membresia.fecha_inicio <= today
        ).all()
        for w in waiting:
            # Only promote if no active membership exists for this client
            has_active = Membresia.query.filter(
                Membresia.cliente_id == w.cliente_id, Membresia.estado_id == 2
            ).first()
            if not has_active:
                w.estado_id = 2
                db.session.add(w)
                try:
                    w.cliente.estado = "Activo"
                    db.session.add(w.cliente)
                except Exception:
                    pass
        db.session.commit()
        current_app.logger.debug("Promoted waiting memberships to active: %d", len(waiting))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error promoting waiting memberships")

    # 3) Process payment completion and update states
    targets = []
    if target_membresia_id:
        mm = Membresia.query.get(target_membresia_id)
        if mm:
            targets.append(mm)
    elif client_id:
        targets = Membresia.query.filter_by(cliente_id=client_id).all()
    else:
        exclusion = [3, 4]
        if vencida_id:
            exclusion.append(vencida_id)
        targets = Membresia.query.filter(Membresia.estado_id.notin_(exclusion)).all()

    for m in targets:
        try:
            if (getattr(m, "tipo_uso", "") or "").lower() == "asistencia_manual":
                cupo = int(getattr(m, "cupo_marcajes", 0) or 0)
                usados = int(getattr(m, "marcajes_usados", 0) or 0)
                if cupo and usados >= cupo:
                    if m.estado_id != 4:
                        m.estado_id = 4
                        db.session.add(m)
                    continue
        except Exception:
            pass

        total_due = _compute_monto_total_for_membresia(m)
        total_paid = Decimal("0")

        try:
            for p in m.pagos:
                for h in p.historial:
                    try:
                        total_paid += Decimal(h.monto_pagado)
                    except Exception:
                        pass
        except Exception:
            current_app.logger.exception("Error calculating total paid for membership %d", m.id)

        # If payment is complete, update state
        if total_due > 0 and total_paid >= total_due:
            desired = None

            # If membership starts in future, leave in 'En espera' (5)
            if m.fecha_inicio and m.fecha_inicio > today:
                desired = 5
            else:
                # Check if another active membership exists
                active_other = Membresia.query.filter(
                    Membresia.cliente_id == m.cliente_id,
                    Membresia.estado_id == 2,
                    Membresia.id != m.id,
                ).first()
                desired = 5 if active_other else 2

            if desired and m.estado_id != desired:
                m.estado_id = desired
                db.session.add(m)
                if desired == 2:
                    try:
                        m.cliente.estado = "Activo"
                        db.session.add(m.cliente)
                    except Exception:
                        pass

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error updating membership states")

    # 4) Sync client states
    try:
        clients_to_check = set()
        if target_membresia_id:
            m0 = Membresia.query.get(target_membresia_id)
            if m0:
                clients_to_check.add(m0.cliente_id)
        if client_id:
            clients_to_check.add(client_id)

        if clients_to_check:
            sync_client_states(clients_to_check)
        else:
            sync_client_states()
    except Exception:
        current_app.logger.exception("Error synchronizing client states")


def sync_client_states(target_ids=None):
    """
    Synchronize Cliente.estado field based on membership statuses:
    - Clients with estado_id=2 or 5 → estado='Activo'
    - Clients with no memberships or only expired → estado='Inactivo'

    Args:
        target_ids: Set of client IDs to update (optional). If None, updates all.
    """
    try:
        # Find clients with active/waiting memberships
        active_rows = (
            db.session.query(Membresia.cliente_id)
            .filter(Membresia.estado_id.in_([2, 5]))
            .distinct()
            .all()
        )
        active_ids = set([r[0] for r in active_rows])

        if target_ids:
            for cid in target_ids:
                cliente = Cliente.query.get(cid)
                if not cliente:
                    continue
                desired = "Activo" if cid in active_ids else "Inactivo"
                if cliente.estado != desired:
                    cliente.estado = desired
                    db.session.add(cliente)
            db.session.commit()
        else:
            for cliente in Cliente.query.all():
                desired = "Activo" if cliente.id in active_ids else "Inactivo"
                if cliente.estado != desired:
                    cliente.estado = desired
                    db.session.add(cliente)
            db.session.commit()

        current_app.logger.debug("Client states synchronized")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error synchronizing client states")


def cancel_pending_memberships_with_past_start():
    """
    Mark pending memberships (estado_id=1) with fecha_inicio in the past as cancelled (3).
    Used to prevent offering expired pending memberships for checkout.

    Returns:
        int: Number of memberships cancelled
    """
    try:
        today = date.today()
        expired = Membresia.query.filter(
            Membresia.estado_id == 1,
            Membresia.fecha_inicio != None,
            Membresia.fecha_inicio < today,
        ).all()

        if not expired:
            return 0

        for m in expired:
            m.estado_id = 3  # Cancelled
            db.session.add(m)

        db.session.commit()
        current_app.logger.debug("Cancelled %d pending memberships with past start", len(expired))
        return len(expired)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error cancelling pending memberships with past start")
        return 0
