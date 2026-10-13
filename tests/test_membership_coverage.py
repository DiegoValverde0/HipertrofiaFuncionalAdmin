"""Cobertura de membresías: una renovación pagada en espera evita "por vencer"."""

from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from gym_admin.extensions import db
from gym_admin.models import HistorialPago, Membresia, Pago, Role, Usuario
from gym_admin.services import membership_service
from gym_admin.services.membership_service import compute_coverage, local_today
from gym_admin.blueprints.clientes import _compute_client_flags_global


def _membresia(cliente, plan, estado_id, start, end, pagado=None):
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=plan.id,
        fecha_inicio=start,
        fecha_fin=end,
        estado_id=estado_id,
    )
    db.session.add(m)
    db.session.flush()
    if pagado is not None:
        pago = Pago(
            cliente_id=cliente.id,
            membresia_id=m.id,
            sucursal_id=cliente.sucursal_id,
            monto_total=pagado,
        )
        db.session.add(pago)
        db.session.flush()
        db.session.add(HistorialPago(pago_id=pago.id, monto_pagado=pagado))
    db.session.commit()
    return m


@pytest.fixture
def hoy():
    return local_today()


def test_renovacion_pagada_en_espera_no_esta_por_vencer(
    db_session, cliente, plan, estados_membresia, hoy
):
    """Caso reportado: activa que vence hoy + renovación pagada desde mañana."""
    actual = _membresia(cliente, plan, 2, hoy - timedelta(days=30), hoy)
    renovacion = _membresia(
        cliente, plan, 5, hoy + timedelta(days=1), hoy + timedelta(days=31), pagado=100
    )

    coverage = compute_coverage(cliente.membresias)
    assert coverage["has"] is True
    assert coverage["soon"] is False
    assert coverage["coverage_end"] == renovacion.fecha_fin

    flags = _compute_client_flags_global([cliente])
    assert flags[cliente.id]["soon"] is False

    status = membership_service.get_membership_status(cliente.id)
    assert status["soon"] is False
    assert status["last_id"] == renovacion.id
    assert actual.id != status["last_id"]


def test_activa_sin_renovacion_esta_por_vencer(
    db_session, cliente, plan, estados_membresia, hoy
):
    _membresia(cliente, plan, 2, hoy - timedelta(days=27), hoy + timedelta(days=3))

    flags = _compute_client_flags_global([cliente])
    assert flags[cliente.id]["soon"] is True
    assert flags[cliente.id]["fecha_fin"] == str(hoy + timedelta(days=3))


def test_renovacion_en_espera_sin_pagar_no_cuenta(
    db_session, cliente, plan, estados_membresia, hoy
):
    _membresia(cliente, plan, 2, hoy - timedelta(days=30), hoy)
    _membresia(cliente, plan, 5, hoy + timedelta(days=1), hoy + timedelta(days=31), pagado=40)

    coverage = compute_coverage(cliente.membresias)
    assert coverage["soon"] is True
    assert coverage["coverage_end"] == hoy


@pytest.fixture
def logged_client(app, db_session, sucursal):
    db.session.add(Role(id=1, nombre="admin"))
    db.session.add(
        Usuario(
            id=1,
            nombre="Recepción",
            correo="recepcion@test.com",
            contrasena=generate_password_hash("pw"),
            rol_id=1,
            sucursal_id=sucursal.id,
            estado=True,
        )
    )
    db.session.commit()
    client = app.test_client()
    resp = client.post(
        "/auth/login", data={"correo": "recepcion@test.com", "contrasena": "pw"}
    )
    assert resp.status_code == 302 and "/auth/login" not in resp.headers["Location"]
    return client


def test_busqueda_muestra_renovacion(logged_client, cliente, plan, estados_membresia, hoy):
    _membresia(cliente, plan, 2, hoy - timedelta(days=30), hoy)
    _membresia(cliente, plan, 5, hoy + timedelta(days=1), hoy + timedelta(days=31), pagado=100)

    resp = logged_client.get("/membresias/search_clientes?q=John")
    assert resp.status_code == 200
    (item,) = resp.get_json()
    assert item["has_membresia"] is True
    assert item["soon"] is False


def test_busqueda_no_falla_si_el_estado_de_un_cliente_falla(
    logged_client, cliente, estados_membresia, monkeypatch
):
    def boom(_cliente_id, horizon_days=7):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(
        "gym_admin.blueprints.membresias.get_membership_status", boom
    )
    resp = logged_client.get("/membresias/search_clientes?q=John")
    assert resp.status_code == 200
    (item,) = resp.get_json()
    assert item["id"] == cliente.id
    assert item["has_membresia"] is False
