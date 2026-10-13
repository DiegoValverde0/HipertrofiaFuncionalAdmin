import smtplib

from gym_admin.services import auth_service


def test_send_email_falls_back_to_starttls_when_ssl_is_not_supported(monkeypatch):
    monkeypatch.setenv("SMTP_SERVER", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user@test.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    class FakeSMTPSSL:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPNotSupportedError("SSL not supported")

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            self.started_tls = False

        def starttls(self):
            self.started_tls = True

        def login(self, *args, **kwargs):
            return None

        def send_message(self, msg):
            return None

        def quit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(auth_service.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(auth_service.smtplib, "SMTP", FakeSMTP)

    assert auth_service.send_email("user@test.com", "subject", "body") is True
