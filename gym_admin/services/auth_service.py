import os
import ssl
import threading
import smtplib
from email.message import EmailMessage
from flask import current_app


def send_email(to_email: str, subject: str, body: str) -> bool:
    smtp_server = (os.getenv("SMTP_SERVER") or "mail.hipertrofiafuncional.online").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    email_from = (os.getenv("EMAIL_FROM") or smtp_user or "").strip()
    use_ssl = str(os.getenv("SMTP_USE_SSL", "0")).strip().lower() in {"1", "true", "yes", "on"}
    use_tls = str(os.getenv("SMTP_USE_TLS", "1")).strip().lower() in {"1", "true", "yes", "on"}
    skip_tls_verify = str(os.getenv("SMTP_TLS_SKIP_VERIFY", "1")).strip().lower() in {"1", "true", "yes", "on"}
    timeout = int(os.getenv("SMTP_TIMEOUT", "10"))

    if not smtp_user or not smtp_password:
        try:
            current_app.logger.warning("send_email: SMTP credentials not configured")
        except Exception:
            pass
        return False

    msg = EmailMessage()
    msg["From"] = email_from or smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body, subtype="plain", charset="utf-8")

    server = None
    try:
        tls_context = ssl.create_default_context()
        if skip_tls_verify:
            tls_context.check_hostname = False
            tls_context.verify_mode = ssl.CERT_NONE

        if smtp_port == 465 or use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=timeout, context=tls_context)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=timeout)

        if hasattr(server, "ehlo"):
            server.ehlo()

        if use_tls and not isinstance(server, smtplib.SMTP_SSL) and hasattr(server, "has_extn") and server.has_extn("STARTTLS"):
            server.starttls(context=tls_context)
            if hasattr(server, "ehlo"):
                server.ehlo()

        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        return True
    except Exception as e:
        try:
            current_app.logger.exception("Error sending email to %s: %s", to_email, str(e))
        except Exception:
            pass
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


def _post_login_worker(user_id, sucursal_id=None):
    try:
        # Import inside worker to avoid circular imports at module import time
        from ..utils import (
            process_membership_states,
            sync_promociones_by_date,
            cancel_pending_memberships_with_past_start,
        )
    except Exception:
        process_membership_states = None
        sync_promociones_by_date = None
        cancel_pending_memberships_with_past_start = None

    try:
        # notificaciones may be in blueprints
        try:
            from ..blueprints.notificaciones import (
                create_birthday_notifications_for_week,
            )
        except Exception:
            create_birthday_notifications_for_week = None
    except Exception:
        create_birthday_notifications_for_week = None

    # Run each task with its own error handling to avoid stopping others
    try:
        if process_membership_states:
            process_membership_states()
    except Exception:
        try:
            current_app.logger.exception(
                "Error processing membership states in background"
            )
        except Exception:
            pass

    try:
        if sync_promociones_by_date:
            sync_promociones_by_date()
    except Exception:
        try:
            current_app.logger.exception("Error syncing promociones in background")
        except Exception:
            pass

    try:
        if cancel_pending_memberships_with_past_start:
            cancelled = cancel_pending_memberships_with_past_start()
            try:
                current_app.logger.debug(
                    "cancel_pending_memberships_with_past_start background: %s",
                    cancelled,
                )
            except Exception:
                pass
    except Exception:
        try:
            current_app.logger.exception(
                "Error cancelling pending memberships in background"
            )
        except Exception:
            pass

    try:
        if create_birthday_notifications_for_week:
            created = create_birthday_notifications_for_week(
                force=True, sucursal_id=sucursal_id
            )
            try:
                current_app.logger.debug(
                    "create_birthday_notifications_for_week background; created=%s",
                    created,
                )
            except Exception:
                pass
    except Exception:
        try:
            current_app.logger.exception(
                "Error creating birthday notifications in background"
            )
        except Exception:
            pass


def trigger_post_login_tasks(user, background=True):
    """Trigger post-login tasks for `user`.

    If `background` is True, tasks run in a daemon thread with app context.
    Otherwise they run synchronously in the current context.
    """
    sucursal = None
    try:
        sucursal = getattr(user, "sucursal_id", None)
    except Exception:
        sucursal = None

    if not background:
        _post_login_worker(getattr(user, "id", None), sucursal_id=sucursal)
        return

    # run in background with app context
    try:
        app = current_app._get_current_object()
    except Exception:
        app = None

    if app is None:
        # fallback to sync
        _post_login_worker(getattr(user, "id", None), sucursal_id=sucursal)
        return

    def _runner(a, uid, suc):
        with a.app_context():
            _post_login_worker(uid, sucursal_id=suc)

    t = threading.Thread(
        target=_runner, args=(app, getattr(user, "id", None), sucursal), daemon=True
    )
    t.start()
