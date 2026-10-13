from gym_admin.extensions import limiter


def test_login_rate_limit(app, db_session):
    client = app.test_client()
    limiter.reset()
    try:
        codes = [
            client.post(
                "/auth/login", data={"correo": "nadie@test.com", "contrasena": "x"}
            ).status_code
            for _ in range(11)
        ]
    finally:
        limiter.reset()
    assert 429 not in codes[:10]
    assert codes[10] == 429
