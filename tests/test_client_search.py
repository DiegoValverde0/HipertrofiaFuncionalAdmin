"""Búsqueda de clientes al crear membresías."""

import pytest

from gym_admin.extensions import db
from gym_admin.models import Cliente
from gym_admin.services.client_service import clean_client_query


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Diego Valverde - diego@gmail.comTiene", "Diego Valverde"),
        ("Cliente de prueba prueba - prueba@gmail.comSin", "Cliente de prueba prueba"),
        ("  ana   paz ", "ana paz"),
        ("70012345", "70012345"),
        ("", ""),
    ],
)
def test_clean_client_query(raw, expected):
    assert clean_client_query(raw) == expected


@pytest.fixture
def clientes(db_session, sucursal):
    rows = [
        Cliente(nombre="Diego Alexander", apellido="Valverde Ribera",
                correo="diego@gmail.com", telefono="70011111", sucursal_id=sucursal.id),
        Cliente(nombre="Ana", apellido="Paz", correo="ana_paz@gmail.com",
                telefono="70022222", sucursal_id=sucursal.id),
        Cliente(nombre="Diego", apellido="Mendoza", telefono="70033333",
                sucursal_id=sucursal.id),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def _nombres(resp):
    assert resp.status_code == 200
    return sorted(item["nombre"] for item in resp.get_json())


@pytest.mark.parametrize(
    "q, expected",
    [
        ("diego", ["Diego Alexander Valverde Ribera", "Diego Mendoza"]),
        ("diego valverde", ["Diego Alexander Valverde Ribera"]),
        ("valverde diego", ["Diego Alexander Valverde Ribera"]),
        ("70022222", ["Ana Paz"]),
        ("ANA PAZ", ["Ana Paz"]),
        # texto que el navegador autocompletaba con el formato viejo
        ("Diego Alexander Valverde Ribera - diego@gmail.comTiene",
         ["Diego Alexander Valverde Ribera"]),
        ("%", []),
        ("a_a", []),  # "_" se busca literal, no como comodín
    ],
)
def test_busqueda_por_palabras(logged_client, clientes, q, expected):
    resp = logged_client.get("/membresias/search_clientes", query_string={"q": q})
    assert _nombres(resp) == expected


def test_resultado_trae_nombre_limpio(logged_client, clientes):
    (item,) = logged_client.get(
        "/membresias/search_clientes", query_string={"q": "ana paz"}
    ).get_json()
    assert item["nombre"] == "Ana Paz"
    assert item["detalle"] == "70022222"
    assert "Sin" not in item["nombre"] and " - " not in item["nombre"]


def test_listado_de_clientes_busca_nombre_completo(logged_client, clientes):
    resp = logged_client.get("/clientes/", query_string={"q": "diego valverde"})
    html = resp.get_data(as_text=True)
    assert "Valverde Ribera" in html
    assert "Mendoza" not in html
