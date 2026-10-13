import pytest
from datetime import date, timedelta
from gym_admin.services.membership_state_service import (
    process_membership_states,
    sync_client_states,
    cancel_pending_memberships_with_past_start
)
from gym_admin.models import Membresia

@pytest.fixture
def base_data(db_session, cliente, plan, estados_membresia):
    return {
        "cliente": cliente,
        "plan": plan,
        "estados": estados_membresia
    }

def test_cancel_pending_memberships_with_past_start(db_session, base_data):
    """Test cancelling pending memberships that started in the past."""
    # Pending membership with past start date (3 days ago)
    m = Membresia(
        cliente_id=base_data["cliente"].id,
        sucursal_id=base_data["cliente"].sucursal_id,
        plan_id=base_data["plan"].id,
        fecha_inicio=date.today() - timedelta(days=3),
        fecha_fin=date.today() + timedelta(days=27),
        estado_id=base_data["estados"][1].id # Pendiente
    )
    db_session.add(m)
    db_session.commit()
    
    count = cancel_pending_memberships_with_past_start()
    
    assert count == 1
    db_session.refresh(m)
    assert m.estado_id == base_data["estados"][3].id # Anulada

def test_process_membership_states_activates_waiting(db_session, base_data):
    """Test process_membership_states transitions 'En espera' to 'Activa'."""
    # Membership 'En espera' whose start date is today
    m = Membresia(
        cliente_id=base_data["cliente"].id,
        sucursal_id=base_data["cliente"].sucursal_id,
        plan_id=base_data["plan"].id,
        fecha_inicio=date.today(),
        fecha_fin=date.today() + timedelta(days=30),
        estado_id=base_data["estados"][5].id # En espera
    )
    db_session.add(m)
    db_session.commit()
    
    process_membership_states()
    
    db_session.refresh(m)
    assert m.estado_id == base_data["estados"][2].id # Activa

def test_process_membership_states_inactivates_expired(db_session, base_data):
    """Test process_membership_states transitions expired 'Activa' to 'Inactiva'."""
    # Active membership whose end date was yesterday
    m = Membresia(
        cliente_id=base_data["cliente"].id,
        sucursal_id=base_data["cliente"].sucursal_id,
        plan_id=base_data["plan"].id,
        fecha_inicio=date.today() - timedelta(days=30),
        fecha_fin=date.today() - timedelta(days=1),
        estado_id=base_data["estados"][2].id # Activa
    )
    db_session.add(m)
    db_session.commit()
    
    process_membership_states()
    
    db_session.refresh(m)
    from gym_admin.models import EstadoMembresia
    vencida = EstadoMembresia.query.filter_by(nombre="Vencida").first()
    assert m.estado_id == vencida.id # Vencida

def test_sync_client_states(db_session, base_data):
    """Test that sync_client_states updates client's estado attribute."""
    cliente = base_data["cliente"]
    cliente.estado = "Inactivo"
    db_session.commit()
    
    # Active membership
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=base_data["plan"].id,
        fecha_inicio=date.today(),
        fecha_fin=date.today() + timedelta(days=30),
        estado_id=base_data["estados"][2].id # Activa
    )
    db_session.add(m)
    db_session.commit()
    
    sync_client_states()
    
    db_session.refresh(cliente)
    assert cliente.estado == "Activo"
