from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import Plan
from ..extensions import db
from sqlalchemy.exc import IntegrityError
from ..utils import admin_required
from ..utils_timezone import utcnow

planes_bp = Blueprint("planes", __name__)


def _parse_plan_duration(form, existing_plan=None):
    """Parse plan duration into stored config and display label."""
    raw_tipo = (form.get("duracion_tipo") or "").strip().lower()

    if not raw_tipo and existing_plan:
        raw_tipo = (getattr(existing_plan, "duracion_tipo", "") or "").strip().lower()

    if not raw_tipo:
        legacy = (form.get("duracion") or "").strip().lower()
        if any(token in legacy for token in ("día", "dias", "day")):
            raw_tipo = "dias"
        else:
            raw_tipo = "meses"

    if raw_tipo == "dias":
        raw_days = form.get("duracion_dias") or form.get("duracion_valor")
        if not raw_days and existing_plan:
            raw_days = getattr(existing_plan, "duracion_valor", None)
        try:
            duracion_valor = int(raw_days)
        except Exception:
            duracion_valor = 0
        if duracion_valor <= 0:
            return None, None, None, "Cantidad de días inválida"
        duracion_label = f"{duracion_valor} día" if duracion_valor == 1 else f"{duracion_valor} días"
        return "dias", duracion_valor, duracion_label, None

    raw_months = form.get("duracion_meses") or form.get("duracion_valor")
    if not raw_months and existing_plan:
        raw_months = getattr(existing_plan, "duracion_valor", None)
    try:
        duracion_valor = int(raw_months)
    except Exception:
        duracion_valor = 0
    if duracion_valor <= 0:
        return None, None, None, "Cantidad de meses inválida"

    duracion_map = {
        1: "Mensual",
        3: "Trimestral",
        6: "Semestral",
        12: "Anual",
    }
    duracion_label = duracion_map.get(duracion_valor, f"{duracion_valor} meses")
    return "meses", duracion_valor, duracion_label, None


def _plan_duration_defaults(plan=None):
    """Return template-friendly defaults for the duration controls."""
    if not plan:
        return {
            "duracion_tipo": "meses",
            "duracion_meses": 1,
            "duracion_dias": 1,
            "duracion_label": "Mensual",
        }

    duracion_tipo = (getattr(plan, "duracion_tipo", "") or "").strip().lower()
    duracion_valor = getattr(plan, "duracion_valor", None)
    duracion_label = getattr(plan, "duracion", None) or ""

    if duracion_tipo == "dias":
        try:
            duracion_dias = int(duracion_valor or 1)
        except Exception:
            duracion_dias = 1
        return {
            "duracion_tipo": "dias",
            "duracion_meses": 1,
            "duracion_dias": duracion_dias,
            "duracion_label": duracion_label or (f"{duracion_dias} día" if duracion_dias == 1 else f"{duracion_dias} días"),
        }

    try:
        duracion_meses = int(duracion_valor or 1)
    except Exception:
        duracion_meses = 1
    if not duracion_label:
        duracion_label = {
            1: "Mensual",
            3: "Trimestral",
            6: "Semestral",
            12: "Anual",
        }.get(duracion_meses, f"{duracion_meses} meses")
    return {
        "duracion_tipo": "meses",
        "duracion_meses": duracion_meses,
        "duracion_dias": 1,
        "duracion_label": duracion_label,
    }


def _plan_usage_defaults(plan=None):
    if not plan:
        return {
            "tipo_uso": "tiempo",
            "cupo_marcajes": "",
        }
    return {
        "tipo_uso": (getattr(plan, "tipo_uso", "tiempo") or "tiempo"),
        "cupo_marcajes": getattr(plan, "cupo_marcajes", "") or "",
    }


def _parse_plan_usage(form, existing_plan=None):
    tipo_uso = (form.get("tipo_uso") or "").strip().lower()
    if not tipo_uso and existing_plan:
        tipo_uso = (getattr(existing_plan, "tipo_uso", "") or "").strip().lower()
    if not tipo_uso:
        tipo_uso = "tiempo"

    raw_cupo = form.get("cupo_marcajes") or form.get("cupo")
    if not raw_cupo and existing_plan:
        raw_cupo = getattr(existing_plan, "cupo_marcajes", None)
    try:
        cupo_marcajes = int(raw_cupo) if raw_cupo not in (None, "") else None
    except Exception:
        return None, None, "Cupo de marcajes inválido"
    if tipo_uso != "asistencia_manual":
        cupo_marcajes = None
    elif cupo_marcajes is None or cupo_marcajes <= 0:
        return None, None, "El plan de asistencia manual requiere un cupo de marcajes"
    return tipo_uso, cupo_marcajes, None


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
        duracion_tipo, duracion_valor, duracion_label, error = _parse_plan_duration(request.form)
        if error:
            flash(error)
            return redirect(url_for("planes.create_plan"))
        tipo_uso, cupo_marcajes, error = _parse_plan_usage(request.form)
        if error:
            flash(error)
            return redirect(url_for("planes.create_plan"))
        p = Plan(
            nombre=nombre,
            descripcion=descripcion,
            duracion=duracion_label,
            duracion_tipo=duracion_tipo,
            duracion_valor=duracion_valor,
            tipo_uso=tipo_uso,
            cupo_marcajes=cupo_marcajes,
            precio=precio,
            tipo=tipo,
            estado=estado,
            fecha_creacion=utcnow(),
        )
        db.session.add(p)
        db.session.commit()
        flash("Plan creado")
        return redirect(url_for("planes.list_planes"))
    duration_defaults = _plan_duration_defaults()
    usage_defaults = _plan_usage_defaults()
    return render_template("planes/form.html", plan=None, **duration_defaults, **usage_defaults)


@planes_bp.route("/<int:plan_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_plan(plan_id):
    p = Plan.query.get_or_404(plan_id)
    if request.method == "POST":
        p.nombre = (request.form.get("nombre") or "").strip()
        p.descripcion = request.form.get("descripcion") or ""
        try:
            p.precio = float(request.form.get("precio") or 0)
        except Exception:
            p.precio = 0
        p.tipo = request.form.get("tipo") or p.tipo
        p.estado = request.form.get("estado") or p.estado
        duracion_tipo, duracion_valor, duracion_label, error = _parse_plan_duration(request.form, existing_plan=p)
        if error:
            flash(error)
            return redirect(url_for("planes.edit_plan", plan_id=p.id))
        tipo_uso, cupo_marcajes, error = _parse_plan_usage(request.form, existing_plan=p)
        if error:
            flash(error)
            return redirect(url_for("planes.edit_plan", plan_id=p.id))
        p.duracion_tipo = duracion_tipo
        p.duracion_valor = duracion_valor
        p.duracion = duracion_label
        p.tipo_uso = tipo_uso
        p.cupo_marcajes = cupo_marcajes
        db.session.commit()
        flash("Plan actualizado")
        return redirect(url_for("planes.list_planes"))
    duration_defaults = _plan_duration_defaults(p)
    usage_defaults = _plan_usage_defaults(p)
    return render_template("planes/form.html", plan=p, **duration_defaults, **usage_defaults)


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
