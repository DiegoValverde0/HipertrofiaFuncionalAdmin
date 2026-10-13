from ..utils import admin_required
from flask import (
    Blueprint,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
    session,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.local import LocalProxy
from ..models import Usuario
from ..extensions import db, limiter
from ..services.auth_service import send_email, trigger_post_login_tasks
import secrets
import string

try:
    from flask_login import login_user, logout_user, current_user
except Exception:
    # fallback ligero usando session si flask-login no está instalado
    def login_user(user):
        try:
            session["user_id"] = int(getattr(user, "id"))
        except Exception:
            session["user_id"] = getattr(user, "id")

    def logout_user():
        session.pop("user_id", None)

    def _get_current_user():
        try:
            from ..models import Usuario

            uid = session.get("user_id")
            if uid:
                u = db.session.get(Usuario, int(uid))
                if u:
                    return u
        except Exception:
            pass

        class _Anon:
            is_authenticated = False
            nombre = None
            correo = None

        return _Anon()

    current_user = LocalProxy(_get_current_user)

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


def _mark_session_permanent():
    session.permanent = True


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute") if limiter else lambda f: f
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        correo = (request.form.get("correo") or "").strip().lower()
        contrasena = (request.form.get("contrasena") or "").strip()
        user = Usuario.query.filter_by(correo=correo).first()
        if not user:
            flash("Credenciales inválidas")
            return redirect(url_for("auth.login"))

        # diagnostic info (no sensitive data)
        try:
            current_app.logger.debug(
                f"Auth attempt for email={correo} user_id={getattr(user, 'id', None)} has_password={bool(getattr(user, 'contrasena', None))}"
            )
        except Exception:
            pass

        hashed_pw = user.contrasena or ""

        # Primero intentamos el check estándar (hashed). Aislamos la verificación
        # de contraseña de las tareas posteriores para evitar que una excepción
        # en tareas pos-login provoque que termine ejecutándose el mensaje de
        # 'Credenciales inválidas' tras un login exitoso.
        hashed_ok = False
        try:
            if hashed_pw and check_password_hash(hashed_pw, contrasena):
                hashed_ok = True
        except Exception:
            try:
                current_app.logger.debug(
                    "Stored password not a valid hash, falling back to plaintext compare"
                )
            except Exception:
                pass

        # Si la verificación con hash fue correcta, iniciar sesión y ejecutar
        # tareas de pos-login de forma segura (cada una con su manejo de errores).
        if hashed_ok:
            _mark_session_permanent()
            login_user(user)
            if user.sucursal_id:
                session["sucursal_id"] = user.sucursal_id
            flash("Bienvenido")

            # Trigger post-login tasks via service (runs in background)
            try:
                trigger_post_login_tasks(user, background=True)
            except Exception:
                try:
                    current_app.logger.exception("Error triggering post-login tasks")
                except Exception:
                    pass
            return redirect(url_for("index"))

        # Si falla el hash-check, comprobamos si la contraseña almacenada era texto plano (legacy)
        if hashed_pw and hashed_pw == contrasena:
            try:
                user.contrasena = generate_password_hash(contrasena)
                db.session.commit()
            except Exception:
                db.session.rollback()
            _mark_session_permanent()
            login_user(user)
            if user.sucursal_id:
                session["sucursal_id"] = user.sucursal_id

            # Trigger post-login tasks via service (runs in background)
            try:
                trigger_post_login_tasks(user, background=True)
            except Exception:
                try:
                    current_app.logger.exception(
                        "Error triggering post-login tasks on fallback login"
                    )
                except Exception:
                    pass
            flash("Bienvenido (contraseña actualizada)")
            return redirect(url_for("index"))

        flash("Credenciales inválidas")
        return redirect(url_for("auth.login"))
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if logout_user is None:
        flash("Funcionalidad de autenticación no disponible (flask-login no instalado)")
        return redirect(url_for("index"))
    logout_user()
    flash("Sesión cerrada")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
@admin_required
def register():
    # admin_required ya verifica autenticación; no redirigir al admin
    # (este endpoint es para que admins creen cuentas nuevas)
    if request.method == "POST":
        nombre = request.form.get("nombre")
        correo = (request.form.get("correo") or "").strip().lower()
        contrasena = (request.form.get("contrasena") or "").strip()
        if not correo or not contrasena:
            flash("Correo y contraseña requeridos")
            return redirect(url_for("auth.register"))
        if Usuario.query.filter_by(correo=correo).first():
            flash("Correo ya registrado")
            return redirect(url_for("auth.register"))
        hashed = generate_password_hash(contrasena)
        user = Usuario(nombre=nombre, correo=correo, contrasena=hashed)
        db.session.add(user)
        db.session.commit()
        flash("Registro exitoso. Por favor inicia sesión.")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


def generate_temp_password(length=12):
    """Genera una contraseña temporal segura usando secrets (criptográficamente seguro)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@auth_bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("3/minute") if limiter else lambda f: f
def forgot():
    if request.method == "POST":
        correo = (request.form.get("correo") or "").strip().lower()
        if not correo:
            flash("Introduce tu correo")
            return redirect(url_for("auth.forgot"))
        user = Usuario.query.filter_by(correo=correo).first()
        if not user:
            flash("No existe usuario con ese correo")
            return redirect(url_for("auth.forgot"))
        new_pw = generate_temp_password(12)
        try:
            user.contrasena = generate_password_hash(new_pw)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Error al generar nueva contraseña, intenta nuevamente")
            return redirect(url_for("auth.forgot"))

        # Determinar dirección de correo a la que enviar la nueva contraseña.
        # Si el valor almacenado parece una dirección (contiene '@' y un dominio), usarla.
        # Si no, concatenar con @gmail.com (comportamiento solicitado: "usuario -> usuario@gmail.com").
        raw = (user.correo or "").strip()
        dest_email = None
        if raw:
            # heurística simple: si contiene '@' y la parte de dominio tiene al menos un punto, lo consideramos un email
            try:
                domain = raw.split("@", 1)[1]
            except Exception:
                domain = ""
            if "@" in raw and domain and ("." in domain):
                dest_email = raw
            else:
                dest_email = raw + "@gmail.com"
        else:
            # si no hay valor en user.correo, intentar usar nombre como fallback
            nombre_val = (getattr(user, "nombre", "") or "").strip()
            if nombre_val:
                dest_email = nombre_val + "@gmail.com"

        if not dest_email:
            try:
                current_app.logger.warning(
                    "Forgot password: no email address available for user id=%s",
                    getattr(user, "id", None),
                )
            except Exception:
                pass
            flash(
                "No hay una dirección de correo asociada a este usuario; contacta al administrador"
            )
            return redirect(url_for("auth.forgot"))

        subject = "Nueva contraseña - Gym Admin"
        body = f"Tu nueva contraseña es: {new_pw}\nCámbiala al iniciar sesión."
        ok = send_email(dest_email, subject, body)
        if ok:
            # informar al usuario que se envió el correo (no mostrar la contraseña)
            flash(f"Se envió la nueva contraseña por correo a {dest_email}")
        else:
            # No mostrar la contraseña en ningún entorno. Informar al usuario y registrar el fallo.
            try:
                current_app.logger.warning(
                    "Forgot password: email delivery failed for %s", dest_email
                )
            except Exception:
                pass
            flash("No se pudo enviar el correo. Contacta al administrador")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@auth_bp.route("/whoami")
def whoami():
    # Ruta de diagnóstico: SOLO disponible en modo debug
    if not current_app.debug:
        abort(404)
    try:
        from flask import session as _session

        cu = current_user
        repr_user = None
        try:
            repr_user = dict(
                id=getattr(cu, "id", None),
                nombre=getattr(cu, "nombre", None),
                correo=getattr(cu, "correo", None),
                is_authenticated=getattr(cu, "is_authenticated", None),
            )
        except Exception:
            repr_user = str(cu)
        return jsonify(
            dict(session_user_id=_session.get("user_id"), current_user=repr_user)
        )
    except Exception:
        return jsonify(dict(error="no-diagnostic-available"))


@auth_bp.route("/profile", methods=["GET", "POST"])
def profile():
    # Perfil del usuario autenticado: mostrar datos y permitir cambio de contraseña propio
    try:
        if not (current_user and getattr(current_user, "is_authenticated", False)):
            return redirect(url_for("auth.login"))
    except Exception:
        return redirect(url_for("auth.login"))

    # reload user from DB to have up-to-date object (supports LocalProxy fallback)
    try:
        user = db.session.get(Usuario, int(getattr(current_user, "id")))
    except Exception:
        user = current_user

    if request.method == "POST":
        current_pw = (request.form.get("current_password") or "").strip()
        new_pw = (request.form.get("new_password") or "").strip()
        confirm_pw = (request.form.get("confirm_password") or "").strip()

        if not current_pw or not new_pw or not confirm_pw:
            flash("Todos los campos son obligatorios")
            return redirect(url_for("auth.profile"))

        if new_pw != confirm_pw:
            flash("La nueva contraseña y la confirmación no coinciden")
            return redirect(url_for("auth.profile"))

        # Validate current password
        stored = getattr(user, "contrasena", "") or ""
        valid = False
        try:
            if stored and check_password_hash(stored, current_pw):
                valid = True
            elif stored and stored == current_pw:
                # legacy plaintext: accept and upgrade
                valid = True
        except Exception:
            pass

        if not valid:
            flash("Contraseña actual inválida")
            return redirect(url_for("auth.profile"))

        # All good: update password hash
        try:
            user.contrasena = generate_password_hash(new_pw)
            db.session.commit()
            flash("Contraseña actualizada correctamente")
        except Exception:
            db.session.rollback()
            flash("Error al actualizar la contraseña")
        return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html", user=user)
