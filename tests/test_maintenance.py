import pytest

URL = "/membresias/admin/run_maintenance"


@pytest.fixture
def client(app, db_session, estados_membresia):
    app.config["ADMIN_TOKEN"] = "token-de-prueba"
    yield app.test_client()
    app.config["ADMIN_TOKEN"] = None


def test_maintenance_with_valid_token(client):
    resp = client.get(URL, headers={"Authorization": "Bearer token-de-prueba"})
    assert resp.status_code == 200
    assert resp.get_json()["method"] == "CRON"


def test_maintenance_rejects_wrong_token(client):
    resp = client.get(URL, headers={"Authorization": "Bearer otro"})
    assert resp.status_code == 403


def test_maintenance_rejects_missing_token(client):
    resp = client.get(URL)
    assert resp.status_code == 403


def test_maintenance_ignores_token_in_query_string(client):
    resp = client.get(URL + "?token=token-de-prueba")
    assert resp.status_code == 403


def test_maintenance_disabled_without_configured_token(app, client):
    app.config["ADMIN_TOKEN"] = None
    resp = client.get(URL, headers={"Authorization": "Bearer "})
    assert resp.status_code == 403
