from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    from backports.zoneinfo import ZoneInfo

BOLIVIA = ZoneInfo("America/La_Paz")


def utcnow():
    """Hora actual en UTC como datetime naive (sin tzinfo).

    Reemplaza a ``datetime.utcnow()`` (obsoleto desde Python 3.12) y conserva
    el formato con el que se guardan las columnas DATETIME de la base.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today():
    """Fecha de hoy en Bolivia, sin depender de la zona horaria del servidor."""
    return to_bolivia(utcnow()).date()


def now_utc():
    """Return current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_bolivia(dt):
    """Convert a datetime to America/La_Paz tz-aware datetime.

    If dt is naive it's assumed to be UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BOLIVIA)


def to_utc(dt):
    """Convert a datetime to UTC tz-aware datetime.

    If dt is naive it's interpreted as America/La_Paz local time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # interpret naive inputs as Bolivia local time
        dt = dt.replace(tzinfo=BOLIVIA)
    return dt.astimezone(timezone.utc)


def to_utc_naive(dt):
    """Convert dt to UTC and return a naive datetime (tzinfo removed).

    Useful when DB columns are DATETIME without timezone and we want to store
    UTC-consistent values.
    """
    u = to_utc(dt)
    # remove tzinfo to store as naive UTC
    return u.replace(tzinfo=None)


def format_dt_local(dt, fmt="%Y-%m-%d %H:%M:%S"):
    b = to_bolivia(dt)
    return b.strftime(fmt) if b else ""
