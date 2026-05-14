from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask import session
from ..extensions import db
from ..models import Cuenta, CategoriaGasto, Gasto, Usuario, Sucursal
from .. import utils_timezone
from ..utils_timezone import now_utc, to_bolivia, to_utc_naive
from datetime import datetime as _dt
from decimal import Decimal, InvalidOperation

try:
    from flask_login import current_user, login_required
except Exception:
    # flask-login no está disponible; reutilizar el fallback definido en el blueprint de auth
    try:
        from .auth import current_user
    except Exception:
        current_user = None
    from functools import wraps

    def login_required(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # si no hay objeto current_user, redirigir al login
            cu = current_user
            if cu is None or not getattr(cu, "is_authenticated", False):
                return redirect(
                    url_for("auth.login") + "?next=" + (request.path or "/")
                )
            return f(*args, **kwargs)

        return wrapped


from ..utils import admin_required

gastos_bp = Blueprint("gastos", __name__, template_folder="../templates/gastos")


@gastos_bp.before_request
def _ensure_admin_for_gastos():
    # allow static or unauthenticated access to some endpoints? enforce admin here
    try:
        if not (
            current_user
            and getattr(current_user, "is_authenticated", False)
            and getattr(current_user, "rol_id", None) == 1
        ):
            # if AJAX request, return 403
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                from flask import abort

                abort(403)
            flash("Acceso restringido: se requieren privilegios de administrador")
            return redirect(url_for("index"))
    except Exception:
        # fail closed
        flash("Acceso restringido")
        return redirect(url_for("index"))


# --- Cuentas ---
@gastos_bp.route("/cuentas")
def cuentas_list():
    cuentas = Cuenta.query.order_by(Cuenta.nombre).all()
    return render_template("gastos/cuentas_list.html", cuentas=cuentas)


@gastos_bp.route("/cuentas/create", methods=["GET", "POST"])
@admin_required
def cuentas_create():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("gastos.cuentas_create"))
        c = Cuenta(nombre=nombre)
        db.session.add(c)
        db.session.commit()
        flash("Cuenta creada")
        return redirect(url_for("gastos.cuentas_list"))
    return render_template("gastos/cuentas_form.html", cuenta=None)


@gastos_bp.route("/cuentas/<int:cuenta_id>/delete", methods=["POST"])
@admin_required
def cuentas_delete(cuenta_id):
    c = Cuenta.query.get_or_404(cuenta_id)
    try:
        db.session.delete(c)
        db.session.commit()
        flash("Cuenta eliminada")
    except Exception:
        db.session.rollback()
        flash("No se puede eliminar la cuenta: está en uso")
    return redirect(url_for("gastos.cuentas_list"))


# --- Categorías ---
@gastos_bp.route("/categorias")
def categorias_list():
    cats = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
    return render_template("gastos/categorias_list.html", categorias=cats)


@gastos_bp.route("/categorias/create", methods=["GET", "POST"])
@admin_required
def categorias_create():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("gastos.categorias_create"))
        c = CategoriaGasto(nombre=nombre)
        db.session.add(c)
        db.session.commit()
        flash("Categoría creada")
        return redirect(url_for("gastos.categorias_list"))
    return render_template("gastos/categorias_form.html", categoria=None)


@gastos_bp.route("/categorias/<int:cat_id>/delete", methods=["POST"])
@admin_required
def categorias_delete(cat_id):
    c = CategoriaGasto.query.get_or_404(cat_id)
    try:
        db.session.delete(c)
        db.session.commit()
        flash("Categoría eliminada")
    except Exception:
        db.session.rollback()
        flash("No se puede eliminar la categoría: está en uso")
    return redirect(url_for("gastos.categorias_list"))


# --- Gastos ---
def _require_login_redirect(next_url=None):
    if current_user is None:
        flash("El sistema de autenticación no está disponible")
        return redirect(url_for("auth.login"))
    if not current_user.is_authenticated:
        target = next_url or request.path
        return redirect(url_for("auth.login") + "?next=" + target)
    return None


@gastos_bp.route("/")
def gastos_list():
    # filtros
    q = request.args.get("q", type=str)
    categoria = request.args.get("categoria", type=int)
    cuenta = request.args.get("cuenta", type=int)
    usuario = request.args.get("usuario", type=int)
    periodo = request.args.get("periodo", type=str)  # day, week, month, year, custom
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    query = Gasto.query
    if q:
        like = f"%{q}%"
        query = query.filter(Gasto.descripcion.ilike(like))
    if categoria:
        query = query.filter_by(categoria_id=categoria)
    if cuenta:
        query = query.filter_by(cuenta_id=cuenta)
    if usuario:
        query = query.filter_by(usuario_id=usuario)

    # manejo de periodos simples: interpretar en hora Bolivia y convertir límites a UTC-naive
    from datetime import date, datetime, timedelta

    try:
        if periodo in ("day", "week", "month", "year"):
            now_b = to_bolivia(now_utc())
            if periodo == "day":
                start_b = datetime(now_b.year, now_b.month, now_b.day)
                end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            elif periodo == "week":
                start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                    days=now_b.weekday()
                )
                start_b = start_day
                end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif periodo == "month":
                start_b = datetime(now_b.year, now_b.month, 1)
                if now_b.month == 12:
                    nextm = datetime(now_b.year + 1, 1, 1)
                else:
                    nextm = datetime(now_b.year, now_b.month + 1, 1)
                end_b = nextm - timedelta(seconds=1)
            else:  # year
                start_b = datetime(now_b.year, 1, 1)
                end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Gasto.fecha_gasto >= start, Gasto.fecha_gasto <= end)
        elif periodo == "custom" and fecha_desde and fecha_hasta:
            sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
            sh_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
            start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
            end_b = datetime(sh_b.year, sh_b.month, sh_b.day, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Gasto.fecha_gasto >= start, Gasto.fecha_gasto <= end)
    except Exception:
        pass

    pag = query.order_by(Gasto.fecha_gasto.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    gastos = pag.items
    # preparar listas para selects
    cuentas = Cuenta.query.order_by(Cuenta.nombre).all()
    categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    return render_template(
        "gastos/gastos_list.html",
        gastos=gastos,
        pagination=pag,
        cuentas=cuentas,
        categorias=categorias,
        usuarios=usuarios,
        q=q,
        categoria=categoria,
        cuenta=cuenta,
        usuario=usuario,
        periodo=periodo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


@gastos_bp.route("/table")
def gastos_table():
    # identical to gastos_list filtering but returns only the partial table for AJAX
    q = request.args.get("q", type=str)
    categoria = request.args.get("categoria", type=int)
    cuenta = request.args.get("cuenta", type=int)
    usuario = request.args.get("usuario", type=int)
    periodo = request.args.get("periodo", type=str)
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    query = Gasto.query
    if q:
        like = f"%{q}%"
        query = query.filter(Gasto.descripcion.ilike(like))
    if categoria:
        query = query.filter_by(categoria_id=categoria)
    if cuenta:
        query = query.filter_by(cuenta_id=cuenta)
    if usuario:
        query = query.filter_by(usuario_id=usuario)

    from datetime import date, datetime, timedelta

    try:
        if periodo in ("day", "week", "month", "year"):
            now_b = to_bolivia(now_utc())
            if periodo == "day":
                start_b = datetime(now_b.year, now_b.month, now_b.day)
                end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            elif periodo == "week":
                start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                    days=now_b.weekday()
                )
                start_b = start_day
                end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif periodo == "month":
                start_b = datetime(now_b.year, now_b.month, 1)
                if now_b.month == 12:
                    nextm = datetime(now_b.year + 1, 1, 1)
                else:
                    nextm = datetime(now_b.year, now_b.month + 1, 1)
                end_b = nextm - timedelta(seconds=1)
            else:
                start_b = datetime(now_b.year, 1, 1)
                end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Gasto.fecha_gasto >= start, Gasto.fecha_gasto <= end)
        elif periodo == "custom" and fecha_desde and fecha_hasta:
            sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
            sh_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
            start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
            end_b = datetime(sh_b.year, sh_b.month, sh_b.day, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Gasto.fecha_gasto >= start, Gasto.fecha_gasto <= end)
    except Exception:
        pass

    pag = query.order_by(Gasto.fecha_gasto.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    gastos = pag.items
    return render_template("gastos/_table.html", gastos=gastos, pagination=pag)


@gastos_bp.route("/export.csv", methods=["GET", "POST"])
def gastos_export():
    # aceptar filtros por GET o POST (para soportar envío desde JS sin exponer en URL)
    data = request.values
    q = data.get("q")
    categoria = data.get("categoria", type=int)
    cuenta = data.get("cuenta", type=int)
    usuario = data.get("usuario", type=int)
    periodo = data.get("periodo")
    fecha_desde = data.get("fecha_desde")
    fecha_hasta = data.get("fecha_hasta")

    query = Gasto.query
    if q:
        like = f"%{q}%"
        query = query.filter(Gasto.descripcion.ilike(like))
    if categoria:
        query = query.filter_by(categoria_id=categoria)
    if cuenta:
        query = query.filter_by(cuenta_id=cuenta)
    if usuario:
        query = query.filter_by(usuario_id=usuario)
    # apply period filters (reuse logic) -- simplified: only custom dates respected here
    try:
        if periodo == "custom" and fecha_desde and fecha_hasta:
            from datetime import datetime as _dt

            sd = _dt.strptime(fecha_desde, "%Y-%m-%d")
            sh = _dt.strptime(fecha_hasta, "%Y-%m-%d")
            query = query.filter(
                Gasto.fecha_gasto >= _dt.combine(sd, _dt.min.time()),
                Gasto.fecha_gasto <= _dt.combine(sh, _dt.max.time()),
            )
    except Exception:
        pass

    rows = query.order_by(Gasto.fecha_gasto.desc()).all()
    import csv
    from io import StringIO

    si = StringIO()
    cw = csv.writer(si)
    # encabezados con filtros usados
    headers = ["Filtro:"]
    headers.append(f"q={q or ''}")
    headers.append(f"categoria={categoria or ''}")
    headers.append(f"cuenta={cuenta or ''}")
    headers.append(f"usuario={usuario or ''}")
    headers.append(f"periodo={periodo or ''}")
    headers.append(f"fecha_desde={fecha_desde or ''}")
    headers.append(f"fecha_hasta={fecha_hasta or ''}")
    cw.writerow(headers)
    cw.writerow(
        ["id", "fecha_gasto", "descripcion", "monto", "cuenta", "categoria", "usuario"]
    )
    for r in rows:
        cw.writerow(
            [
                r.id,
                r.fecha_gasto,
                r.descripcion,
                r.monto,
                r.cuenta.nombre if r.cuenta else "",
                r.categoria.nombre if r.categoria else "",
                r.usuario.nombre if r.usuario else r.usuario_id,
            ]
        )
    output = si.getvalue()
    return (
        output,
        200,
        {
            "Content-Type": "text/csv",
            "Content-Disposition": 'attachment; filename="gastos_export.csv"',
        },
    )


@gastos_bp.route("/print", methods=["GET", "POST"])
def gastos_print():
    data = request.values
    q = data.get("q")
    categoria = data.get("categoria", type=int)
    cuenta = data.get("cuenta", type=int)
    usuario = data.get("usuario", type=int)
    periodo = data.get("periodo")
    fecha_desde = data.get("fecha_desde")
    fecha_hasta = data.get("fecha_hasta")

    query = Gasto.query
    if q:
        like = f"%{q}%"
        query = query.filter(Gasto.descripcion.ilike(like))
    if categoria:
        query = query.filter_by(categoria_id=categoria)
    if cuenta:
        query = query.filter_by(cuenta_id=cuenta)
    if usuario:
        query = query.filter_by(usuario_id=usuario)

    # include filters header
    rows = query.order_by(Gasto.fecha_gasto.desc()).all()
    from datetime import datetime as _dt

    filters = dict(
        q=q,
        categoria=categoria,
        cuenta=cuenta,
        usuario=usuario,
        periodo=periodo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    # maps
    cuentas_map = {c.id: c.nombre for c in Cuenta.query.all()}
    categorias_map = {c.id: c.nombre for c in CategoriaGasto.query.all()}
    usuarios_map = {u.id: (u.nombre or u.correo) for u in Usuario.query.all()}
    return render_template(
        "gastos/gastos_print.html",
        gastos=rows,
        now=_dt.utcnow(),
        filters=filters,
        cuentas_map=cuentas_map,
        categorias_map=categorias_map,
        usuarios_map=usuarios_map,
    )


@gastos_bp.route("/create", methods=["GET", "POST"])
@admin_required
def gastos_create():
    # require login
    r = _require_login_redirect(request.path)
    if r:
        return r

    cuentas = Cuenta.query.order_by(Cuenta.nombre).all()
    categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()

    if request.method == "POST":
        descripcion = (request.form.get("descripcion") or "").strip()
        monto_raw = (request.form.get("monto") or "0").strip()
        cuenta_id = request.form.get("cuenta_id")
        categoria_id = request.form.get("categoria_id")
        fecha_raw = (request.form.get("fecha_gasto") or "").strip()
        if fecha_raw:
            fecha_raw = fecha_raw.replace("T", " ")

        # validaciones
        if not descripcion:
            flash("Descripción requerida")
            return redirect(url_for("gastos.gastos_create"))
        try:
            monto = Decimal(monto_raw)
        except (InvalidOperation, ValueError):
            flash("Monto inválido")
            return redirect(url_for("gastos.gastos_create"))
        if monto <= 0:
            flash("El monto debe ser mayor que 0")
            return redirect(url_for("gastos.gastos_create"))

        # obtener usuario desde current_user
        uid = None
        try:
            uid = current_user.id
        except Exception:
            uid = None
        if not uid:
            # redirigir al login con next si no autenticado
            return redirect(
                url_for("auth.login") + "?next=" + url_for("gastos.gastos_create")
            )
        # Sucursal: preferir valor enviado en el formulario, luego sesión
        sucursal_id = request.form.get("sucursal_id") or session.get("sucursal_id")
        if not sucursal_id:
            flash("Seleccione una sucursal antes de registrar el gasto")
            return redirect(url_for("gastos.gastos_create"))
        try:
            sucursal_id = int(sucursal_id)
        except Exception:
            flash("Sucursal inválida")
            return redirect(url_for("gastos.gastos_create"))
        # Fecha del gasto: si el formulario trae una fecha (en hora local Bolivia), convertir a UTC al guardar
        fecha_gasto = None
        if fecha_raw:
            # aceptar formatos con o sin segundos
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = _dt.strptime(fecha_raw, fmt)
                    break
                except Exception:
                    parsed = None
            if parsed:
                # interpretamos la entrada como hora local de Bolivia y convertimos a UTC naive
                fecha_gasto = utils_timezone.to_utc_naive(parsed)
            else:
                flash("Formato de fecha inválido. Usa YYYY-MM-DD HH:MM")
                return redirect(url_for("gastos.gastos_create"))
        else:
            # usar ahora en UTC (naive UTC para almacenar en DATETIME)
            fecha_gasto = utils_timezone.to_utc_naive(utils_timezone.now_utc())

        g = Gasto(
            descripcion=descripcion,
            monto=monto,
            categoria_id=categoria_id or None,
            cuenta_id=cuenta_id or None,
            usuario_id=uid,
            sucursal_id=sucursal_id,
            fecha_gasto=fecha_gasto,
        )
        db.session.add(g)
        db.session.commit()
        flash("Gasto registrado")
        return redirect(url_for("gastos.gastos_list"))

    return render_template(
        "gastos/gastos_form.html",
        cuentas=cuentas,
        categorias=categorias,
        sucursales=sucursales,
    )


@gastos_bp.route("/<int:gasto_id>/delete", methods=["POST"])
@admin_required
def gastos_delete(gasto_id):
    r = _require_login_redirect(request.path)
    if r:
        return r
    g = Gasto.query.get_or_404(gasto_id)
    try:
        db.session.delete(g)
        db.session.commit()
        flash("Gasto eliminado")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar el gasto")
    return redirect(url_for("gastos.gastos_list"))
