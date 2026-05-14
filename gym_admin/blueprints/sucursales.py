from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import current_user
from ..models import Sucursal
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required

sucursales_bp = Blueprint("sucursales", __name__)


@sucursales_bp.context_processor
def sucursal_context_processor():
    """
    Inyecta la lista de sucursales y la sucursal actual en el contexto de todas las plantillas.
    """
    sucursales_list = []
    sucursal_actual = None
    if current_user and current_user.is_authenticated:
        sucursales_list = Sucursal.query.order_by(Sucursal.nombre).all()
        # Prioridad: 1. Sucursal asignada al usuario, 2. Sucursal en sesión
        if (
            current_user.sucursal_id
        ):  # Si el usuario tiene una sucursal fija, esa es la única verdad.
            sucursal_actual = current_user.sucursal_id
        else:  # Si es un admin sin sucursal, entonces sí leemos la que haya seleccionado en la sesión.
            sucursal_actual = session.get("sucursal_id")

    return dict(sucursales=sucursales_list, sucursal_actual_id=sucursal_actual)


@sucursales_bp.route("/")
@admin_required
def list_sucursales():
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    return render_template("sucursales/list.html", sucursales=sucursales)


@sucursales_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_sucursal():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        direccion = request.form.get("direccion")
        telefono = request.form.get("telefono")
        estado = request.form.get("estado")
        s = Sucursal(
            nombre=nombre, direccion=direccion, telefono=telefono, estado=estado
        )
        db.session.add(s)
        db.session.commit()
        flash("Sucursal creada")
        return redirect(url_for("sucursales.list_sucursales"))
    return render_template("sucursales/form.html", sucursal=None)


@sucursales_bp.route("/<int:sucursal_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_sucursal(sucursal_id):
    s = Sucursal.query.get_or_404(sucursal_id)
    if request.method == "POST":
        s.nombre = request.form.get("nombre")
        s.direccion = request.form.get("direccion")
        s.telefono = request.form.get("telefono")
        s.estado = request.form.get("estado")
        db.session.commit()
        flash("Sucursal actualizada")
        return redirect(url_for("sucursales.list_sucursales"))
    return render_template("sucursales/form.html", sucursal=s)


@sucursales_bp.route("/<int:sucursal_id>/delete", methods=["POST"])
@admin_required
def delete_sucursal(sucursal_id):
    s = Sucursal.query.get_or_404(sucursal_id)
    try:
        db.session.delete(s)
        db.session.commit()
        flash("Sucursal eliminada")
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se puede eliminar la sucursal: existen clientes o membresías vinculadas."
        )
    return redirect(url_for("sucursales.list_sucursales"))


@sucursales_bp.route("/select/<int:sucursal_id>")
def select_sucursal(sucursal_id):
    # store selected sucursal in session; 0 means 'all' -> remove key
    if int(sucursal_id) == 0:
        session.pop("sucursal_id", None)
    else:
        session["sucursal_id"] = int(sucursal_id)
    return redirect(request.referrer or url_for("index"))
