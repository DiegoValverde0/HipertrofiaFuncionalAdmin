from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import Promocion
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required

promociones_bp = Blueprint("promociones", __name__)


@promociones_bp.route("/")
def list_promociones():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)
    query = Promocion.query
    if q:
        like = f"%{q}%"
        query = query.filter(Promocion.nombre.ilike(like))
    pag = query.order_by(Promocion.fecha_inicio.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        "promociones/list.html", pagination=pag, promociones=pag.items
    )


@promociones_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_promocion():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = request.form.get("descripcion") or ""
        descuento = request.form.get("descuento") or 0
        fecha_inicio = request.form.get("fecha_inicio") or None
        fecha_fin = request.form.get("fecha_fin") or None
        estado = request.form.get("estado") or "Activo"
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("promociones.create_promocion"))
        try:
            descuento = float(descuento)
        except Exception:
            descuento = 0
        p = Promocion(
            nombre=nombre,
            descripcion=descripcion,
            descuento=descuento,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            estado=estado,
        )
        db.session.add(p)
        db.session.commit()
        flash("Promoción creada")
        return redirect(url_for("promociones.list_promociones"))
    return render_template("promociones/form.html", promocion=None)


@promociones_bp.route("/<int:promocion_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_promocion(promocion_id):
    p = Promocion.query.get_or_404(promocion_id)
    if request.method == "POST":
        p.nombre = (request.form.get("nombre") or "").strip()
        p.descripcion = request.form.get("descripcion") or ""
        try:
            p.descuento = float(request.form.get("descuento") or 0)
        except Exception:
            p.descuento = 0
        p.fecha_inicio = request.form.get("fecha_inicio") or p.fecha_inicio
        p.fecha_fin = request.form.get("fecha_fin") or p.fecha_fin
        p.estado = request.form.get("estado") or p.estado
        db.session.commit()
        flash("Promoción actualizada")
        return redirect(url_for("promociones.list_promociones"))
    return render_template("promociones/form.html", promocion=p)


@promociones_bp.route("/<int:promocion_id>/delete", methods=["POST"])
@admin_required
def delete_promocion(promocion_id):
    p = Promocion.query.get_or_404(promocion_id)
    try:
        db.session.delete(p)
        db.session.commit()
        flash("Promoción eliminada")
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se puede eliminar la promoción: existen membresías vinculadas que la usan."
        )
    return redirect(url_for("promociones.list_promociones"))
