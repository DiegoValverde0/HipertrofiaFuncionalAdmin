from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from ..models import Usuario, Role, Sucursal
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required

usuarios_bp = Blueprint("usuarios", __name__)


@usuarios_bp.route("/")
@admin_required
def list_usuarios():
    usuarios = (
        Usuario.query.options(
            db.joinedload(Usuario.rol), db.joinedload(Usuario.sucursal)
        )
        .order_by(Usuario.id)
        .all()
    )
    return render_template("usuarios/list.html", usuarios=usuarios)


@usuarios_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_usuario():
    roles = Role.query.order_by(Role.nombre).all()
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    if request.method == "POST":
        nombre = request.form.get("nombre")
        correo = request.form.get("correo")
        contrasena = request.form.get("contrasena")
        rol_id = request.form.get("rol_id") or None
        sucursal_id = request.form.get("sucursal_id") or None
        hashed = generate_password_hash(contrasena) if contrasena else None
        # Convertir a None si el valor es una cadena vacía
        user = Usuario(
            nombre=nombre,
            correo=correo,
            contrasena=hashed,
            rol_id=rol_id,
            sucursal_id=sucursal_id if sucursal_id else None,
        )
        db.session.add(user)
        db.session.commit()
        flash("Usuario creado")
        return redirect(url_for("usuarios.list_usuarios"))
    return render_template(
        "usuarios/form.html", user=None, roles=roles, sucursales=sucursales
    )


@usuarios_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_usuario(user_id):
    user = Usuario.query.get_or_404(user_id)
    roles = Role.query.order_by(Role.nombre).all()
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    if request.method == "POST":
        user.nombre = request.form.get("nombre")
        user.correo = request.form.get("correo")
        # For privacy and security, do NOT allow administrators to change other users' passwords here.
        # Password changes must be done via the 'forgot password' email flow by the account owner.
        # If a password field was submitted, ignore it and inform the admin.
        if request.form.get("contrasena"):
            flash(
                'No está permitido cambiar contraseñas desde aquí. Pide al usuario usar "¿Olvidaste tu contraseña?" para restablecerla por correo.'
            )
        user.rol_id = request.form.get("rol_id") or None
        sucursal_id = request.form.get("sucursal_id") or None
        user.sucursal_id = sucursal_id if sucursal_id else None
        db.session.commit()
        flash("Usuario actualizado")
        return redirect(url_for("usuarios.list_usuarios"))
    return render_template(
        "usuarios/form.html", user=user, roles=roles, sucursales=sucursales
    )


@usuarios_bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_usuario(user_id):
    user = Usuario.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash("Usuario eliminado")
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se puede eliminar el usuario: existen registros dependientes vinculados (auditorías, ventas, etc.)."
        )
    return redirect(url_for("usuarios.list_usuarios"))
