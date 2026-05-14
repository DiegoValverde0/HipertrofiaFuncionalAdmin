import pytest
from datetime import date, timedelta
from gym_admin.services.promotion_service import sync_promociones_by_date
from gym_admin.models import Promocion

def test_sync_promociones_by_date(db_session):
    """Test sync_promociones_by_date changes states correctly."""
    today = date.today()
    
    # Promo starts tomorrow -> should be Inactivo
    p1 = Promocion(
        nombre="Future Promo",
        fecha_inicio=today + timedelta(days=1),
        fecha_fin=today + timedelta(days=10),
        estado="Activo"
    )
    # Promo ended yesterday -> should be Inactivo
    p2 = Promocion(
        nombre="Past Promo",
        fecha_inicio=today - timedelta(days=10),
        fecha_fin=today - timedelta(days=1),
        estado="Activo"
    )
    # Promo currently active (started yesterday, ends tomorrow) -> should be Activo
    p3 = Promocion(
        nombre="Current Promo",
        fecha_inicio=today - timedelta(days=1),
        fecha_fin=today + timedelta(days=1),
        estado="Inactivo" # Setting to Inactivo to see if it activates
    )
    
    db_session.add_all([p1, p2, p3])
    db_session.commit()
    
    activadas, inactivadas = sync_promociones_by_date(today)
    
    # Results Check
    assert p3.id in activadas
    assert p1.id in inactivadas
    assert p2.id in inactivadas
    
    db_session.refresh(p1)
    db_session.refresh(p2)
    db_session.refresh(p3)
    
    assert p1.estado == "Inactivo"
    assert p2.estado == "Inactivo"
    assert p3.estado == "Activo"
