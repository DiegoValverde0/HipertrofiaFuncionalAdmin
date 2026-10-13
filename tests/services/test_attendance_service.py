from datetime import date, datetime, timedelta

from gym_admin.models import Plan, Membresia
from gym_admin.services.attendance_service import (
    manual_attendance_summary,
    register_manual_attendance,
)
from gym_admin.services.membership_service import create_membership


def test_register_manual_attendance_flow(db_session, cliente, estados_membresia):
    """Test manual attendance registration with daily limit and quota exhaustion."""
    plan_manual = Plan(
        nombre="Pack manual",
        descripcion="30 marcajes en 2 meses",
        duracion="2 meses",
        duracion_tipo="meses",
        duracion_valor=2,
        tipo_uso="asistencia_manual",
        cupo_marcajes=2,
        precio=80.00,
        tipo="Basico",
    )
    db_session.add(plan_manual)
    db_session.commit()

    success, membresia, error = create_membership(
        cliente_id=cliente.id,
        plan_id=plan_manual.id,
        fecha_inicio=date(2026, 7, 1).strftime("%Y-%m-%d"),
        estado_id=estados_membresia[2].id,
    )

    assert success is True
    assert error is None
    assert isinstance(membresia, Membresia)
    assert membresia.tipo_uso == "asistencia_manual"
    assert membresia.cupo_marcajes == 2
    assert membresia.marcajes_usados == 0

    first_day = date(2026, 7, 2)
    ok, payload, err = register_manual_attendance(
        membresia.id,
        usuario_id=None,
        sucursal_id=cliente.sucursal_id,
        registered_at=datetime.combine(first_day, datetime.min.time()),
    )
    assert ok is True
    assert err is None
    assert payload["usados"] == 1
    assert payload["restantes"] == 1

    same_day_ok, _, same_day_err = register_manual_attendance(
        membresia.id,
        usuario_id=None,
        sucursal_id=cliente.sucursal_id,
        registered_at=datetime.combine(first_day, datetime.min.time()) + timedelta(hours=3),
    )
    assert same_day_ok is False
    assert "mismo" in same_day_err.lower() or "día" in same_day_err.lower()

    second_day = first_day + timedelta(days=1)
    ok, payload, err = register_manual_attendance(
        membresia.id,
        usuario_id=None,
        sucursal_id=cliente.sucursal_id,
        registered_at=datetime.combine(second_day, datetime.min.time()),
    )
    assert ok is True
    assert err is None
    assert payload["usados"] == 2
    assert payload["restantes"] == 0
    assert membresia.estado_id == estados_membresia[4].id

    summary = manual_attendance_summary(membresia)
    assert summary["puede_marcar"] is False
    assert summary["restantes"] == 0

    third_day = second_day + timedelta(days=1)
    third_ok, _, third_err = register_manual_attendance(
        membresia.id,
        usuario_id=None,
        sucursal_id=cliente.sucursal_id,
        registered_at=datetime.combine(third_day, datetime.min.time()),
    )
    assert third_ok is False
    assert "cupo" in third_err.lower() or "disponible" in third_err.lower()
