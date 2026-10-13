from flask import Blueprint, current_app, jsonify, render_template, request, session
from ..models import Gasto, Pago, Cliente, Membresia, Plan
from ..extensions import db
from datetime import date
from sqlalchemy import func
from flask_login import current_user

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../templates")


@dashboard_bp.route("/")
def dashboard_home():
    # la plantilla `home.html` actuará como dashboard
    return render_template("home.html")


def _month_key(dt):
    return dt.strftime("%Y-%m")


@dashboard_bp.route("/api/financials/monthly")
def api_financials_monthly():
    # devuelve ingresos (pagos) y egresos (gastos) por mes para el último año
    try:
        today = date.today()
        start = today.replace(year=today.year - 1, day=1)
    except Exception:
        start = date.today()

    # allow optional inclusion of cafeteria ventas into ingresos
    include_cafeteria = request.args.get("include_cafeteria", default="0") in (
        "1",
        "true",
        "True",
    )

    pagos_q = (
        db.session.query(
            func.strftime("%Y-%m", Pago.fecha_pago).label("m"),
            func.sum(Pago.monto_total).label("ingresos"),
        )
        .filter(Pago.fecha_pago >= start)
        .group_by("m")
        .order_by("m")
    )
    gastos_q = (
        db.session.query(
            func.strftime("%Y-%m", Gasto.fecha_gasto).label("m"),
            func.sum(Gasto.monto).label("egresos"),
        )
        .filter(Gasto.fecha_gasto >= start)
        .group_by("m")
        .order_by("m")
    )

    # Detect DB dialect and use appropriate month-format function (SQLite vs MySQL vs Postgres)
    try:
        bind = db.session.get_bind()
        dialect = getattr(bind, "dialect").name
    except Exception:
        dialect = "sqlite"

    if dialect in ("mysql", "mariadb"):
        m_expr_pago = func.date_format(Pago.fecha_pago, "%Y-%m")
        m_expr_gasto = func.date_format(Gasto.fecha_gasto, "%Y-%m")
    elif dialect == "postgresql":
        m_expr_pago = func.to_char(Pago.fecha_pago, "YYYY-MM")
        m_expr_gasto = func.to_char(Gasto.fecha_gasto, "YYYY-MM")
    else:
        m_expr_pago = func.strftime("%Y-%m", Pago.fecha_pago)
        m_expr_gasto = func.strftime("%Y-%m", Gasto.fecha_gasto)

    # Apply sucursal filter when available (for pagos via membresia and for clients/members)
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        else:
            sucursal_id = session.get("sucursal_id")

    pagos_query = db.session.query(
        m_expr_pago.label("m"), func.sum(Pago.monto_total).label("ingresos")
    ).filter(Pago.fecha_pago >= start)
    if sucursal_id:
        pagos_query = pagos_query.filter(Pago.sucursal_id == int(sucursal_id))
    pagos_q = pagos_query.group_by(m_expr_pago).order_by(m_expr_pago)

    gastos_query = db.session.query(
        m_expr_gasto.label("m"), func.sum(Gasto.monto).label("egresos")
    ).filter(Gasto.fecha_gasto >= start)
    # Aplicar filtro de sucursal a los gastos
    if sucursal_id:
        gastos_query = gastos_query.filter(Gasto.sucursal_id == int(sucursal_id))
    gastos_q = gastos_query.group_by(m_expr_gasto).order_by(m_expr_gasto)

    pagos = {r.m: float(r.ingresos or 0) for r in pagos_q}
    gastos = {r.m: float(r.egresos or 0) for r in gastos_q}

    # if include_cafeteria requested, aggregate Venta.monto_total by month and add to pagos
    if include_cafeteria:
        try:
            from ..models import Venta

            # build month expression for Venta.fecha_venta similar to Pago/Gasto above
            if dialect in ("mysql", "mariadb"):
                m_expr_venta = func.date_format(Venta.fecha_venta, "%Y-%m")
            elif dialect == "postgresql":
                m_expr_venta = func.to_char(Venta.fecha_venta, "YYYY-MM")
            else:
                m_expr_venta = func.strftime("%Y-%m", Venta.fecha_venta)
            ventas_query = db.session.query(
                m_expr_venta.label("m"), func.sum(Venta.monto_total).label("ventas_ing")
            ).filter(Venta.fecha_venta >= start)
            # respect sucursal by joining Venta -> Cliente -> Cliente.sucursal_id when sucursal filter present
            if sucursal_id:
                ventas_query = ventas_query.filter(Venta.sucursal_id == int(sucursal_id))
            ventas_q = ventas_query.group_by(m_expr_venta).order_by(m_expr_venta)
            ventas_map = {r.m: float(r.ventas_ing or 0) for r in ventas_q}
            # add ventas_map into pagos map by month key
            for k, v in ventas_map.items():
                pagos[k] = pagos.get(k, 0.0) + v
        except Exception:
            # if Venta model is unavailable or query fails, ignore and continue
            pass

    # construir lista de meses entre start y hoy
    labels = []
    data_ing = []
    data_eg = []
    cur = start
    while cur <= date.today():
        key = cur.strftime("%Y-%m")
        labels.append(key)
        data_ing.append(pagos.get(key, 0.0))
        data_eg.append(gastos.get(key, 0.0))
        # avanzar mes
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    return jsonify(dict(labels=labels, ingresos=data_ing, egresos=data_eg))


@dashboard_bp.route("/api/clients/summary")
def api_clients_summary():
    try:
        sucursal_id = None
        if current_user and current_user.is_authenticated:
            if current_user.sucursal_id:
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        # normalize session value '0' to None (selector uses '0' for "Todas")
        try:
            if sucursal_id is not None and str(sucursal_id) == "0":
                sucursal_id = None
        except Exception:
            pass
        q = Cliente.query
        if sucursal_id:
            q = q.filter(Cliente.sucursal_id == int(sucursal_id))
        total = q.count()
        activos = q.filter(Cliente.estado == "Activo").count()
        inactivos = total - activos
        return jsonify(
            dict(
                total=total,
                activos=activos,
                inactivos=inactivos,
                sucursal_id=sucursal_id,
            )
        )
    except Exception as e:
        return jsonify(dict(error=str(e)))


@dashboard_bp.route("/api/clients/birthdays")
def api_clients_birthdays():
    # devuelve clientes con cumpleaños esta semana (respetando sucursal)
    from datetime import timedelta

    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    results = []
    try:
        sucursal_id = None
        if current_user and current_user.is_authenticated:
            if current_user.sucursal_id:
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        q = Cliente.query.filter(Cliente.fecha_nacimiento != None)
        if sucursal_id:
            q = q.filter(Cliente.sucursal_id == int(sucursal_id))
        clients = q.all()
    except Exception as e:
        return jsonify(dict(error=str(e)))
    for c in clients:
        try:
            b = c.fecha_nacimiento
            try:
                b_this = b.replace(year=start.year)
            except ValueError:
                b_this = date(start.year, 2, 28)
            if start <= b_this <= end:
                results.append(
                    dict(
                        id=c.id,
                        nombre=f"{c.nombre} {c.apellido}",
                        fecha_nacimiento=c.fecha_nacimiento.isoformat(),
                        fecha_formateada=b_this.isoformat(),
                        telefono=(getattr(c, "telefono", None) or ""),
                    )
                )
        except Exception:
            continue
    return jsonify(results)


@dashboard_bp.route("/api/members/expiring")
def api_members_expiring():
    # clientes cuya cobertura termina en los próximos `days` días (default 30).
    # Un cliente con una renovación pagada en espera no aparece.
    from datetime import timedelta
    from .clientes import _compute_client_flags_global
    from ..services.membership_service import local_today

    days = request.args.get("days", default=30, type=int)
    now = local_today()
    cutoff = now + timedelta(days=days)
    try:
        sucursal_id = None
        if current_user and current_user.is_authenticated:
            if current_user.sucursal_id:
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        sucursal_id = int(sucursal_id) if sucursal_id else None

        # membresías que terminan en la ventana, sólo para acotar los clientes
        mq = db.session.query(Membresia.cliente_id).filter(
            Membresia.fecha_fin >= now, Membresia.fecha_fin <= cutoff
        )
        if sucursal_id:
            mq = mq.filter(Membresia.sucursal_id == sucursal_id)
        client_ids = {row.cliente_id for row in mq.distinct()}
        clients = (
            Cliente.query.filter(Cliente.id.in_(client_ids)).all() if client_ids else []
        )

        flags = _compute_client_flags_global(
            clients, horizon_days=days, sucursal_id=sucursal_id
        )
        out = []
        for c in clients:
            f = flags.get(c.id, {})
            if not f.get("soon") or not f.get("fecha_fin"):
                continue
            fecha_fin = date.fromisoformat(f["fecha_fin"])
            out.append(
                dict(
                    cliente_id=c.id,
                    nombre=f"{c.nombre} {c.apellido}",
                    telefono=(getattr(c, "telefono", None) or ""),
                    fecha_fin=fecha_fin.isoformat(),
                    days_left=(fecha_fin - now).days,
                )
            )
        out.sort(key=lambda item: item["days_left"])
        return jsonify(dict(count=len(out), items=out))
    except Exception as e:
        current_app.logger.exception("Error en api_members_expiring")
        return jsonify(dict(error=str(e))), 500


@dashboard_bp.route("/api/overview")
def api_overview():
    """Return totals for cards (clientes total/activos/inactivos) respecting sucursal filter"""
    try:
        sucursal_id = None
        if current_user and current_user.is_authenticated:
            if current_user.sucursal_id:
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        q = Cliente.query
        if sucursal_id:
            q = q.filter(Cliente.sucursal_id == int(sucursal_id))
        total = q.count()
        activos = q.filter(Cliente.estado == "Activo").count()
        inactivos = total - activos
        return jsonify(dict(total=total, activos=activos, inactivos=inactivos))
    except Exception as e:
        return jsonify(dict(error=str(e)))


@dashboard_bp.route("/api/planes/populares")
def api_planes_populares():
    """Return top N plans by number of memberships (respecting sucursal)
    Response: { items: [{plan_id, nombre, count}], total: n }
    """
    try:
        sucursal_id = None
        if current_user and current_user.is_authenticated:
            if current_user.sucursal_id:
                sucursal_id = current_user.sucursal_id
            else:
                sucursal_id = session.get("sucursal_id")
        from sqlalchemy import func

        q = db.session.query(
            Membresia.plan_id, func.count(Membresia.id).label("cnt")
        ).join(Plan, Membresia.plan_id == Plan.id)
        if sucursal_id:
            q = q.filter(Membresia.sucursal_id == int(sucursal_id))
        q = (
            q.group_by(Membresia.plan_id)
            .order_by(func.count(Membresia.id).desc())
            .limit(8)
        )
        rows = q.all()
        items = []
        for pid, cnt in rows:
            plan = db.session.get(Plan, pid)
            items.append(
                dict(
                    plan_id=pid,
                    nombre=plan.nombre if plan else str(pid),
                    count=int(cnt),
                )
            )
        return jsonify(dict(items=items, total=len(items)))
    except Exception as e:
        return jsonify(dict(error=str(e)))


@dashboard_bp.route("/api/promociones/activas")
def api_promociones_activas():
    """Return active promotions (respecting global state only)."""
    try:
        from ..models import Promocion

        date.today()
        q = Promocion.query.filter(Promocion.estado == "Activo")
        # optionally respect sucursal if promos have sucursal (they don't by model); keep global
        rows = q.order_by(Promocion.fecha_fin.asc()).limit(10).all()
        items = [
            dict(
                id=p.id,
                nombre=p.nombre,
                descripcion=p.descripcion or "",
                descuento=p.descuento,
                fecha_inicio=(p.fecha_inicio.isoformat() if p.fecha_inicio else None),
                fecha_fin=(p.fecha_fin.isoformat() if p.fecha_fin else None),
            )
            for p in rows
        ]
        return jsonify(dict(items=items, total=len(items)))
    except Exception as e:
        return jsonify(dict(error=str(e)))
