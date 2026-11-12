"""Tests para la vista interactiva de informe y segmentación de clientes."""

from datetime import date, timedelta

import pytest
from flask import g
from werkzeug.security import generate_password_hash

from gym_admin.extensions import db, limiter
from gym_admin.models import (
    Cliente,
    HistorialPago,
    MarcajeAsistencia,
    Membresia,
    Pago,
    Role,
    SeguimientoCliente,
    Sucursal,
    Usuario,
    Venta,
)
from gym_admin.services.client_report_service import (
    get_client_contact_history,
    get_client_report_data,
    register_client_contact,
)
from gym_admin.services.membership_service import local_today


def _crear_membresia(cliente, plan, estado_id, inicio, fin, monto_total=100, pagado=None):
    m = Membresia(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        plan_id=plan.id,
        fecha_inicio=inicio,
        fecha_fin=fin,
        estado_id=estado_id,
    )
    db.session.add(m)
    db.session.flush()
    if monto_total is not None:
        p = Pago(
            cliente_id=cliente.id,
            membresia_id=m.id,
            sucursal_id=cliente.sucursal_id,
            monto_total=monto_total,
            metodo_pago="Efectivo",
        )
        db.session.add(p)
        db.session.flush()
        if pagado is not None and pagado > 0:
            db.session.add(
                HistorialPago(pago_id=p.id, monto_pagado=pagado, metodo_pago="Efectivo")
            )
    return m


@pytest.fixture
def dataset_segmentos(db_session, sucursal, plan, estados_membresia):
    hoy = local_today()
    s2 = Sucursal(nombre="Sucursal Norte")
    db.session.add(s2)
    db.session.flush()

    c_nunca = Cliente(
        nombre="Ana",
        apellido="Prospecto",
        telefono="70000001",
        fecha_registro=hoy - timedelta(days=15),
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=sucursal.id,
    )
    c_pendiente = Cliente(
        nombre="Luis",
        apellido="Pendiente",
        telefono="70000002",
        fecha_registro=hoy - timedelta(days=5),
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=sucursal.id,
    )
    c_por_vencer = Cliente(
        nombre="Carla",
        apellido="Vencer",
        telefono="70000003",
        tipo_cliente="Individual",
        estado="Activo",
        sucursal_id=sucursal.id,
    )
    c_activo_nuevo = Cliente(
        nombre="Mario",
        apellido="Nuevo",
        telefono="70000004",
        tipo_cliente="Individual",
        estado="Activo",
        sucursal_id=sucursal.id,
    )
    c_activo_frec = Cliente(
        nombre="Elena",
        apellido="Fiel",
        telefono="70000005",
        tipo_cliente="Corporativo",
        estado="Activo",
        sucursal_id=sucursal.id,
    )
    c_unica_vez = Cliente(
        nombre="Pedro",
        apellido="Unico",
        telefono="70000006",
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=sucursal.id,
    )
    c_frec_inactivo = Cliente(
        nombre="Sofia",
        apellido="Exfiel",
        telefono="70000007",
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=sucursal.id,
    )
    c_moroso = Cliente(
        nombre="Raul",
        apellido="Moroso",
        telefono="70000008",
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=sucursal.id,
    )
    c_otra_suc = Cliente(
        nombre="Nora",
        apellido="OtraSede",
        telefono="70000009",
        tipo_cliente="Individual",
        estado="Inactivo",
        sucursal_id=s2.id,
    )

    db.session.add_all(
        [
            c_nunca,
            c_pendiente,
            c_por_vencer,
            c_activo_nuevo,
            c_activo_frec,
            c_unica_vez,
            c_frec_inactivo,
            c_moroso,
            c_otra_suc,
        ]
    )
    db.session.flush()

    # Pendiente (estado=1) no cuenta como adquirida
    _crear_membresia(c_pendiente, plan, 1, hoy, hoy + timedelta(days=30), monto_total=100, pagado=0)

    # Por vencer en 3 días
    _crear_membresia(
        c_por_vencer, plan, 2, hoy - timedelta(days=27), hoy + timedelta(days=3), monto_total=120, pagado=120
    )

    # Activo nuevo (1ra membresía, >7 días)
    _crear_membresia(
        c_activo_nuevo, plan, 2, hoy - timedelta(days=5), hoy + timedelta(days=25), monto_total=150, pagado=150
    )

    # Activo frecuente (2 membresías) + compra POS + asistencia
    _crear_membresia(
        c_activo_frec, plan, 4, hoy - timedelta(days=60), hoy - timedelta(days=31), monto_total=200, pagado=200
    )
    m_fiel = _crear_membresia(
        c_activo_frec, plan, 2, hoy - timedelta(days=30), hoy + timedelta(days=20), monto_total=200, pagado=200
    )
    db.session.add(Venta(cliente_id=c_activo_frec.id, sucursal_id=sucursal.id, monto_total=80))
    db.session.add(
        MarcajeAsistencia(membresia_id=m_fiel.id, cliente_id=c_activo_frec.id, sucursal_id=sucursal.id)
    )

    # Única vez vencido hace 5 días
    _crear_membresia(
        c_unica_vez, plan, 6, hoy - timedelta(days=35), hoy - timedelta(days=5), monto_total=100, pagado=100
    )

    # Frecuente inactivo (3 membresías, última vencida hace 45 días, con saldo pendiente 50)
    _crear_membresia(
        c_frec_inactivo, plan, 4, hoy - timedelta(days=140), hoy - timedelta(days=110), monto_total=100, pagado=100
    )
    _crear_membresia(
        c_frec_inactivo, plan, 4, hoy - timedelta(days=109), hoy - timedelta(days=79), monto_total=100, pagado=100
    )
    _crear_membresia(
        c_frec_inactivo, plan, 6, hoy - timedelta(days=75), hoy - timedelta(days=45), monto_total=150, pagado=100
    )

    # Moroso > 90 días (venció hace 120 días)
    _crear_membresia(
        c_moroso, plan, 6, hoy - timedelta(days=150), hoy - timedelta(days=120), monto_total=90, pagado=90
    )

    # Otra sucursal
    _crear_membresia(
        c_otra_suc, plan, 6, hoy - timedelta(days=40), hoy - timedelta(days=10), monto_total=100, pagado=100
    )

    db.session.commit()
    return {
        "hoy": hoy,
        "sucursal": sucursal,
        "otra_sucursal": s2,
        "c_nunca": c_nunca,
        "c_pendiente": c_pendiente,
        "c_por_vencer": c_por_vencer,
        "c_activo_nuevo": c_activo_nuevo,
        "c_activo_frec": c_activo_frec,
        "c_unica_vez": c_unica_vez,
        "c_frec_inactivo": c_frec_inactivo,
        "c_moroso": c_moroso,
        "c_otra_suc": c_otra_suc,
    }


def test_segmentacion_y_contadores_exactos(db_session, dataset_segmentos):
    sucursal = dataset_segmentos["sucursal"]
    res = get_client_report_data(filters={}, sucursal_id=sucursal.id, page=1, per_page=25)

    assert res["pagination"].total == 8  # excluye c_otra_suc
    by_id = {r["cliente"].id: r for r in res["rows"]}

    assert by_id[dataset_segmentos["c_nunca"].id]["segmento_key"] == "nunca"
    assert by_id[dataset_segmentos["c_nunca"].id]["valid_count"] == 0

    assert by_id[dataset_segmentos["c_pendiente"].id]["segmento_key"] == "nunca"
    assert by_id[dataset_segmentos["c_pendiente"].id]["pendientes_extra"] == 1

    assert by_id[dataset_segmentos["c_por_vencer"].id]["segmento_key"] == "por_vencer"
    assert by_id[dataset_segmentos["c_por_vencer"].id]["counter"]["dias_restantes"] == 3

    assert by_id[dataset_segmentos["c_activo_nuevo"].id]["segmento_key"] == "activo_nuevo"
    assert by_id[dataset_segmentos["c_activo_frec"].id]["segmento_key"] == "activo_frecuente"
    assert by_id[dataset_segmentos["c_activo_frec"].id]["ltv"] == 480.0
    assert by_id[dataset_segmentos["c_activo_frec"].id]["total_asistencias"] == 1

    unica = by_id[dataset_segmentos["c_unica_vez"].id]
    assert unica["segmento_key"] == "unica_vez"
    assert unica["valid_count"] == 1
    assert unica["counter"]["dias_vencido"] == 5

    frec_inac = by_id[dataset_segmentos["c_frec_inactivo"].id]
    assert frec_inac["segmento_key"] == "frecuente_inactivo"
    assert frec_inac["valid_count"] == 3
    assert frec_inac["counter"]["dias_vencido"] == 45
    assert "saldo_pendiente" not in frec_inac
    assert frec_inac["contacto"]["key"] == "sin_contacto"
    assert frec_inac["wa_url"].startswith("https://wa.me/59170000007?text=")

    moroso = by_id[dataset_segmentos["c_moroso"].id]
    assert moroso["counter"]["dias_vencido"] == 120


def test_filtros_dinamicos_y_rango_personalizado(db_session, dataset_segmentos):
    suc_id = dataset_segmentos["sucursal"].id

    # Ventana semana (1-7d): Pedro Unico (5d)
    r_sem = get_client_report_data({"ventana": "semana"}, sucursal_id=suc_id)
    assert [r["cliente"].nombre for r in r_sem["rows"]] == ["Pedro"]

    # Ventana trimestre (31-90d): Sofia Exfiel (45d)
    r_tri = get_client_report_data({"ventana": "trimestre"}, sucursal_id=suc_id)
    assert [r["cliente"].nombre for r in r_tri["rows"]] == ["Sofia"]

    # Ventana >90d: Raul Moroso (120d)
    r_mor = get_client_report_data({"ventana": "mas_90d"}, sucursal_id=suc_id)
    assert [r["cliente"].nombre for r in r_mor["rows"]] == ["Raul"]

    # Rango personalizado 40 a 130 días: Sofia (45d) y Raul (120d)
    r_pers = get_client_report_data(
        {"ventana": "personalizado", "dias_min": 40, "dias_max": 130, "sort": "nombre", "dir": "asc"},
        sucursal_id=suc_id,
    )
    assert [r["cliente"].nombre for r in r_pers["rows"]] == ["Raul", "Sofia"]

    # Tipo Corporativo: Elena Fiel
    r_corp = get_client_report_data({"tipo": "Corporativo"}, sucursal_id=suc_id)
    assert [r["cliente"].nombre for r in r_corp["rows"]] == ["Elena"]

    # Historial 2_3: Elena (2) y Sofia (3)
    r_hist = get_client_report_data(
        {"historial": "2_3", "sort": "membresias", "dir": "desc"}, sucursal_id=suc_id
    )
    assert [r["cliente"].nombre for r in r_hist["rows"]] == ["Sofia", "Elena"]


def test_paginacion_y_agrupamiento(db_session, sucursal, plan, estados_membresia):
    hoy = local_today()
    for i in range(18):
        c = Cliente(
            nombre=f"Cliente{i:02d}",
            apellido="Prueba",
            telefono=f"710000{i:02d}",
            sucursal_id=sucursal.id,
        )
        db.session.add(c)
        db.session.flush()
        if i % 2 == 0:
            _crear_membresia(
                c, plan, 6, hoy - timedelta(days=40 + i), hoy - timedelta(days=10 + i), monto_total=100, pagado=100
            )
    db.session.commit()

    p1 = get_client_report_data(
        {"agrupar": "segmento", "sort": "nombre", "dir": "asc"},
        sucursal_id=sucursal.id,
        page=1,
        per_page=15,
    )
    p2 = get_client_report_data(
        {"agrupar": "segmento", "sort": "nombre", "dir": "asc"},
        sucursal_id=sucursal.id,
        page=2,
        per_page=15,
    )
    assert p1["pagination"].total == 18
    assert p1["pagination"].pages == 2
    assert len(p1["rows"]) == 15
    assert len(p2["rows"]) == 3
    ids_p1 = {r["cliente"].id for r in p1["rows"]}
    ids_p2 = {r["cliente"].id for r in p2["rows"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_recepcion_no_ve_exportar_y_accede_informe(app, db_session, sucursal, dataset_segmentos):
    db.session.add_all([Role(id=1, nombre="admin"), Role(id=2, nombre="recepcion")])
    db.session.add(
        Usuario(
            id=11,
            nombre="Recepcion",
            correo="recep@test.com",
            contrasena=generate_password_hash("pw"),
            rol_id=2,
            sucursal_id=sucursal.id,
            estado=True,
        )
    )
    db.session.commit()

    limiter.reset()
    client_recep = app.test_client()
    try:
        resp_login = client_recep.post(
            "/auth/login", data={"correo": "recep@test.com", "contrasena": "pw"}
        )
        assert resp_login.status_code == 302

        list_html = client_recep.get("/clientes/").get_data(as_text=True)
        assert "Informe / Segmentación" in list_html
        assert "export-super-excel" not in list_html
        assert "export-clients-csv" not in list_html

        # Bloqueo directo a rutas de exportación para recepción
        resp_csv = client_recep.get("/clientes/export.csv")
        assert resp_csv.status_code == 302
        resp_bi = client_recep.get("/clientes/exportar-consolidado?formato=xlsx")
        assert resp_bi.status_code == 403

        # Acceso completo al nuevo informe interactivo y su parcial AJAX
        resp_inf = client_recep.get("/clientes/informe")
        assert resp_inf.status_code == 200
        inf_html = resp_inf.get_data(as_text=True)
        assert "Informe Interactivo de Clientes" in inf_html
        assert "Guía de Segmentos" in inf_html
        assert "Últ. Contacto" in inf_html
        assert "Checklist de contacto" in inf_html
        assert "Sofia Exfiel" in inf_html
        assert "Nora OtraSede" not in inf_html
        # Opciones innecesarias y botones redundantes eliminados
        assert "Saldo Bs." not in inf_html
        assert 'id="rep-deuda-btn"' not in inf_html
        assert "+ Memb." not in inf_html
        assert "Ver perfil" not in inf_html

        resp_partial = client_recep.get("/clientes/informe/table?segmento=frecuente_inactivo&agrupar=segmento")
        assert resp_partial.status_code == 200
        partial_html = resp_partial.get_data(as_text=True)
        assert "Sofia Exfiel" in partial_html
        assert "Pedro Unico" not in partial_html
    finally:
        g.pop("_login_user", None)


def test_admin_si_ve_exportar(logged_client):
    admin_list_html = logged_client.get("/clientes/").get_data(as_text=True)
    assert "Informe / Segmentación" in admin_list_html
    assert "export-super-excel" in admin_list_html
    assert "export-clients-csv" in admin_list_html


def test_seguimiento_contacto_filtros_orden_y_kpis(db_session, dataset_segmentos):
    suc_id = dataset_segmentos["sucursal"].id
    hoy = local_today()

    c_sofia = dataset_segmentos["c_frec_inactivo"]
    c_pedro = dataset_segmentos["c_unica_vez"]
    c_raul = dataset_segmentos["c_moroso"]

    # Validación de resultado inválido
    ok_bad, _, err_bad = register_client_contact(c_sofia.id, "invalido")
    assert not ok_bad
    assert err_bad

    # Sofia: llamada -> comprometido con fecha de recontacto vencida (ayer)
    ok1, s1, err1 = register_client_contact(
        c_sofia.id,
        "comprometido",
        canal="Llamada",
        nota="Prometio pasar a renovar",
        fecha_recontacto=hoy - timedelta(days=1),
    )
    assert ok1 and err1 is None and s1 is not None

    # Pedro: presencial -> no_contesto, recontacto pasado mañana
    ok2, _, _ = register_client_contact(
        c_pedro.id,
        "no_contesto",
        canal="Presencial",
        nota="Telefono apagado",
        fecha_recontacto=hoy + timedelta(days=2),
    )
    assert ok2

    # Raul: llamada antiguo (hace 10 días) -> contesto
    ok3, s3, _ = register_client_contact(c_raul.id, "contesto", canal="Llamada", nota="Pide promo")
    assert ok3 and s3 is not None
    s3.fecha_contacto = s3.fecha_contacto - timedelta(days=10)
    db.session.commit()

    # Verificar historial por cliente
    hist_sofia = get_client_contact_history(c_sofia.id)
    assert len(hist_sofia) == 1
    assert hist_sofia[0]["resultado"] == "comprometido"
    assert hist_sofia[0]["canal"] == "Llamada"

    # Reporte completo y KPIs de contacto
    rep = get_client_report_data({}, sucursal_id=suc_id)
    kpis = rep["kpis"]
    assert kpis["sin_contacto"] == 5
    assert kpis["comprometido"] == 1
    assert kpis["no_contesto"] == 1
    assert kpis["contactados_7d"] == 2
    assert kpis["requiere_recontacto"] == 4
    # Respuesta efectiva: comprometido (1) + contesto (1) sobre 3 con historial = 67%
    assert kpis["tasa_respuesta"] == 67

    by_id = {r["cliente"].id: r for r in rep["rows"]}
    assert by_id[c_sofia.id]["contacto"]["key"] == "comprometido"
    assert by_id[c_sofia.id]["contacto"]["recontacto_vencido"] is True
    assert by_id[c_sofia.id]["contacto"]["total_contactos"] == 1
    assert by_id[c_pedro.id]["contacto"]["canal"] == "Presencial"

    # Filtros de contacto
    r_sin = get_client_report_data({"contacto": "sin_contacto"}, sucursal_id=suc_id)
    assert r_sin["pagination"].total == 5

    r_comp = get_client_report_data({"contacto": "comprometido"}, sucursal_id=suc_id)
    assert [r["cliente"].nombre for r in r_comp["rows"]] == ["Sofia"]

    # Requiere recontacto: Sofia (fecha vencida) + sin contacto accionables (c_nunca, c_pendiente, c_por_vencer)
    r_rec = get_client_report_data({"contacto": "requiere_recontacto"}, sucursal_id=suc_id)
    rec_ids = {r["cliente"].id for r in r_rec["rows"]}
    assert rec_ids == {
        c_sofia.id,
        dataset_segmentos["c_nunca"].id,
        dataset_segmentos["c_pendiente"].id,
        dataset_segmentos["c_por_vencer"].id,
    }

    r_7d = get_client_report_data({"contacto": "contactado_reciente"}, sucursal_id=suc_id)
    assert {r["cliente"].nombre for r in r_7d["rows"]} == {"Sofia", "Pedro"}

    # Ordenamiento por fecha de recontacto (NULLS LAST)
    r_sort = get_client_report_data(
        {"sort": "fecha_recontacto", "dir": "asc"},
        sucursal_id=suc_id,
    )
    assert [r["cliente"].nombre for r in r_sort["rows"][:2]] == ["Sofia", "Pedro"]

    # Agrupamiento por estado de contacto mantiene bloques contiguos (sin_contacto primero)
    r_grp = get_client_report_data(
        {"agrupar": "contacto", "sort": "nombre", "dir": "asc"},
        sucursal_id=suc_id,
    )
    grp_keys = [r["contacto"]["key"] for r in r_grp["rows"]]
    assert grp_keys[:5] == ["sin_contacto"] * 5
    # Último contacto descendente coloca primero al más reciente (Pedro/Sofia antes que Raul)
    r_ult = get_client_report_data(
        {"sort": "ultimo_contacto", "dir": "asc"},
        sucursal_id=suc_id,
    )
    assert r_ult["rows"][0]["cliente"].id == c_raul.id


def test_endpoints_checklist_contacto_y_sucursal(logged_client, db_session, dataset_segmentos):
    c_sofia = dataset_segmentos["c_frec_inactivo"]
    c_otra = dataset_segmentos["c_otra_suc"]
    hoy = local_today()

    # Registrar contacto vía llamada sin usar WhatsApp
    resp_post = logged_client.post(
        "/clientes/informe/contacto",
        json={
            "cliente_id": c_sofia.id,
            "resultado": "contactado",
            "canal": "Llamada",
            "nota": "Se llamo al celular personal",
            "fecha_recontacto": (hoy + timedelta(days=3)).isoformat(),
        },
    )
    assert resp_post.status_code == 200
    payload = resp_post.get_json()
    assert payload["success"] is True
    assert payload["seguimiento"]["resultado"] == "contactado"
    assert payload["seguimiento"]["canal"] == "Llamada"

    # Consultar historial desde endpoint JSON
    resp_hist = logged_client.get(f"/clientes/informe/{c_sofia.id}/seguimientos")
    assert resp_hist.status_code == 200
    hist_data = resp_hist.get_json()
    assert hist_data["success"] is True
    assert len(hist_data["items"]) == 1
    assert hist_data["items"][0]["nota"] == "Se llamo al celular personal"

    # El parcial actualizado refleja el último contacto
    resp_table = logged_client.get("/clientes/informe/table?contacto=contactado")
    assert resp_table.status_code == 200
    html = resp_table.get_data(as_text=True)
    assert "Sofia Exfiel" in html
    assert "Llamada" in html

    # Aislamiento multi-sucursal: no permite registrar ni ver historial de cliente de otra sede
    resp_other_post = logged_client.post(
        "/clientes/informe/contacto",
        json={"cliente_id": c_otra.id, "resultado": "contesto", "canal": "Llamada"},
    )
    assert resp_other_post.status_code == 403

    resp_other_hist = logged_client.get(f"/clientes/informe/{c_otra.id}/seguimientos")
    assert resp_other_hist.status_code == 403
