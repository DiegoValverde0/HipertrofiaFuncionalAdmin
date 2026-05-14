import pytest
from datetime import date, timedelta
from decimal import Decimal
from gym_admin.services.payment_service import (
    create_payment,
    add_payment_history,
    ensure_membership_state_after_payment,
    get_payment_with_history
)
from gym_admin.models import Membresia, Pago, HistorialPago

@pytest.fixture
def membresia_pendiente(db_session, cliente, plan, estados_membresia):
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=plan.id,
        fecha_inicio=date.today(),
        fecha_fin=date.today() + timedelta(days=30),
        estado_id=estados_membresia[1].id # Pendiente
    )
    db_session.add(m)
    db_session.commit()
    return m

@pytest.fixture
def membresia_activa(db_session, cliente, plan, estados_membresia):
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=plan.id,
        fecha_inicio=date.today(),
        fecha_fin=date.today() + timedelta(days=30),
        estado_id=estados_membresia[2].id # Activa
    )
    db_session.add(m)
    db_session.commit()
    return m

def test_create_payment_success(db_session, membresia_pendiente):
    """Test creating a payment for a pending membership."""
    success, pago, error = create_payment(
        membresia_id=membresia_pendiente.id,
        monto_total=Decimal("100.00"),
        metodo_pago="Efectivo",
        comentarios="Test"
    )
    
    assert success is True
    assert error is None
    assert isinstance(pago, Pago)
    assert pago.membresia_id == membresia_pendiente.id
    assert pago.monto_total == Decimal("100.00")
    assert pago.metodo_pago == "Efectivo"
    assert pago.sucursal_id == membresia_pendiente.sucursal_id

def test_create_payment_validates_pending(db_session, membresia_activa):
    """Test that payments can only be created for pending memberships."""
    success, pago, error = create_payment(
        membresia_id=membresia_activa.id,
        monto_total=Decimal("100.00")
    )
    
    assert success is False
    assert pago is None
    assert "Membresía debe estar Pendiente" in error

def test_add_payment_history_partial(db_session, membresia_pendiente):
    """Test adding partial payments."""
    _, pago, _ = create_payment(membresia_pendiente.id, Decimal("100.00"))
    
    # Add first partial payment
    success, hist, error = add_payment_history(
        pago_id=pago.id,
        abono=Decimal("40.00"),
        metodo_pago="Tarjeta"
    )
    
    assert success is True
    assert hist.monto_pagado == Decimal("40.00")
    assert hist.metodo_pago == "Tarjeta"
    
    # Ensure total is updated via relationship
    info = get_payment_with_history(pago.id)
    assert info["total_abonado"] == Decimal("40.00")
    assert info["pendiente"] == Decimal("60.00")

    # Overpaying should fail
    success, hist, error = add_payment_history(pago.id, Decimal("70.00"))
    assert success is False
    assert "Abono excede monto total" in error

def test_ensure_membership_state_after_full_payment(db_session, membresia_pendiente, estados_membresia):
    """Test that fully paying a membership updates its state."""
    _, pago, _ = create_payment(membresia_pendiente.id, Decimal("100.00"))
    add_payment_history(pago.id, Decimal("100.00"))
    
    success, new_state, error = ensure_membership_state_after_payment(membresia_pendiente.id)
    
    assert success is True
    # The state should be transitioned to "En espera" by payment service 
    # (then process_membership_states might make it Activa depending on dates, 
    # but here we test the primary transition in isolated DB context)
    db_session.refresh(membresia_pendiente)
    
    # Can be Activa (2) or En espera (5) depending on if another active exists and date logic
    assert membresia_pendiente.estado_id in (estados_membresia[2].id, estados_membresia[5].id)
