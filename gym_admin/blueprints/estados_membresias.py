from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import EstadoMembresia
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required

estados_bp = Blueprint("estados_membresias", __name__)


@estados_bp.route("/")
def list_estados():
    estados = EstadoMembresia.query.order_by(EstadoMembresia.nombre).all()
    return render_template("estados_membresias/list.html", estados=estados)


@estados_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_estado():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("estados_membresias.create_estado"))
        e = EstadoMembresia(nombre=nombre)
        db.session.add(e)
        db.session.commit()
        flash("Estado creado")
        return redirect(url_for("estados_membresias.list_estados"))
    return render_template("estados_membresias/form.html", estado=None)


@estados_bp.route("/<int:estado_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_estado(estado_id):
    e = EstadoMembresia.query.get_or_404(estado_id)
    if request.method == "POST":
        e.nombre = (request.form.get("nombre") or "").strip()
        db.session.commit()
        flash("Estado actualizado")
        return redirect(url_for("estados_membresias.list_estados"))
    return render_template("estados_membresias/form.html", estado=e)


@estados_bp.route("/<int:estado_id>/delete", methods=["POST"])
@admin_required
def delete_estado(estado_id):
    e = EstadoMembresia.query.get_or_404(estado_id)
    try:
        db.session.delete(e)
        db.session.commit()
        flash("Estado eliminado")
    except IntegrityError:
        db.session.rollback()
        flash("No se puede eliminar el estado: existen membresías que lo utilizan.")
    return redirect(url_for("estados_membresias.list_estados"))
