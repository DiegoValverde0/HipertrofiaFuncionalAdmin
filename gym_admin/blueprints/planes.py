from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import Plan
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from ..utils import admin_required

planes_bp = Blueprint("planes", __name__)


@planes_bp.route("/")
def list_planes():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)
    query = Plan.query
    if q:
        like = f"%{q}%"
        query = query.filter(Plan.nombre.ilike(like))
    pag = query.order_by(Plan.fecha_creacion.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template("planes/list.html", pagination=pag, planes=pag.items)


@planes_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_plan():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = request.form.get("descripcion") or ""
        duracion = request.form.get("duracion") or ""
        precio = request.form.get("precio") or 0
        tipo = request.form.get("tipo") or "Individual"
        estado = request.form.get("estado") or "Activo"
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("planes.create_plan"))
        try:
            precio = float(precio)
        except Exception:
            precio = 0
        p = Plan(
            nombre=nombre,
            descripcion=descripcion,
            duracion=duracion,
            precio=precio,
            tipo=tipo,
            estado=estado,
            fecha_creacion=datetime.utcnow(),
        )
        db.session.add(p)
        db.session.commit()
        flash("Plan creado")
        return redirect(url_for("planes.list_planes"))
    return render_template("planes/form.html", plan=None)


@planes_bp.route("/<int:plan_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_plan(plan_id):
    p = Plan.query.get_or_404(plan_id)
    if request.method == "POST":
        p.nombre = (request.form.get("nombre") or "").strip()
        p.descripcion = request.form.get("descripcion") or ""
        p.duracion = request.form.get("duracion") or p.duracion
        try:
            p.precio = float(request.form.get("precio") or 0)
        except Exception:
            p.precio = 0
        p.tipo = request.form.get("tipo") or p.tipo
        p.estado = request.form.get("estado") or p.estado
        db.session.commit()
        flash("Plan actualizado")
        return redirect(url_for("planes.list_planes"))
    return render_template("planes/form.html", plan=p)


@planes_bp.route("/<int:plan_id>/delete", methods=["POST"])
@admin_required
def delete_plan(plan_id):
    p = Plan.query.get_or_404(plan_id)
    try:
        db.session.delete(p)
        db.session.commit()
        flash("Plan eliminado")
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se puede eliminar el plan: existen membresías u otros registros vinculados a este plan."
        )
    return redirect(url_for("planes.list_planes"))
