import os
import threading
import smtplib
from email.message import EmailMessage
from flask import current_app


def send_email(to_email: str, subject: str, body: str) -> bool:
    smtp_server = os.getenv("SMTP_SERVER", "hipertrofiafuncional.online")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM", smtp_user)

    if not smtp_user or not smtp_password:
        try:
            current_app.logger.warning("send_email: SMTP credentials not configured")
        except Exception:
            pass
        return False

    try:
        msg = EmailMessage()
        msg["From"] = email_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body, subtype="plain", charset="utf-8")

        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return True
    except Exception as e:
        try:
            current_app.logger.exception("Error sending email: %s", str(e))
        except Exception:
            pass
        return False


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
