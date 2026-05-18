from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    flash,
    session,
)
from ..models import Venta, DetalleVenta, Producto, Cliente
from ..extensions import db
from sqlalchemy import func
from datetime import datetime, timedelta
from ..utils_timezone import now_utc, to_bolivia, to_utc_naive

try:
    from flask_login import current_user
except Exception:
    # fallback: try to import current_user from auth blueprint
    try:
        from .auth import current_user
    except Exception:
        current_user = None

ventas_bp = Blueprint("ventas", __name__, template_folder="../templates/ventas")


@ventas_bp.route("/")
def list_ventas():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)
    period = request.args.get("period", "all")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    metodo_pago_filter = request.args.get("metodo_pago")

    query = Venta.query

    if q:
        like = f"%{q}%"
        query = query.join(Cliente).filter(
            (Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like))
        )

    if metodo_pago_filter:
        query = query.filter(Venta.metodo_pago == metodo_pago_filter)

    # --- LÓGICA DE FILTRADO POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated and current_user.sucursal_id:
        sucursal_id = current_user.sucursal_id
    elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
        sucursal_id = int(session.get("sucursal_id"))

    if sucursal_id:
        query = query.filter(Venta.sucursal_id == sucursal_id)

    # --- LÓGICA DE FILTRADO POR FECHA (interpretar entradas como hora Bolivia y convertir a UTC) ---
    try:
        if period and period != "all" and not (fecha_desde and fecha_hasta):
            now_b = to_bolivia(now_utc())
            if period == "today":
                start_b = datetime(now_b.year, now_b.month, now_b.day)
                end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            elif period == "week":
                start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                    days=now_b.weekday()
                )
                start_b = start_day
                end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif period == "month":
                start_b = datetime(now_b.year, now_b.month, 1)
                if now_b.month == 12:
                    nm = datetime(now_b.year + 1, 1, 1)
                else:
                    nm = datetime(now_b.year, now_b.month + 1, 1)
                end_b = nm - timedelta(seconds=1)
            elif period == "year":
                start_b = datetime(now_b.year, 1, 1)
                end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            else:
                start_b = None
                end_b = None
            if start_b and end_b:
                start = to_utc_naive(start_b)
                end = to_utc_naive(end_b)
                query = query.filter(
                    Venta.fecha_venta >= start,
                    Venta.fecha_venta < (end + timedelta(seconds=1)),
                )
        elif fecha_desde and fecha_hasta:
            sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
            hd_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
            start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
            end_b = datetime(hd_b.year, hd_b.month, hd_b.day, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Venta.fecha_venta >= start, Venta.fecha_venta <= end)
    except (ValueError, TypeError):
        flash("Formato de fecha inválido.", "warning")

    pag = query.order_by(Venta.fecha_venta.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = pag.items

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "ventas/_table.html",
            ventas=items,
            pagination=pag,
            q=q,
            period=period,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            metodo_pago_filter=metodo_pago_filter,
        )

    return render_template(
        "ventas/list.html",
        ventas=items,
        pagination=pag,
        q=q,
        period=period,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        metodo_pago_filter=metodo_pago_filter,
    )


@ventas_bp.route("/create", methods=["GET", "POST"])
def create_venta():
    # require authenticated user (similar to gastos)
    if current_user is None or not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login") + "?next=" + request.path)

    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        
        cliente_id = request.form.get("cliente_id") or None
        # set usuario_id from current_user

        # --- LÓGICA DE SUCURSAL PARA LA VENTA ---
        sucursal_id = None
        if current_user and current_user.is_authenticated and current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
            sucursal_id = int(session.get("sucursal_id"))

        usuario_id = getattr(current_user, "id", None)
        metodo = request.form.get("metodo_pago") or "Efectivo"
        descuento = float(request.form.get("descuento") or 0)

        productos = request.form.getlist("producto_id[]")
        cantidades = request.form.getlist("cantidad[]")
        precios = request.form.getlist("precio[]")

        # validate arrays
        if not productos:
            msg = "No se han añadido productos a la venta."
            if is_ajax:
                return jsonify({"success": False, "message": msg}), 400
            flash(msg, "warning")
            return redirect(url_for("ventas.create_venta"))
        if not sucursal_id:
            msg = "No se pudo determinar la sucursal para la venta. Por favor, seleccione una."
            if is_ajax:
                return jsonify({"success": False, "message": msg}), 400
            flash(msg, "danger")
            return redirect(url_for("ventas.create_venta"))

        # check stock availability first
        requested = []
        for i, pid in enumerate(productos):
            try:
                qty = int(cantidades[i])
            except Exception:
                qty = 1
            requested.append((int(pid), qty))

        # load products and validate
        prod_map = {
            p.id: p
            for p in Producto.query.filter(
                Producto.id.in_([p for p, _ in requested])
            ).all()
        }
        for pid, qty in requested:
            p = prod_map.get(pid)
            if not p:
                msg = f"El producto con ID {pid} no existe."
                if is_ajax:
                    return jsonify({"success": False, "message": msg}), 400
                flash(msg, "danger")
                return redirect(url_for("ventas.create_venta"))

            # Validar stock usando el nuevo método del modelo
            if qty > p.obtener_stock(sucursal_id):
                msg = f'Stock insuficiente para "{p.nombre}" en esta sucursal. Disponible: {p.obtener_stock(sucursal_id)}.'
                if is_ajax:
                    return jsonify({"success": False, "message": msg}), 400
                flash(msg, "danger")
                return redirect(url_for("ventas.create_venta"))

        # create venta and detalles inside try/except
        try:
            v = Venta(
                cliente_id=cliente_id,
                usuario_id=usuario_id,
                sucursal_id=sucursal_id,
                metodo_pago=metodo,
                monto_total=0,
            )
            db.session.add(v)
            db.session.flush()
            total_calc = 0
            for i, pid in enumerate(productos):
                pid_i = int(pid)
                try:
                    qty = int(cantidades[i])
                except Exception:
                    qty = 1
                try:
                    price = float(precios[i])
                except Exception:
                    price = 0
                subtotal = qty * price
                dv = DetalleVenta(
                    venta_id=v.id,
                    producto_id=pid_i,
                    cantidad=qty,
                    precio_unitario=price,
                    subtotal=subtotal,
                )
                db.session.add(dv)
                total_calc += subtotal
                # Ajustar stock usando el nuevo método del modelo
                prod = prod_map.get(pid_i)
                if prod:
                    prod.actualizar_stock(sucursal_id, qty, operacion="restar")

            total_calc = max(0, total_calc - float(descuento))
            v.monto_total = total_calc
            db.session.add(v)
            db.session.commit()
            
            if is_ajax:
                return jsonify({"success": True, "message": "Venta registrada exitosamente", "venta_id": v.id}), 200
            return redirect(url_for("ventas.list_ventas"))
        except Exception as e:
            db.session.rollback()
            msg = "Ocurrió un error inesperado al registrar la venta."
            if is_ajax:
                return jsonify({"success": False, "message": msg, "error": str(e)}), 500
            flash(msg, "danger")
            raise
    # GET: provide products list for building sale
    productos = (
        Producto.query.filter(Producto.estado == "Activo")
        .order_by(Producto.nombre)
        .all()
    )
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    return render_template("ventas/form.html", productos=productos, clientes=clientes)


@ventas_bp.route("/<int:vid>")
def view_venta(vid):
    v = Venta.query.get_or_404(vid)
    # Si es una petición AJAX, devolver solo el fragmento del cuerpo del modal
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("ventas/_detail_modal_body.html", venta=v)
    # Si se accede directamente, mostrar una página completa (fallback)
    return render_template("ventas/detail_page.html", venta=v)


@ventas_bp.route("/api/clientes")
def api_clientes():
    q = request.args.get("q", "")

    # --- OBTENER SUCURSAL ACTUAL PARA FILTRAR CLIENTES ---
    sucursal_id = None
    if current_user and current_user.is_authenticated and current_user.sucursal_id:
        sucursal_id = current_user.sucursal_id
    elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
        sucursal_id = int(session.get("sucursal_id"))

    query = Cliente.query
    if sucursal_id:
        query = query.filter(Cliente.sucursal_id == sucursal_id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like))
        )

    clientes = query.order_by(Cliente.nombre).limit(10).all()
    return jsonify([{"id": c.id, "text": f"{c.nombre} {c.apellido}"} for c in clientes])


@ventas_bp.route("/api/productos")
def api_productos():
    items = (
        Producto.query.filter(Producto.estado == "Activo")
        .order_by(Producto.nombre)
        .all()
    )

    # --- OBTENER SUCURSAL ACTUAL PARA CONSULTAR STOCK ---
    sucursal_id = None
    if current_user and current_user.is_authenticated and current_user.sucursal_id:
        sucursal_id = current_user.sucursal_id
    elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
        sucursal_id = int(session.get("sucursal_id"))

    out = []
    for p in items:
        stock_actual = p.obtener_stock(sucursal_id) if sucursal_id else 0
        out.append(
            {
                "id": p.id,
                "nombre": p.nombre,
                "precio": float(p.precio or 0),
                "stock": stock_actual,
            }
        )
    return jsonify({"items": out})


@ventas_bp.route("/api/summary")
def api_summary():
    """Devuelve un resumen (monto total y cantidad) de ventas según los mismos filtros que la lista."""
    q = request.args.get("q", type=str)
    period = request.args.get("period", "all")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    metodo_pago_filter = request.args.get("metodo_pago")

    query = Venta.query

    if q:
        like = f"%{q}%"
        query = query.join(Cliente).filter(
            (Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like))
        )

    if metodo_pago_filter:
        query = query.filter(Venta.metodo_pago == metodo_pago_filter)

    # --- LÓGICA DE FILTRADO POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated and current_user.sucursal_id:
        sucursal_id = current_user.sucursal_id
    elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
        sucursal_id = int(session.get("sucursal_id"))

    if sucursal_id:
        query = query.filter(Venta.sucursal_id == sucursal_id)

    # --- LÓGICA DE FILTRADO POR FECHA (para summary API) ---
    try:
        if period and period != "all" and not (fecha_desde and fecha_hasta):
            now_b = to_bolivia(now_utc())
            if period == "today":
                start_b = datetime(now_b.year, now_b.month, now_b.day)
                end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            elif period == "week":
                start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                    days=now_b.weekday()
                )
                start_b = start_day
                end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif period == "month":
                start_b = datetime(now_b.year, now_b.month, 1)
                if now_b.month == 12:
                    nm = datetime(now_b.year + 1, 1, 1)
                else:
                    nm = datetime(now_b.year, now_b.month + 1, 1)
                end_b = nm - timedelta(seconds=1)
            elif period == "year":
                start_b = datetime(now_b.year, 1, 1)
                end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            else:
                start_b = None
                end_b = None
            if start_b and end_b:
                start = to_utc_naive(start_b)
                end = to_utc_naive(end_b)
                query = query.filter(
                    Venta.fecha_venta >= start, Venta.fecha_venta <= end
                )
        elif fecha_desde and fecha_hasta:
            sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
            hd_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
            start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
            end_b = datetime(hd_b.year, hd_b.month, hd_b.day, 23, 59, 59)
            start = to_utc_naive(start_b)
            end = to_utc_naive(end_b)
            query = query.filter(Venta.fecha_venta >= start, Venta.fecha_venta <= end)
    except (ValueError, TypeError):
        # devolver 0 si hay problema en formato
        return jsonify(dict(total=0, count=0))

    # calcular suma y cantidad
    try:
        total = (
            query.with_entities(func.coalesce(func.sum(Venta.monto_total), 0)).scalar()
            or 0
        )
        count = query.with_entities(func.count(Venta.id)).scalar() or 0
        return jsonify(dict(total=float(total), count=int(count)))
    except Exception:
        return jsonify(dict(total=0, count=0))
