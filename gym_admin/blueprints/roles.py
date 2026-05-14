from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import Role
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required

roles_bp = Blueprint("roles", __name__)


@roles_bp.route("/")
@admin_required
def list_roles():
    roles = Role.query.order_by(Role.nombre).all()
    return render_template("roles/list.html", roles=roles)


@roles_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_role():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        if not nombre:
            flash("Nombre requerido")
            return redirect(url_for("roles.create_role"))
        role = Role(nombre=nombre)
        db.session.add(role)
        db.session.commit()
        flash("Rol creado")
        return redirect(url_for("roles.list_roles"))
    return render_template("roles/form.html", role=None)


@roles_bp.route("/<int:role_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_role(role_id):
    role = Role.query.get_or_404(role_id)
    if request.method == "POST":
        role.nombre = request.form.get("nombre")
        db.session.commit()
        flash("Rol actualizado")
        return redirect(url_for("roles.list_roles"))
    return render_template("roles/form.html", role=role)


@roles_bp.route("/<int:role_id>/delete", methods=["POST"])
@admin_required
def delete_role(role_id):
    role = Role.query.get_or_404(role_id)
    try:
        db.session.delete(role)
        db.session.commit()
        flash("Rol eliminado")
    except IntegrityError:
        db.session.rollback()
        flash("No se puede eliminar el rol: existen usuarios asociados a este rol.")
    return redirect(url_for("roles.list_roles"))
