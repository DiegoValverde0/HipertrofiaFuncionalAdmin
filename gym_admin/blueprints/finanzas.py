from flask import Blueprint, render_template, request
from ..utils import admin_required
from ..models import (
    Pago,
    Venta,
    Gasto,
    Membresia,
    Plan,
    Sucursal,
    CategoriaGasto,
    Cuenta,
    HistorialPago,
)
from ..extensions import db
from sqlalchemy import func
from datetime import datetime, timedelta
from ..utils_timezone import local_today, now_utc, to_bolivia, to_utc_naive

finanzas_bp = Blueprint("finanzas", __name__)


def _parse_period(period, fecha_desde, fecha_hasta):
    # Interpret period/fecha inputs in Bolivia local time and return UTC-naive start/end datetimes
    try:
        now_b = to_bolivia(now_utc())
        if period == "today":
            start_b = datetime(now_b.year, now_b.month, now_b.day)
            end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            return to_utc_naive(start_b), to_utc_naive(end_b)
        if period == "week":
            start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                days=now_b.weekday()
            )
            start_b = start_day
            end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            return to_utc_naive(start_b), to_utc_naive(end_b)
        if period == "month":
            start_b = datetime(now_b.year, now_b.month, 1)
            if now_b.month == 12:
                nm = datetime(now_b.year + 1, 1, 1)
            else:
                nm = datetime(now_b.year, now_b.month + 1, 1)
            end_b = nm - timedelta(seconds=1)
            return to_utc_naive(start_b), to_utc_naive(end_b)
        if period == "year":
            start_b = datetime(now_b.year, 1, 1)
            end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            return to_utc_naive(start_b), to_utc_naive(end_b)
        # custom
        try:
            sd = datetime.strptime(fecha_desde, "%Y-%m-%d") if fecha_desde else None
            hd = datetime.strptime(fecha_hasta, "%Y-%m-%d") if fecha_hasta else None
            if sd and hd:
                start_b = datetime(sd.year, sd.month, sd.day)
                end_b = datetime(hd.year, hd.month, hd.day, 23, 59, 59)
                return to_utc_naive(start_b), to_utc_naive(end_b)
        except Exception:
            pass
    except Exception:
        pass
    # fallback last 30 days in Bolivia
    try:
        now_b = to_bolivia(now_utc())
        s_b = datetime(now_b.year, now_b.month, now_b.day) - timedelta(days=30)
        e_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
        return to_utc_naive(s_b), to_utc_naive(e_b)
    except Exception:
        # final fallback to naive UTC now last 30 days
        today = local_today()
        s = datetime.combine(today - timedelta(days=30), datetime.min.time())
        e = datetime.combine(today, datetime.max.time())
        return s, e


@finanzas_bp.route("/")
@admin_required
def index():
    # filters
    sucursal_id = request.args.get("sucursal_id", type=int)
    period = request.args.get("period", "month")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")

    start_dt, end_dt = _parse_period(period, fecha_desde, fecha_hasta)

    # base filters
    suc_filter = []
    if sucursal_id and sucursal_id != 0:
        suc_filter.append(Membresia.sucursal_id == sucursal_id)

    # Ingresos: sumar montos de `HistorialPago` (detalle de pagos) y contar membresías con pagos
    pagos_filters = [
        HistorialPago.fecha_pago >= start_dt,
        HistorialPago.fecha_pago <= end_dt,
    ]
    ingresos_query = db.session.query(
        func.coalesce(func.sum(HistorialPago.monto_pagado), 0).label("total_pagos")
    )
    ingresos_query = ingresos_query.join(Pago, HistorialPago.pago_id == Pago.id)
    if sucursal_id and sucursal_id != 0:
        ingresos_query = ingresos_query.join(
            Membresia, Pago.membresia_id == Membresia.id
        ).filter(Membresia.sucursal_id == sucursal_id)
    ingresos_query = ingresos_query.filter(*pagos_filters)
    ingresos_summary = ingresos_query.one()

    # contar membresías distintas que recibieron algún pago en el periodo
    memb_count_q = (
        db.session.query(func.count(func.distinct(Pago.membresia_id)))
        .join(HistorialPago, HistorialPago.pago_id == Pago.id)
        .filter(*pagos_filters)
    )
    if sucursal_id and sucursal_id != 0:
        memb_count_q = memb_count_q.join(
            Membresia, Pago.membresia_id == Membresia.id
        ).filter(Membresia.sucursal_id == sucursal_id)
    total_membresias_pagadas = int(memb_count_q.scalar() or 0)

    include_ventas = request.args.get("include_ventas") in ("1", "true", "True", "on")

    ventas_summary = type("S", (), {"total_ventas": 0, "count_ventas": 0})()
    if include_ventas:
        ventas_query = db.session.query(
            func.coalesce(func.sum(Venta.monto_total), 0).label("total_ventas"),
            func.count(Venta.id).label("count_ventas"),
        )
        ventas_filters = [Venta.fecha_venta >= start_dt, Venta.fecha_venta <= end_dt]
        if sucursal_id and sucursal_id != 0:
            ventas_filters.append(Venta.sucursal_id == sucursal_id)
        ventas_query = ventas_query.filter(*ventas_filters)
        ventas_summary = ventas_query.one()

    total_ingresos = float(ingresos_summary.total_pagos or 0) + float(
        getattr(ventas_summary, "total_ventas", 0) or 0
    )
    total_ingresos_count = int(
        total_membresias_pagadas + (getattr(ventas_summary, "count_ventas", 0) or 0)
    )

    # Egresos: gastos
    gastos_query = db.session.query(
        func.coalesce(func.sum(Gasto.monto), 0).label("total_gastos"),
        func.count(Gasto.id).label("count_gastos"),
    )
    gastos_filters = [Gasto.fecha_gasto >= start_dt, Gasto.fecha_gasto <= end_dt]
    if sucursal_id and sucursal_id != 0:
        gastos_filters.append(Gasto.sucursal_id == sucursal_id)
    gastos_summary = gastos_query.filter(*gastos_filters).one()

    total_egresos = float(gastos_summary.total_gastos or 0)
    total_egresos_count = int(gastos_summary.count_gastos or 0)

    # Analytics: membresias pagadas por plan
    plan_stats = []
    try:
        sub = (
            db.session.query(
                Pago.membresia_id,
                func.sum(HistorialPago.monto_pagado).label("sum_pago"),
            )
            .join(HistorialPago, HistorialPago.pago_id == Pago.id)
            .filter(
                HistorialPago.fecha_pago >= start_dt, HistorialPago.fecha_pago <= end_dt
            )
            .group_by(Pago.membresia_id)
            .subquery()
        )
        q = db.session.query(
            Plan.nombre, func.count(func.distinct(Membresia.id)).label("memb_count")
        )
        q = q.join(Membresia, Membresia.plan_id == Plan.id).join(
            sub, sub.c.membresia_id == Membresia.id
        )
        if sucursal_id and sucursal_id != 0:
            q = q.filter(Membresia.sucursal_id == sucursal_id)
        q = q.group_by(Plan.nombre).order_by(
            func.count(func.distinct(Membresia.id)).desc()
        )
        plan_stats = [{"plan": r[0], "count": int(r[1])} for r in q.all()]
    except Exception:
        plan_stats = []

    # gastos por categoría
    gastos_by_cat = []
    try:
        gc = db.session.query(
            CategoriaGasto.nombre,
            func.coalesce(func.sum(Gasto.monto), 0).label("total"),
        )
        gc = gc.join(Gasto, Gasto.categoria_id == CategoriaGasto.id).filter(
            Gasto.fecha_gasto >= start_dt, Gasto.fecha_gasto <= end_dt
        )
        if sucursal_id and sucursal_id != 0:
            gc = gc.filter(Gasto.sucursal_id == sucursal_id)
        gc = gc.group_by(CategoriaGasto.nombre).order_by(func.sum(Gasto.monto).desc())
        gastos_by_cat = [{"categoria": r[0], "total": float(r[1])} for r in gc.all()]
    except Exception:
        gastos_by_cat = []

    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    cuentas = Cuenta.query.order_by(Cuenta.nombre).all()

    context = dict(
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        total_ingresos_count=total_ingresos_count,
        total_egresos_count=total_egresos_count,
        plan_stats=plan_stats,
        gastos_by_cat=gastos_by_cat,
        sucursales=sucursales,
        cuentas=cuentas,
        start_dt=start_dt,
        end_dt=end_dt,
        selected_sucursal=sucursal_id,
        period=period,
        include_ventas=include_ventas,
    )

    return render_template("finanzas/index.html", **context)


def _compute_finanzas(
    sucursal_id, start_dt, end_dt, include_ventas=False, cuenta_id=None
):
    """Compute summary dictionaries used by UI. Returns dict with keys matching template context."""
    # ingresos (pagos) — usar HistorialPago para sumar montos reales
    pagos_filters = [
        HistorialPago.fecha_pago >= start_dt,
        HistorialPago.fecha_pago <= end_dt,
    ]
    ingresos_query = db.session.query(
        func.coalesce(func.sum(HistorialPago.monto_pagado), 0).label("total_pagos")
    )
    ingresos_query = ingresos_query.join(Pago, HistorialPago.pago_id == Pago.id)
    if sucursal_id and sucursal_id != 0:
        ingresos_query = ingresos_query.join(
            Membresia, Pago.membresia_id == Membresia.id
        ).filter(Membresia.sucursal_id == sucursal_id)
    ingresos_query = ingresos_query.filter(*pagos_filters)
    ingresos_summary = ingresos_query.one()

    memb_count_q = (
        db.session.query(func.count(func.distinct(Pago.membresia_id)))
        .join(HistorialPago, HistorialPago.pago_id == Pago.id)
        .filter(*pagos_filters)
    )
    if sucursal_id and sucursal_id != 0:
        memb_count_q = memb_count_q.join(
            Membresia, Pago.membresia_id == Membresia.id
        ).filter(Membresia.sucursal_id == sucursal_id)
    total_membresias_pagadas = int(memb_count_q.scalar() or 0)

    ventas_summary = type("S", (), {"total_ventas": 0, "count_ventas": 0})()
    if include_ventas:
        ventas_query = db.session.query(
            func.coalesce(func.sum(Venta.monto_total), 0).label("total_ventas"),
            func.count(Venta.id).label("count_ventas"),
        )
        ventas_filters = [Venta.fecha_venta >= start_dt, Venta.fecha_venta <= end_dt]
        if sucursal_id and sucursal_id != 0:
            ventas_filters.append(Venta.sucursal_id == sucursal_id)
        ventas_query = ventas_query.filter(*ventas_filters)
        ventas_summary = ventas_query.one()

    total_ingresos = float(ingresos_summary.total_pagos or 0) + float(
        getattr(ventas_summary, "total_ventas", 0) or 0
    )
    total_ingresos_count = int(
        total_membresias_pagadas + (getattr(ventas_summary, "count_ventas", 0) or 0)
    )

    # egresos (gastos) filter by cuenta if provided
    gastos_query = db.session.query(
        func.coalesce(func.sum(Gasto.monto), 0).label("total_gastos"),
        func.count(Gasto.id).label("count_gastos"),
    )
    gastos_filters = [Gasto.fecha_gasto >= start_dt, Gasto.fecha_gasto <= end_dt]
    if sucursal_id and sucursal_id != 0:
        gastos_filters.append(Gasto.sucursal_id == sucursal_id)
    if cuenta_id:
        gastos_query = gastos_query.filter(Gasto.cuenta_id == cuenta_id)
    gastos_summary = gastos_query.filter(*gastos_filters).one()

    total_egresos = float(gastos_summary.total_gastos or 0)
    total_egresos_count = int(gastos_summary.count_gastos or 0)

    # plan stats
    plan_stats = []
    try:
        sub = (
            db.session.query(
                Pago.membresia_id,
                func.sum(HistorialPago.monto_pagado).label("sum_pago"),
            )
            .join(HistorialPago, HistorialPago.pago_id == Pago.id)
            .filter(
                HistorialPago.fecha_pago >= start_dt, HistorialPago.fecha_pago <= end_dt
            )
            .group_by(Pago.membresia_id)
            .subquery()
        )
        q = db.session.query(
            Plan.nombre, func.count(func.distinct(Membresia.id)).label("memb_count")
        )
        q = q.join(Membresia, Membresia.plan_id == Plan.id).join(
            sub, sub.c.membresia_id == Membresia.id
        )
        if sucursal_id and sucursal_id != 0:
            q = q.filter(Membresia.sucursal_id == sucursal_id)
        q = q.group_by(Plan.nombre).order_by(
            func.count(func.distinct(Membresia.id)).desc()
        )
        plan_stats = [{"plan": r[0], "count": int(r[1])} for r in q.all()]
    except Exception:
        plan_stats = []

    gastos_by_cat = []
    try:
        gc = db.session.query(
            CategoriaGasto.nombre,
            func.coalesce(func.sum(Gasto.monto), 0).label("total"),
        )
        gc = gc.join(Gasto, Gasto.categoria_id == CategoriaGasto.id).filter(
            Gasto.fecha_gasto >= start_dt, Gasto.fecha_gasto <= end_dt
        )
        if sucursal_id and sucursal_id != 0:
            gc = gc.filter(Gasto.sucursal_id == sucursal_id)
        if cuenta_id:
            gc = gc.filter(Gasto.cuenta_id == cuenta_id)
        gc = gc.group_by(CategoriaGasto.nombre).order_by(func.sum(Gasto.monto).desc())
        gastos_by_cat = [{"categoria": r[0], "total": float(r[1])} for r in gc.all()]
    except Exception:
        gastos_by_cat = []

    return dict(
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        total_ingresos_count=total_ingresos_count,
        total_egresos_count=total_egresos_count,
        plan_stats=plan_stats,
        gastos_by_cat=gastos_by_cat,
    )


@finanzas_bp.route("/data", methods=["POST"])
@admin_required
def data():
    # receive filters via form or json
    try:
        payload = request.get_json() if request.is_json else request.form
    except Exception:
        payload = request.form
    sucursal_id = int(payload.get("sucursal_id") or 0)
    period = payload.get("period") or "month"
    fecha_desde = payload.get("fecha_desde")
    fecha_hasta = payload.get("fecha_hasta")
    include_ventas = payload.get("include_ventas") in ("1", "true", "True", True, "on")
    cuenta_id = payload.get("cuenta_id")
    try:
        cuenta_id = int(cuenta_id) if cuenta_id else None
    except Exception:
        cuenta_id = None

    start_dt, end_dt = _parse_period(period, fecha_desde, fecha_hasta)
    result = _compute_finanzas(
        sucursal_id,
        start_dt,
        end_dt,
        include_ventas=include_ventas,
        cuenta_id=cuenta_id,
    )
    # also include list of sucursales and cuentas for client-side rendering if needed
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    cuentas = Cuenta.query.order_by(Cuenta.nombre).all()
    return render_template(
        "finanzas/_panel.html",
        sucursales=sucursales,
        cuentas=cuentas,
        start_dt=start_dt,
        end_dt=end_dt,
        period=period,
        selected_sucursal=sucursal_id,
        selected_cuenta=cuenta_id,
        include_ventas=include_ventas,
        **result
    )
