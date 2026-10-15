"""Coherencia de fechas de membresías: extensión y "hoy" en hora de Bolivia."""

from datetime import date, datetime, timedelta

from gym_admin.extensions import db
from gym_admin.models import Membresia
from gym_admin.services.membership_state_service import (
    cancel_pending_memberships_with_past_start,
    process_membership_states,
)
from gym_admin.utils_timezone import local_today


def _activar(plan):
    plan.estado = "Activo"
    db.session.commit()


def _membresia(cliente, plan, estado_id, inicio, fin):
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=plan.id,
        fecha_inicio=inicio,
        fecha_fin=fin,
        estado_id=estado_id,
    )
    db.session.add(m)
    db.session.commit()
    return m


def test_extension_guarda_las_fechas_de_la_vista_previa(
    logged_client, cliente, plan, estados_membresia
):
    _activar(plan)
    hoy = local_today()
    actual = _membresia(cliente, plan, 2, hoy - timedelta(days=20), hoy + timedelta(days=10))

    preview = logged_client.get(
        "/membresias/preview-dates",
        query_string={
            "fecha_inicio": hoy.isoformat(),
            "plan_id": plan.id,
            "opcion": "extend",
            "cliente_id": cliente.id,
        },
    ).get_json()
    resp = logged_client.post(
        "/membresias/create",
        data={
            "cliente_id": cliente.id,
            "plan_id": plan.id,
            "fecha_inicio": hoy.isoformat(),  # el formulario aún tenía "hoy"
            "opcion": "extend",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200, resp.get_json()

    nueva = Membresia.query.filter(Membresia.id != actual.id).one()
    assert nueva.fecha_inicio.isoformat() == preview["fecha_inicio"]
    assert nueva.fecha_fin.isoformat() == preview["fecha_fin"]
    assert nueva.fecha_inicio > actual.fecha_fin  # no se superpone con la vigente


def _noche_en_bolivia(monkeypatch):
    """21:00 del 15/10 en Bolivia = 01:00 UTC del 16/10."""
    monkeypatch.setattr(
        "gym_admin.utils_timezone.utcnow", lambda: datetime(2026, 10, 16, 1, 0)
    )
    return date(2026, 10, 15)


def test_de_noche_no_vence_la_membresia_que_termina_hoy(
    monkeypatch, db_session, cliente, plan, estados_membresia
):
    hoy = _noche_en_bolivia(monkeypatch)
    m = _membresia(cliente, plan, 2, hoy - timedelta(days=30), hoy)

    process_membership_states()

    assert db.session.get(Membresia, m.id).estado_id == 2


def test_de_noche_no_anula_la_pendiente_que_empieza_hoy(
    monkeypatch, db_session, cliente, plan, estados_membresia
):
    hoy = _noche_en_bolivia(monkeypatch)
    m = _membresia(cliente, plan, 1, hoy, hoy + timedelta(days=30))

    assert cancel_pending_memberships_with_past_start() == 0
    assert db.session.get(Membresia, m.id).estado_id == 1


def _abonar(membresia, monto):
    from gym_admin.models import HistorialPago, Pago

    pago = Pago(
        cliente_id=membresia.cliente_id,
        membresia_id=membresia.id,
        sucursal_id=membresia.sucursal_id,
        monto_total=100,
    )
    db.session.add(pago)
    db.session.flush()
    db.session.add(HistorialPago(pago_id=pago.id, monto_pagado=monto))
    db.session.commit()


def test_pendiente_con_pago_parcial_no_se_anula(db_session, cliente, plan, estados_membresia):
    hoy = local_today()
    sin_pago = _membresia(cliente, plan, 1, hoy - timedelta(days=3), hoy + timedelta(days=27))
    con_abono = _membresia(cliente, plan, 1, hoy - timedelta(days=3), hoy + timedelta(days=27))
    _abonar(con_abono, 40)

    assert cancel_pending_memberships_with_past_start() == 1
    assert db.session.get(Membresia, sin_pago.id).estado_id == 3
    assert db.session.get(Membresia, con_abono.id).estado_id == 1


def test_crear_membresia_no_anula_pendiente_con_abono(db_session, cliente, plan, estados_membresia):
    from gym_admin.services.membership_service import create_membership

    _activar(plan)
    hoy = local_today()
    con_abono = _membresia(cliente, plan, 1, hoy, hoy + timedelta(days=30))
    _abonar(con_abono, 40)
    sin_pago = _membresia(cliente, plan, 1, hoy, hoy + timedelta(days=30))

    ok, _, err = create_membership(cliente.id, plan.id, hoy + timedelta(days=31), estado_id=1)
    assert ok, err
    assert db.session.get(Membresia, con_abono.id).estado_id == 1
    assert db.session.get(Membresia, sin_pago.id).estado_id == 3
