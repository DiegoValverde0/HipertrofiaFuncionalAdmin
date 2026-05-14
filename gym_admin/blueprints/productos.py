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
from ..models import Producto, Inventario
from ..extensions import db
from flask_login import current_user
from ..utils import admin_required

productos_bp = Blueprint(
    "productos", __name__, template_folder="../templates/productos"
)


@productos_bp.route("/")
def list_productos():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)

    # --- LÓGICA DE FILTRADO POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and str(session.get("sucursal_id")) != "0":
            sucursal_id = int(session.get("sucursal_id"))

    query = Producto.query
    if q:
        like = f"%{q}%"
        query = query.filter(Producto.nombre.ilike(like))

    pag = query.order_by(Producto.nombre.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = pag.items

    # Para cada producto, obtener el stock de la sucursal actual
    stock_por_producto = {}
    if sucursal_id:
        inventarios = Inventario.query.filter(
            Inventario.sucursal_id == sucursal_id,
            Inventario.producto_id.in_([p.id for p in items]),
        ).all()
        stock_por_producto = {inv.producto_id: inv.cantidad for inv in inventarios}

    # Support AJAX partial response
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("partial") == "1"
    )

    ctx = dict(
        productos=items,
        pagination=pag,
        q=q,
        per_page=per_page,
        page=page,
        stock_por_producto=stock_por_producto,
        sucursal_actual_id=sucursal_id,
    )

    if is_ajax:
        return render_template("productos/_table.html", **ctx)

    return render_template("productos/list.html", **ctx)


@productos_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_producto():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = request.form.get("descripcion")
        precio = request.form.get("precio") or 0

        # El stock ya no se gestiona aquí, solo se crea el producto en el catálogo global.
        p = Producto(
            nombre=nombre, descripcion=descripcion, precio=precio, estado="Activo"
        )
        db.session.add(p)
        db.session.commit()
        flash(
            "Producto creado en el catálogo global. Ahora puedes ajustar el stock en cada sucursal."
        )
        return redirect(url_for("productos.list_productos"))
    return render_template("productos/form.html", producto=None)


@productos_bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def edit_producto(pid):
    p = Producto.query.get_or_404(pid)
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = request.form.get("descripcion")
        precio = request.form.get("precio") or p.precio

        # El stock ya no se gestiona aquí.
        p.nombre = nombre
        p.descripcion = descripcion
        p.precio = precio
        db.session.add(p)
        db.session.commit()
        flash("Producto actualizado.")
        return redirect(url_for("productos.list_productos"))
    return render_template("productos/form.html", producto=p)


@productos_bp.route("/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_producto(pid):
    p = Producto.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("productos.list_productos"))


@productos_bp.route("/<int:producto_id>/ajustar_stock", methods=["POST"])
@admin_required
def ajustar_stock(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    sucursal_id = request.form.get("sucursal_id", type=int)
    cantidad = request.form.get("cantidad", type=int)
    operacion = request.form.get("operacion")

    if not sucursal_id:
        flash("No se ha especificado una sucursal para el ajuste de stock.", "danger")
        return redirect(url_for("productos.list_productos"))

    if cantidad is None or cantidad < 0:
        flash("La cantidad debe ser un número positivo.", "danger")
        return redirect(url_for("productos.list_productos"))

    try:
        if operacion == "establecer":
            # Para 'establecer', primero reseteamos a 0 y luego sumamos la nueva cantidad.
            stock_actual = producto.obtener_stock(sucursal_id)
            if stock_actual > 0:
                producto.actualizar_stock(sucursal_id, stock_actual, operacion="restar")
            producto.actualizar_stock(sucursal_id, cantidad, operacion="sumar")
        else:
            producto.actualizar_stock(sucursal_id, cantidad, operacion=operacion)
        db.session.commit()
        flash(f'Stock de "{producto.nombre}" actualizado en la sucursal.', "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar el stock: {e}", "danger")

    return redirect(url_for("productos.list_productos"))


@productos_bp.route("/api/list")
def api_list():
    items = (
        Producto.query.filter(Producto.estado == "Activo")
        .order_by(Producto.nombre)
        .all()
    )
    out = [
        {
            "id": x.id,
            "nombre": x.nombre,
            "precio": float(x.precio or 0),
            "stock": x.stock,
        }
        for x in items
    ]
    return jsonify({"items": out})
