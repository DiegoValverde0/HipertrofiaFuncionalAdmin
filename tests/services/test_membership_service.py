from datetime import date, timedelta
from gym_admin.services.membership_service import (
    create_membership, 
    compute_end_date, 
    get_membership_status,
    update_membership,
)
from gym_admin.models import Membresia, Plan

def test_compute_fecha_fin():
    """Los meses cuentan el día de inicio: el fin es el día anterior al aniversario."""
    start = date(2023, 1, 10)  # martes

    assert compute_end_date(start, "1 mes") == date(2023, 2, 9)        # jueves
    assert compute_end_date(start, "Trimestral") == date(2023, 4, 10)  # 09/04 domingo -> lunes
    assert compute_end_date(start, "Semestral") == date(2023, 7, 10)   # 09/07 domingo -> lunes
    assert compute_end_date(start, "Anual") == date(2024, 1, 9)


def test_renovacion_mensual_no_corre_el_dia(db_session, cliente, plan, estados_membresia):
    """Cada extensión empieza el mismo día del mes, aunque el fin caiga en fin de semana."""
    from gym_admin.services.membership_service import extension_start_date
    from gym_admin.extensions import db

    plan.duracion_tipo, plan.duracion_valor = "meses", 1
    inicio = date(2026, 3, 10)
    for esperado in [date(2026, 4, 10), date(2026, 5, 10), date(2026, 6, 10), date(2026, 7, 10)]:
        m = Membresia(cliente_id=cliente.id, sucursal_id=cliente.sucursal_id, plan_id=plan.id,
                      fecha_inicio=inicio, fecha_fin=compute_end_date(inicio, plan), estado_id=2)
        db.session.add(m)
        db.session.flush()
        inicio = extension_start_date(m)
        assert inicio == esperado
        # el fin de la anterior (corrido al lunes) nunca deja un hueco
        assert m.fecha_fin >= inicio - timedelta(days=1)


def test_extension_tras_fin_manual_empieza_al_dia_siguiente(db_session, cliente, plan, estados_membresia):
    from gym_admin.services.membership_service import extension_start_date

    m = Membresia(cliente_id=cliente.id, sucursal_id=cliente.sucursal_id, plan_id=plan.id,
                  fecha_inicio=date(2026, 3, 10), fecha_fin=date(2026, 4, 22), estado_id=2)
    db_session.add(m)
    db_session.flush()
    assert extension_start_date(m) == date(2026, 4, 23)


def test_compute_fecha_fin_custom_days(db_session):
    """Test the new configurable day-based duration."""
    plan_custom = Plan(
        nombre="Pack 15 días",
        descripcion="Plan flexible",
        duracion="15 días",
        duracion_tipo="dias",
        duracion_valor=15,
        precio=50.00,
        tipo="Basico",
    )
    db_session.add(plan_custom)
    db_session.commit()

    start = date(2026, 7, 1)
    fin = compute_end_date(start, plan_custom)

    assert fin == date(2026, 7, 15)

def test_create_membership_success(db_session, cliente, plan, estados_membresia):
    """Test successful membership creation."""
    start_date = date.today()
    success, result, error = create_membership(
        cliente_id=cliente.id,
        plan_id=plan.id,
        fecha_inicio=start_date.strftime("%Y-%m-%d"),
        estado_id=1
    )
    
    assert success is True
    assert error is None
    assert isinstance(result, Membresia)
    assert result.cliente_id == cliente.id
    assert result.plan_id == plan.id
    assert result.is_pendiente is True
    assert result.fecha_inicio == start_date
    assert result.fecha_fin is not None
    assert result.sucursal_id == cliente.sucursal_id

def test_create_membership_with_promotions(db_session, cliente, plan, promocion, estados_membresia):
    """Test membership creation with a promotion."""
    success, result, error = create_membership(
        cliente_id=cliente.id,
        plan_id=plan.id,
        promocion_id=promocion.id,
        fecha_inicio=date.today().strftime("%Y-%m-%d"),
        estado_id=1
    )
    
    assert success is True
    assert result.promocion_id == promocion.id
    
    # The actual discount calculation happens in _compute_monto_total_for_membresia during payment
    # Here we just assert the relationship is established

def test_create_membership_invalid_client(db_session, plan):
    """Test creation with invalid client fails."""
    success, result, error = create_membership(
        cliente_id=999,
        plan_id=plan.id,
        fecha_inicio="2023-01-01",
        estado_id=1
    )
    
    assert success is False
    assert result is None
    assert "Cliente no existe" in error

def test_create_membership_invalid_plan(db_session, cliente):
    """Test creation with invalid plan fails."""
    success, result, error = create_membership(
        cliente_id=cliente.id,
        plan_id=999,
        fecha_inicio="2023-01-01",
        estado_id=1
    )
    
    assert success is False
    assert "Plan no existe o inactivo" in error


def test_update_membership_recalculates_fecha_fin_when_plan_changes(db_session, cliente, plan, estados_membresia):
    """Test that editing a membership recomputes the end date when the plan changes."""
    plan_trimestral = Plan(
        nombre="Trimestral",
        descripcion="Plan de tres meses",
        duracion="Trimestral",
        precio=250.00,
        tipo="Basico",
    )
    db_session.add(plan_trimestral)
    db_session.commit()

    start_date = date(2026, 5, 4)
    membresia = Membresia(
        cliente_id=cliente.id,
        plan_id=plan.id,
        sucursal_id=cliente.sucursal_id,
        fecha_inicio=start_date,
        fecha_fin=compute_end_date(start_date, plan.duracion),
        estado_id=estados_membresia[1].id,
    )
    db_session.add(membresia)
    db_session.commit()

    success, error = update_membership(membresia.id, plan_id=plan_trimestral.id)

    assert success is True
    assert error is None
    assert membresia.plan_id == plan_trimestral.id
    assert membresia.fecha_fin == compute_end_date(start_date, plan_trimestral.duracion)


def test_update_membership_recalculates_fecha_fin_when_start_changes(db_session, cliente, plan, estados_membresia):
    """Test that editing a membership recomputes the end date when the start date changes."""
    start_date = date(2026, 5, 4)
    new_start_date = date(2026, 6, 2)
    membresia = Membresia(
        cliente_id=cliente.id,
        plan_id=plan.id,
        sucursal_id=cliente.sucursal_id,
        fecha_inicio=start_date,
        fecha_fin=compute_end_date(start_date, plan.duracion),
        estado_id=estados_membresia[1].id,
    )
    db_session.add(membresia)
    db_session.commit()

    success, error = update_membership(membresia.id, fecha_inicio=new_start_date)

    assert success is True
    assert error is None
    assert membresia.fecha_inicio == new_start_date
    assert membresia.fecha_fin == compute_end_date(new_start_date, plan.duracion)

def test_get_membership_status(db_session, cliente, plan, estados_membresia):
    """Test resolving membership status dynamically."""
    # Create active membership ending tomorrow
    m_activa = Membresia(
        cliente_id=cliente.id, 
        plan_id=plan.id, 
        sucursal_id=cliente.sucursal_id,
        fecha_inicio=date.today() - timedelta(days=10),
        fecha_fin=date.today() + timedelta(days=1),
        estado_id=estados_membresia[2].id # Activa
    )
    db_session.add(m_activa)
    db_session.commit()
    
    status = get_membership_status(cliente.id)
    assert status["has"] is True
    assert status["soon"] is True # 1 day left <= 5 days
    assert status["last_id"] == m_activa.id
    
    # Update to end next month
    m_activa.fecha_fin = date.today() + timedelta(days=30)
    db_session.commit()
    
    status = get_membership_status(cliente.id)
    assert status["has"] is True
    assert status["soon"] is False # 30 days > 5 days

    # Test "En espera" state
    m_activa.estado_id = estados_membresia[5].id # En espera
    db_session.commit()
    
    # We must add a payment to make "En espera" count as active
    from gym_admin.models import Pago, HistorialPago
    pago = Pago(membresia_id=m_activa.id, cliente_id=cliente.id, sucursal_id=cliente.sucursal_id, monto_total=100.0)
    db_session.add(pago)
    db_session.commit()
    hist = HistorialPago(pago_id=pago.id, monto_pagado=100.0, metodo_pago="Efectivo")
    db_session.add(hist)
    db_session.commit()
    db_session.refresh(m_activa)
    
    status = get_membership_status(cliente.id)
    assert status["has"] is True # En espera with payment counts as active
