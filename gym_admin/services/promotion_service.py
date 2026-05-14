"""
Promotion batch processing service.

Handles automatic state transitions for promotions based on activation/expiry dates.
"""
from datetime import date
from flask import current_app
from ..extensions import db
from ..models import Promocion


def sync_promociones_by_date(today=None):
    """
    Synchronize Promocion.estado based on fecha_inicio and fecha_fin:
    - If fecha_fin < today and estado != 'Inactivo' → mark as 'Inactivo'
    - If fecha_inicio <= today <= fecha_fin → mark as 'Activo'
    - If fecha_fin is None and fecha_inicio <= today → mark as 'Activo'

    Args:
        today: Reference date for comparison (defaults to date.today())

    Returns:
        tuple: (activadas, desactivadas) lists of promotion IDs
    """
    today = today or date.today()
    activadas = []
    desactivadas = []

    try:
        # Deactivate expired or future promotions
        try:
            from sqlalchemy import or_
            vencidas = Promocion.query.filter(
                or_(
                    Promocion.fecha_fin < today,
                    Promocion.fecha_inicio > today
                ),
                Promocion.estado != "Inactivo",
            ).all()

            for p in vencidas:
                p.estado = "Inactivo"
                db.session.add(p)
                desactivadas.append(p.id)

            current_app.logger.debug("Deactivated %d expired promotions", len(desactivadas))
        except Exception:
            current_app.logger.exception("Error deactivating expired promotions")

        # Activate promotions that have started
        try:
            potenciales = Promocion.query.filter(
                Promocion.fecha_inicio != None, Promocion.fecha_inicio <= today
            ).all()

            for p in potenciales:
                # Skip if it has an expiry date that has passed (already handled above)
                if p.fecha_fin and p.fecha_fin < today:
                    continue

                if p.estado != "Activo":
                    p.estado = "Activo"
                    db.session.add(p)
                    activadas.append(p.id)

            current_app.logger.debug("Activated %d promotions", len(activadas))
        except Exception:
            current_app.logger.exception("Error activating promotions")

        # Commit changes
        if activadas or desactivadas:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Error committing promotion state changes")

        current_app.logger.debug(
            "Promotion sync complete: activated=%d, deactivated=%d",
            len(activadas),
            len(desactivadas),
        )

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error synchronizing promotions by date")

    return (activadas, desactivadas)
