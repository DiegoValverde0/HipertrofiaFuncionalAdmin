from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    current_app,
    abort,
)
from flask_login import current_user
import hmac
from ..models import Membresia, Cliente, Plan, Promocion, EstadoMembresia
from ..services.membership_service import (
    compute_coverage,
    local_today,
    get_membership_status,
    create_membership,
    update_membership,
)
from ..services.attendance_service import (
    manual_attendance_summary,
    register_manual_attendance as register_manual_attendance_service,
)
from ..utils import (
    _compute_monto_total_for_membresia,
    admin_required,
    login_exempt,
    verify_sucursal_access,
    process_membership_states,
)
from ..extensions import db
from datetime import datetime, date
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

membresias_bp = Blueprint("membresias", __name__)


def _client_membership_status(cliente):
    """Return dict with keys: has (bool), soon (bool), last_id (int|None), last_fecha_fin (date|None), last_estado (int|None)
    Determines if the client's latest membership is considered 'valid' (active or paid "en espera").
    """
    if not cliente:
        return {
            "has": False,
            "soon": False,
            "last_id": None,
            "last_fecha_fin": None,
            "last_estado": None,
        }
    return get_membership_status(cliente.id)


@membresias_bp.route("/")
def list_membresias():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)
    tipo_uso = request.args.get("tipo_uso", type=str)
    query = Membresia.query

    if tipo_uso == "asistencia_manual":
        query = query.filter(Membresia.tipo_uso == "asistencia_manual")

    # --- LÓGICA DE FILTRADO POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and session.get("sucursal_id") != 0:
            sucursal_id = session.get("sucursal_id")

    if sucursal_id:
        query = query.filter(Membresia.sucursal_id == sucursal_id)

    if q:
        like = f"%{q}%"
        # buscar por cliente nombre/apellido
        query = query.join(Cliente).filter(
            or_(Cliente.nombre.ilike(like), Cliente.apellido.ilike(like))
        )
    pag = query.order_by(Membresia.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = pag.items
    # calcular pendiente por membresía para ocultar el botón de crear pago cuando no haya saldo
    pendientes = {}
    for m in items:
        try:
            monto = _compute_monto_total_for_membresia(m)
            pagado = 0
            for p in m.pagos:
                for h in p.historial:
                    try:
                        pagado += h.monto_pagado
                    except Exception:
                        pass
            restante = float(monto - pagado)
        except Exception:
            restante = 0.0
        pendientes[m.id] = restante

    # "Por vencer": activa, vence en <= 7 días y el cliente no tiene otra
    # membresía válida (activa o en espera pagada) que termine después.
    expiring = {}
    manual_summaries = {}
    coverage_by_client = {}
    for m in items:
        if m.cliente_id not in coverage_by_client:
            try:
                coverage_by_client[m.cliente_id] = compute_coverage(
                    m.cliente.membresias, horizon_days=7
                )["coverage_end"]
            except Exception:
                current_app.logger.exception(
                    "Error calculando cobertura del cliente %s", m.cliente_id
                )
                coverage_by_client[m.cliente_id] = None

        soon = False
        try:
            if m.is_activa and m.fecha_fin:
                days_left = (m.fecha_fin - local_today()).days
                coverage_end = coverage_by_client[m.cliente_id]
                renewed = coverage_end is not None and coverage_end > m.fecha_fin
                soon = days_left <= 7 and not renewed
        except Exception:
            soon = False
        expiring[m.id] = soon

        try:
            if m.is_manual_asistencia:
                manual_summaries[m.id] = manual_attendance_summary(m)
        except Exception:
            pass

    # Support returning only the table fragment for AJAX requests (partial=1) or X-Requested-With
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("partial") == "1"
    )
    if is_ajax:
        return render_template(
            "membresias/_table.html",
            pagination=pag,
            membresias=items,
            pendientes=pendientes,
            expiring=expiring,
            manual_summaries=manual_summaries,
            q=q,
            tipo_uso=tipo_uso,
            per_page=per_page,
        )
    return render_template(
        "membresias/list.html",
        pagination=pag,
        membresias=items,
        pendientes=pendientes,
        expiring=expiring,
        manual_summaries=manual_summaries,
        q=q,
        tipo_uso=tipo_uso,
        per_page=per_page,
    )


@membresias_bp.route("/admin/run_maintenance")
@login_exempt
def run_maintenance():
    """Endpoint unificado para mantenimiento del sistema.
    Permite acceso si:
    1. El usuario es administrador logueado.
    2. Se envía el ADMIN_TOKEN en la cabecera ``Authorization: Bearer <token>``
       (usado por el cron del VPS).
    """
    is_admin = bool(
        current_user
        and current_user.is_authenticated
        and getattr(current_user, "rol_id", None) == 1
    )

    conf_tok = current_app.config.get("ADMIN_TOKEN") or ""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    is_cron = bool(conf_tok and token) and hmac.compare_digest(token, conf_tok)

    if not is_admin and not is_cron:
        return jsonify({"success": False, "message": "Acceso denegado"}), 403

    try:
        from .notificaciones import create_birthday_notifications_for_week
        
        # 1. Procesar membresías
        process_membership_states()
        
        # 2. Procesar notificaciones de cumpleaños
        create_birthday_notifications_for_week()
        
        return jsonify({
            "success": True, 
            "message": "Mantenimiento completado",
            "method": "CRON" if is_cron else "Manual"
        }), 200
    except Exception as e:
        current_app.logger.exception("Error en mantenimiento unificado")
        return jsonify({"success": False, "error": str(e)}), 500


@membresias_bp.route("/search_clientes")
def search_clientes_for_membresia():
    # búsqueda en tiempo real para el formulario de membresías
    q = request.args.get("q", type=str) or ""
    if not q:
        return jsonify([])
    like = f"%{q}%"
    query = Cliente.query.filter(
        or_(
            Cliente.nombre.ilike(like),
            Cliente.apellido.ilike(like),
            Cliente.correo.ilike(like),
            Cliente.telefono.ilike(like),
        )
    )

    # --- FILTRAR CLIENTES POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and session.get("sucursal_id") != 0:
            sucursal_id = session.get("sucursal_id")

    if sucursal_id:
        query = query.filter(Cliente.sucursal_id == sucursal_id)

    rows = query.order_by(Cliente.nombre, Cliente.apellido).limit(30).all()
    result = []
    for r in rows:
        # Si falla el estado de un cliente se lista igual (sin estado) en vez de
        # romper toda la búsqueda.
        try:
            status = _client_membership_status(r)
        except Exception:
            current_app.logger.exception(
                "Error calculando estado de membresía del cliente %s", r.id
            )
            status = {}
        last_fecha = status.get("last_fecha_fin")
        result.append(
            {
                "id": r.id,
                "text": f"{r.nombre} {r.apellido} - {r.correo or r.telefono or ''}",
                "has_membresia": bool(status.get("has")),
                "soon": bool(status.get("soon")),
                "ultima_membresia": status.get("last_id"),
                "ultima_fecha_fin": str(last_fecha) if last_fecha else None,
                "ultima_estado": status.get("last_estado"),
                "sucursal_id": r.sucursal_id,
            }
        )
    return jsonify(result)


@membresias_bp.route("/preview-dates", methods=["GET"])
def preview_membership_dates():
    """API endpoint para preview de fechas sin crear membresía."""
    try:
        fecha_inicio = request.args.get("fecha_inicio", type=str)
        plan_id = request.args.get("plan_id", type=int)
        opcion = request.args.get("opcion", "new", type=str)
        cliente_id = request.args.get("cliente_id", type=int)
        
        if not fecha_inicio or not plan_id:
            return jsonify({'estado': 'error', 'mensaje': 'Parámetros requeridos'}), 400
        
        from ..services.membership_service import preview_membership_dates as preview_svc
        result = preview_svc(
            fecha_inicio=fecha_inicio,
            plan_id=plan_id,
            opcion=opcion,
            cliente_id=cliente_id
        )
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error in preview_membership_dates endpoint: {e}")
        return jsonify({'estado': 'error', 'mensaje': str(e)}), 500


@membresias_bp.route("/create", methods=["GET", "POST"])
def create_membresia():
    # si la creación viene desde el cliente, origin_cliente_id fija el cliente y bloquea cambios
    origin_cliente_id = request.args.get("cliente_id", type=int)
    cliente_id = origin_cliente_id or request.form.get("cliente_id", type=int)
    # sólo planes y promociones activos
    plans = Plan.query.filter(Plan.estado == "Activo").order_by(Plan.nombre).all()
    promos = (
        Promocion.query.filter(Promocion.estado == "Activo")
        .order_by(Promocion.nombre)
        .all()
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        errors = {}
        if origin_cliente_id:
            cliente_id = origin_cliente_id
        else:
            cliente_id = request.form.get("cliente_id", type=int)

        plan_id = request.form.get("plan_id", type=int)
        promocion_id = request.form.get("promocion_id", type=int) or None
        fecha_inicio_raw = request.form.get("fecha_inicio")
        fecha_fin_raw = request.form.get("fecha_fin")
        opcion = request.form.get("opcion") or "new"

        if not cliente_id:
            errors["cliente_id"] = "Cliente requerido"
        if not plan_id:
            errors["plan_id"] = "Plan requerido"

        if errors:
            if is_ajax:
                return jsonify({"success": False, "message": "Error de validación", "errors": errors}), 400
            else:
                for v in errors.values():
                    flash(v)
                return redirect(url_for("membresias.create_membresia"))

        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            if is_ajax:
                return jsonify({"success": False, "message": "Cliente no encontrado"}), 400
            flash("Cliente no encontrado")
            return redirect(url_for("membresias.create_membresia"))

        plan = db.session.get(Plan, plan_id)
        if not plan or getattr(plan, "estado", None) != "Activo":
            if is_ajax:
                return jsonify({"success": False, "message": "Plan no encontrado o inactivo"}), 400
            flash("Plan no encontrado o inactivo")
            return redirect(request.referrer or url_for("membresias.create_membresia"))

        if promocion_id:
            promo = db.session.get(Promocion, promocion_id)
            if not promo or getattr(promo, "estado", None) != "Activo":
                if is_ajax:
                    return jsonify({"success": False, "message": "Promoción no encontrada o inactiva"}), 400
                flash("Promoción no encontrada o inactiva")
                return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Parsear fecha_inicio
        try:
            fecha_inicio = (
                datetime.strptime(fecha_inicio_raw, "%Y-%m-%d").date()
                if fecha_inicio_raw
                else date.today()
            )
        except Exception:
            fecha_inicio = date.today()

        client_status = _client_membership_status(cliente)

        # Validación: si es "new" pero cliente tiene membresía activa, advertir (solo flash, no bloqueante)
        if opcion == "new" and client_status.get("has"):
            if not is_ajax:
                flash(
                    "Advertencia: el cliente ya posee una membresía activa o en espera (pagada). Revise antes de crear una nueva o use Extender."
                )

        # Validación: si es "extend", verificar que el cliente tenga membresías
        if opcion == "extend":
            if not cliente.membresias:
                if is_ajax:
                    return jsonify({"success": False, "message": "El cliente no posee membresía para extender"}), 400
                flash("El cliente no posee membresía para extender")
                return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Usar preview_membership_dates para obtener fecha_fin calculada correctamente
        from ..services.membership_service import preview_membership_dates as preview_svc
        preview = preview_svc(
            fecha_inicio=fecha_inicio,
            plan_id=plan_id,
            opcion=opcion,
            cliente_id=cliente_id,
        )

        if preview["estado"] != "valido":
            if is_ajax:
                return jsonify({"success": False, "message": f"Error calculando fechas: {preview.get('mensaje', 'Desconocido')}", "errors": {}}), 400
            flash(f"Error calculando fechas: {preview.get('mensaje', 'Desconocido')}")
            return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Parsear fecha_fin desde el preview
        try:
            fecha_fin = datetime.strptime(preview["fecha_fin"], "%Y-%m-%d").date()
        except Exception:
            if is_ajax:
                return jsonify({"success": False, "message": "Error al procesar fecha de fin calculada"}), 400
            flash("Error al procesar fecha de fin calculada")
            return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Sólo admins pueden sobrescribir fecha_fin
        if current_user and getattr(current_user, "rol_id", None) == 1:
            if fecha_fin_raw:
                try:
                    fecha_fin_override = datetime.strptime(fecha_fin_raw, "%Y-%m-%d").date()
                    # Validar que sea posterior a fecha_inicio
                    if fecha_fin_override > fecha_inicio:
                        fecha_fin = fecha_fin_override
                    else:
                        if is_ajax:
                            return jsonify({"success": False, "message": "Fecha fin manual debe ser posterior a fecha inicio"}), 400
                        flash("Fecha fin manual debe ser posterior a fecha inicio")
                        return redirect(request.referrer or url_for("membresias.create_membresia"))
                except Exception:
                    pass

        # Obtener sucursal
        suc_id = cliente.sucursal_id
        form_suc = request.form.get("cliente_sucursal_id", type=int)
        if not suc_id and form_suc:
            suc_id = form_suc
        if not suc_id:
            suc_id = session.get("sucursal_id")
        if not suc_id:
            if is_ajax:
                return jsonify({"success": False, "message": "No se puede crear membresía: el cliente no tiene sucursal y no hay sucursal seleccionada."}), 400
            flash("No se puede crear membresía: el cliente no tiene sucursal y no hay sucursal seleccionada.")
            return redirect(request.referrer or url_for("clientes.list_clientes"))

        # Obtener estado pendiente
        estado_obj = EstadoMembresia.query.filter(
            (EstadoMembresia.id == 1) | (EstadoMembresia.nombre.ilike("pendiente%"))
        ).first()
        if not estado_obj:
            if is_ajax:
                return jsonify({"success": False, "message": "No existe un estado de membresía pendiente configurado"}), 400
            flash("No existe un estado de membresía pendiente configurado")
            return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Crear membresía
        ok, new_membership_obj, err = create_membership(
            cliente_id=cliente_id,
            plan_id=plan_id,
            fecha_inicio=fecha_inicio,
            estado_id=estado_obj.id,
            sucursal_id=suc_id,
            promocion_id=promocion_id,
            fecha_fin=fecha_fin,
            tipo_creacion=opcion,
        )
        if not ok or not new_membership_obj:
            if is_ajax:
                return jsonify({"success": False, "message": err or "No se pudo crear la membresía"}), 400
            flash(err or "No se pudo crear la membresía")
            return redirect(request.referrer or url_for("membresias.create_membresia"))

        # Procesar estados de membresía
        try:
            process_membership_states(
                target_membresia_id=new_membership_obj.id, client_id=cliente_id
            )
        except Exception:
            current_app.logger.exception("Error post-create processing for membership")

        msg = f"Membresía #{new_membership_obj.id} creada exitosamente para el cliente {cliente.nombre} {cliente.apellido} (pendiente de pago)."
        if is_ajax:
            return jsonify({"success": True, "message": msg, "membresia_id": new_membership_obj.id})
        flash(msg)
        return redirect(url_for("membresias.list_membresias"))

    # GET
    cliente = db.session.get(Cliente, cliente_id) if cliente_id else None
    client_status = _client_membership_status(cliente) if cliente else None
    # default opcion: si el cliente tiene membresía válida, preseleccionar 'extend'
    default_opcion = "extend" if client_status and client_status.get("has") else "new"
    # compute default start date: next day after last_fecha_fin (if any), adjusted to next business day
    default_start_date = None
    try:
        if client_status and client_status.get("last_fecha_fin"):
            from datetime import timedelta

            lf = client_status.get("last_fecha_fin")
            nd = lf + timedelta(days=1)
            # ajustar fin de semana a lunes
            if nd.weekday() == 5:
                nd = nd + timedelta(days=2)
            if nd.weekday() == 6:
                nd = nd + timedelta(days=1)
            default_start_date = str(nd)
    except Exception:
        default_start_date = None

    if is_ajax:
        return render_template(
            "membresias/form_modal.html",
            cliente=cliente,
            plans=plans,
            promos=promos,
            origin_cliente_id=origin_cliente_id,
            client_status=client_status,
            default_opcion=default_opcion,
            default_start_date=default_start_date,
            is_edit=False,
        )

    return render_template(
        "membresias/form.html",
        cliente=cliente,
        plans=plans,
        promos=promos,
        origin_cliente_id=origin_cliente_id,
        client_status=client_status,
        default_opcion=default_opcion,
        default_start_date=default_start_date,
    )


@membresias_bp.route("/<int:membresia_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_membresia(membresia_id):
    m = Membresia.query.get_or_404(membresia_id)
    verify_sucursal_access(m)
    # En edición mostrar solo planes y promociones activas (igual que en creación)
    plans = Plan.query.filter(Plan.estado == "Activo").order_by(Plan.nombre).all()
    promos = (
        Promocion.query.filter(Promocion.estado == "Activo")
        .order_by(Promocion.nombre)
        .all()
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        updates = {}
        plan_id = request.form.get("plan_id", type=int)
        if plan_id:
            updates["plan_id"] = plan_id

        updates["promocion_id"] = request.form.get("promocion_id", type=int) or None

        try:
            updates["fecha_inicio"] = datetime.strptime(
                request.form.get("fecha_inicio"), "%Y-%m-%d"
            ).date()
        except Exception:
            pass
        try:
            updates["fecha_fin"] = datetime.strptime(
                request.form.get("fecha_fin"), "%Y-%m-%d"
            ).date()
        except Exception:
            pass

        # Sólo permitir que el usuario manualmente ponga Anulada o Inactiva.
        requested_estado = request.form.get("estado_id", type=int)
        
        try:
            from ..models import EstadoMembresia
            anulada_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("anulad%")).first()
            inactiva_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("inactiv%")).first()
            allowed_manual_states = []
            if anulada_estado: allowed_manual_states.append(anulada_estado.id)
            if inactiva_estado: allowed_manual_states.append(inactiva_estado.id)
        except Exception:
            allowed_manual_states = [3, 4]

        if requested_estado in allowed_manual_states:
            updates["estado_id"] = requested_estado
        else:
            if requested_estado is not None and not is_ajax:
                flash(
                    "Sólo puede marcar la membresía como Anulada o Inactiva manualmente. Otros estados son gestionados automáticamente."
                )

        ok, err = update_membership(m.id, **updates)
        if not ok:
            if is_ajax:
                return jsonify({"success": False, "message": err or "No se pudo actualizar la membresía"}), 400
            flash(err or "No se pudo actualizar la membresía")
            return redirect(
                request.referrer or url_for("membresias.edit_membresia", membresia_id=m.id)
            )

        if inactiva_estado and requested_estado == inactiva_estado.id:
            try:
                m.cliente.estado = "Inactivo"
                db.session.add(m.cliente)
                db.session.commit()
            except Exception:
                db.session.rollback()

        try:
            process_membership_states(target_membresia_id=m.id, client_id=m.cliente_id)
        except Exception:
            current_app.logger.exception("Error post-edit processing for membership")

        if is_ajax:
            return jsonify({"success": True, "message": "Membresía actualizada", "membresia_id": m.id})
        flash("Membresía actualizada")
        return redirect(url_for("membresias.list_membresias"))
    
    # GET - provide state IDs to the template
    try:
        from ..models import EstadoMembresia
        anulada_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("anulad%")).first()
        inactiva_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("inactiv%")).first()
        anulada_id = anulada_estado.id if anulada_estado else 3
        inactiva_id = inactiva_estado.id if inactiva_estado else 4
    except Exception:
        anulada_id = 3
        inactiva_id = 4
        
    if is_ajax:
        return render_template(
            "membresias/form_modal.html",
            membresia=m,
            plans=plans,
            promos=promos,
            anulada_id=anulada_id,
            inactiva_id=inactiva_id,
            is_edit=True,
        )

    return render_template(
        "membresias/form.html",
        membresia=m,
        plans=plans,
        promos=promos,
        anulada_id=anulada_id,
        inactiva_id=inactiva_id,
        is_edit=True,
    )


@membresias_bp.route("/<int:membresia_id>/delete", methods=["POST"])
@admin_required
def delete_membresia(membresia_id):
    m = Membresia.query.get_or_404(membresia_id)
    verify_sucursal_access(m)
    try:
        db.session.delete(m)
        db.session.commit()
        flash("Membresía eliminada")
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se puede eliminar la membresía: existen pagos u otros registros dependientes."
        )
    return redirect(url_for("membresias.list_membresias"))


@membresias_bp.route("/cliente/<int:cliente_id>")
def list_by_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    membresias = (
        Membresia.query.filter_by(cliente_id=cliente_id)
        .order_by(Membresia.fecha_inicio.desc())
        .all()
    )
    # calcular si cada membresía está vigente (resolver dinámicamente el/los ids de 'Activa')
    active_map = {}
    expiring = {}
    pendientes = {}
    try:
        from ..models import EstadoMembresia

        activa_objs = EstadoMembresia.query.filter(
            EstadoMembresia.nombre.ilike("activ%")
        ).all()
        activa_ids = set(
            [e.id for e in (activa_objs or []) if getattr(e, "id", None) is not None]
        )
    except Exception:
        activa_ids = {2}

    # compute pendings and expiring flag per membership
    try:
        from datetime import date as _d, timedelta

        horizon = _d.today() + timedelta(days=7)
        for m in membresias:
            active_map[m.id] = getattr(m, "estado_id", None) in activa_ids
            soon = False
            try:
                if (
                    getattr(m, "fecha_fin", None)
                    and getattr(m, "estado_id", None) in activa_ids
                    and m.fecha_fin <= horizon
                ):
                    soon = True
            except Exception:
                soon = False
            expiring[m.id] = soon
            # pendiente (monto restante)
            try:
                monto = _compute_monto_total_for_membresia(m)
                pagado = 0
                for p in m.pagos:
                    for h in p.historial:
                        try:
                            pagado += h.monto_pagado
                        except Exception:
                            pass
                restante = float(monto - pagado)
            except Exception:
                restante = 0.0
            pendientes[m.id] = restante
    except Exception:
        pass

    return render_template(
        "membresias/by_cliente.html",
        cliente=cliente,
        membresias=membresias,
        active_map=active_map,
        expiring=expiring,
        pendientes=pendientes,
    )


@membresias_bp.route("/<int:membresia_id>/info")
def membresia_info(membresia_id):
    m = Membresia.query.get_or_404(membresia_id)
    # calcular monto debido según plan/promoción (coincide con lógica de pagos)
    try:
        precio = float(m.plan.precio)
    except Exception:
        precio = 0.0
    descuento = 0.0
    if m.promocion and getattr(m.promocion, "descuento", None) is not None:
        try:
            descuento = float(m.promocion.descuento)
        except Exception:
            descuento = 0.0
    # interpretar descuento COMO MONTO FIJO a restar del precio
    try:
        monto = precio - float(descuento)
    except Exception:
        monto = precio
    if monto < 0:
        monto = 0.0

    return {
        "id": m.id,
        "cliente_id": m.cliente_id,
        "plan": m.plan.nombre if m.plan else None,
        "tipo_uso": getattr(m, "tipo_uso", None),
        "cupo_marcajes": getattr(m, "cupo_marcajes", None),
        "marcajes_usados": getattr(m, "marcajes_usados", 0),
        "promocion": m.promocion.nombre if m.promocion else None,
        "precio_base": precio,
        "descuento": descuento,
        "monto_calculado": round(monto, 2),
        "fecha_inicio": str(m.fecha_inicio),
        "fecha_fin": str(m.fecha_fin),
        "estado_id": m.estado_id,
    }


@membresias_bp.route("/<int:membresia_id>/detail")
def membresia_detail(membresia_id):
    # Render a detailed HTML fragment/modal with full membership information
    m = Membresia.query.get_or_404(membresia_id)
    # cliente info
    cliente = m.cliente
    cliente_fullname = (
        (cliente.nombre + " " + (cliente.apellido or "")).strip() if cliente else None
    )
    cliente_telefono = getattr(cliente, "telefono", None) if cliente else None
    # plan/promo/montos
    try:
        precio = (
            float(m.plan.precio)
            if m.plan and getattr(m.plan, "precio", None) is not None
            else 0.0
        )
    except Exception:
        precio = 0.0
    descuento = 0.0
    if m.promocion and getattr(m.promocion, "descuento", None) is not None:
        try:
            descuento = float(m.promocion.descuento)
        except Exception:
            descuento = 0.0
    try:
        monto = precio - float(descuento)
    except Exception:
        monto = precio
    if monto < 0:
        monto = 0.0
    monto = round(monto, 2)

    # pagos summary
    pagos_total = 0.0
    pagos_count = 0
    pagos_list = []
    try:
        for p in m.pagos:
            # aggregate historial amounts
            p_total = 0.0
            try:
                for h in p.historial:
                    try:
                        p_total += float(h.monto_pagado)
                    except Exception:
                        pass
            except Exception:
                # fallback if pagos store amount directly
                try:
                    p_total = float(getattr(p, "monto", 0) or 0)
                except Exception:
                    p_total = 0.0
            pagos_total += p_total
            pagos_count += 1
            pagos_list.append(
                {
                    "id": getattr(p, "id", None),
                    "monto": p_total,
                    "fecha": str(
                        getattr(p, "created_at", getattr(p, "fecha", None) or "")
                    ),
                    "detalle": getattr(p, "nota", None) or getattr(p, "detalle", None),
                }
            )
    except Exception:
        pagos_total = 0.0

    saldo = round(monto - pagos_total, 2)

    # estado nombre
    estado_nombre = (
        m.estado_membresia.nombre
        if getattr(m, "estado_membresia", None)
        else (m.estado_id or "-")
    )

    # plan info
    plan_nombre = m.plan.nombre if m.plan else None
    plan_duracion = getattr(m.plan, "duracion", None) if m.plan else None
    manual_attendance = manual_attendance_summary(m)
    manual_attendance["action_url"] = url_for("membresias.register_manual_attendance_route", membresia_id=m.id)

    # sucursal nombre (best-effort)
    sucursal_nombre = None
    try:
        suc = getattr(m, "sucursal", None)
        if suc and getattr(suc, "nombre", None):
            sucursal_nombre = suc.nombre
    except Exception:
        sucursal_nombre = None

    from datetime import datetime as _dt

    generated_at = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    # representación de descuento como monto fijo en moneda
    try:
        descuento_val = float(descuento)
        descuento_repr = "$" + ("{:.2f}".format(descuento_val))
    except Exception:
        descuento_repr = "$0.00"

    # generate a time-limited tokenized URL for public PDF access (default 7 days)
    try:
        s = URLSafeTimedSerializer(
            current_app.config.get("SECRET_KEY")
            or current_app.config.get("SECRET_KEY", ""),
            salt="memb-pdf",
        )
        token = s.dumps({"id": m.id})
        pdf_url = url_for("membresias.membresia_pdf_token", token=token, _external=True)
    except Exception:
        pdf_url = url_for("membresias.membresia_pdf", membresia_id=m.id)

    return render_template(
        "membresias/_detail.html",
        m=m,
        cliente_fullname=cliente_fullname,
        cliente_telefono=cliente_telefono,
        precio_base=precio,
        descuento=descuento,
        descuento_repr=descuento_repr,
        monto_calculado=monto,
        pagos_total=pagos_total,
        pagos_count=pagos_count,
        pagos_list=pagos_list,
        saldo=saldo,
        estado_nombre=estado_nombre,
        plan_nombre=plan_nombre,
        plan_duracion=plan_duracion,
        manual_attendance=manual_attendance,
        sucursal_nombre=sucursal_nombre,
        generated_at=generated_at,
        pdf_url=pdf_url,
    )


@membresias_bp.route("/<int:membresia_id>/marcajes/manual", methods=["POST"])
def register_manual_attendance_route(membresia_id):
    m = Membresia.query.get_or_404(membresia_id)
    verify_sucursal_access(m)

    observacion = (request.form.get("observacion") or "").strip() or None
    usuario_id = getattr(current_user, "id", None) if current_user and current_user.is_authenticated else None
    sucursal_id = getattr(current_user, "sucursal_id", None) if current_user and current_user.is_authenticated else None

    ok, payload, err = register_manual_attendance_service(
        membresia_id=m.id,
        usuario_id=usuario_id,
        sucursal_id=sucursal_id,
        observacion=observacion,
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if ok:
        message = "Marcaje manual registrado exitosamente."
        if payload and payload.get("cupo"):
            restantes = payload.get("restantes", 0)
            message = f"Marcaje exitoso. Quedan {restantes} clases restantes."
        if is_ajax:
            return jsonify({"success": True, "message": message, "attendance": payload})
        flash(message)
        return redirect(request.referrer or url_for("membresias.list_membresias"))

    if is_ajax:
        return jsonify({"success": False, "message": err or "No se pudo registrar el marcaje", "attendance": payload}), 400
    flash(err or "No se pudo registrar el marcaje")
    return redirect(request.referrer or url_for("membresias.list_membresias"))


@membresias_bp.route("/<int:membresia_id>/pdf")
def membresia_pdf(membresia_id):
    # Endpoint that returns a PDF of the membership receipt if WeasyPrint is available,
    # otherwise returns a printable HTML page.
    m = Membresia.query.get_or_404(membresia_id)
    # reuse same data preparation as in detail
    cliente = m.cliente
    cliente_fullname = (
        (cliente.nombre + " " + (cliente.apellido or "")).strip() if cliente else None
    )
    cliente_telefono = getattr(cliente, "telefono", None) if cliente else None
    try:
        precio = (
            float(m.plan.precio)
            if m.plan and getattr(m.plan, "precio", None) is not None
            else 0.0
        )
    except Exception:
        precio = 0.0
    descuento = 0.0
    if m.promocion and getattr(m.promocion, "descuento", None) is not None:
        try:
            descuento = float(m.promocion.descuento)
        except Exception:
            descuento = 0.0
    if descuento > 1:
        monto = precio * (100.0 - descuento) / 100.0
    else:
        monto = precio * (1.0 - descuento)
    monto = round(monto, 2)

    pagos_total = 0.0
    pagos_count = 0
    pagos_list = []
    try:
        for p in m.pagos:
            p_total = 0.0
            try:
                for h in p.historial:
                    try:
                        p_total += float(h.monto_pagado)
                    except Exception:
                        pass
            except Exception:
                try:
                    p_total = float(getattr(p, "monto", 0) or 0)
                except Exception:
                    p_total = 0.0
            pagos_total += p_total
            pagos_count += 1
            pagos_list.append(
                {
                    "id": getattr(p, "id", None),
                    "monto": p_total,
                    "fecha": str(
                        getattr(p, "created_at", getattr(p, "fecha", None) or "")
                    ),
                    "detalle": getattr(p, "nota", None) or getattr(p, "detalle", None),
                }
            )
    except Exception:
        pagos_total = 0.0

    saldo = round(monto - pagos_total, 2)
    estado_nombre = (
        m.estado_membresia.nombre
        if getattr(m, "estado_membresia", None)
        else (m.estado_id or "-")
    )
    plan_nombre = m.plan.nombre if m.plan else None
    plan_duracion = getattr(m.plan, "duracion", None) if m.plan else None
    sucursal_nombre = None
    try:
        suc = getattr(m, "sucursal", None)
        if suc and getattr(suc, "nombre", None):
            sucursal_nombre = suc.nombre
    except Exception:
        sucursal_nombre = None
    from datetime import datetime as _dt

    generated_at = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    descuento_repr = (
        (str(int(descuento)) + "%")
        if descuento > 1
        else (str(round(descuento * 100, 2)) + "%") if descuento else "0%"
    )

    # Render printable HTML
    html = render_template(
        "membresias/_detail_print.html",
        m=m,
        cliente_fullname=cliente_fullname,
        cliente_telefono=cliente_telefono,
        precio_base=precio,
        descuento=descuento,
        descuento_repr=descuento_repr,
        monto_calculado=monto,
        pagos_total=pagos_total,
        pagos_count=pagos_count,
        pagos_list=pagos_list,
        saldo=saldo,
        estado_nombre=estado_nombre,
        plan_nombre=plan_nombre,
        plan_duracion=plan_duracion,
        sucursal_nombre=sucursal_nombre,
        generated_at=generated_at,
    )

    # Try to produce PDF via WeasyPrint if available
    try:
        # dynamic import to avoid hard dependency at module import time
        import importlib

        weasy = importlib.import_module("weasyprint")
        HTML = getattr(weasy, "HTML")
        pdf = HTML(string=html, base_url=request.url_root).write_pdf()
        from flask import Response

        resp = Response(pdf, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = (
            f"attachment; filename=membresia-{m.id}.pdf"
        )
        return resp
    except Exception:
        # Fallback: return the HTML so the browser can print/save it
        return html


@membresias_bp.route("/pdf/<token>")
def membresia_pdf_token(token):
    # Public, token-based access to a membership pdf/html. Token is time-limited.
    try:
        s = URLSafeTimedSerializer(
            current_app.config.get("SECRET_KEY")
            or current_app.config.get("SECRET_KEY", ""),
            salt="memb-pdf",
        )
        data = s.loads(
            token, max_age=current_app.config.get("PDF_TOKEN_MAX_AGE", 60 * 60 * 24 * 7)
        )
        memb_id = data.get("id") if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired):
        memb_id = None
    except Exception:
        memb_id = None
    if not memb_id:
        abort(404)
    # delegate to the normal renderer by reusing the code above: fetch membership and render printable html/pdf
    m = Membresia.query.get_or_404(memb_id)
    # prepare same data as membersia_pdf does (duplicating a bit for clarity)
    cliente = m.cliente
    cliente_fullname = (
        (cliente.nombre + " " + (cliente.apellido or "")).strip() if cliente else None
    )
    cliente_telefono = getattr(cliente, "telefono", None) if cliente else None
    try:
        precio = (
            float(m.plan.precio)
            if m.plan and getattr(m.plan, "precio", None) is not None
            else 0.0
        )
    except Exception:
        precio = 0.0
    descuento = 0.0
    if m.promocion and getattr(m.promocion, "descuento", None) is not None:
        try:
            descuento = float(m.promocion.descuento)
        except Exception:
            descuento = 0.0
    if descuento > 1:
        monto = precio * (100.0 - descuento) / 100.0
    else:
        monto = precio * (1.0 - descuento)
    monto = round(monto, 2)
    pagos_total = 0.0
    pagos_count = 0
    try:
        pagos_list = []
        for p in m.pagos:
            p_total = 0.0
            try:
                for h in p.historial:
                    try:
                        p_total += float(h.monto_pagado)
                    except Exception:
                        pass
            except Exception:
                try:
                    p_total = float(getattr(p, "monto", 0) or 0)
                except Exception:
                    p_total = 0.0
            pagos_total += p_total
            pagos_count += 1
            pagos_list.append(
                {
                    "id": getattr(p, "id", None),
                    "monto": p_total,
                    "fecha": str(
                        getattr(p, "created_at", getattr(p, "fecha", None) or "")
                    ),
                    "detalle": getattr(p, "nota", None) or getattr(p, "detalle", None),
                }
            )
    except Exception:
        pagos_total = 0.0
        pagos_list = []
    saldo = round(monto - pagos_total, 2)
    estado_nombre = (
        m.estado_membresia.nombre
        if getattr(m, "estado_membresia", None)
        else (m.estado_id or "-")
    )
    plan_nombre = m.plan.nombre if m.plan else None
    plan_duracion = getattr(m.plan, "duracion", None) if m.plan else None
    from datetime import datetime as _dt

    generated_at = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    descuento_repr = (
        (str(int(descuento)) + "%")
        if descuento > 1
        else (str(round(descuento * 100, 2)) + "%") if descuento else "0%"
    )
    # If ?download=1 present, try to generate PDF and return as attachment. Otherwise render a public HTML page
    html = render_template(
        "membresias/_detail_print.html",
        m=m,
        cliente_fullname=cliente_fullname,
        cliente_telefono=cliente_telefono,
        precio_base=precio,
        descuento=descuento,
        descuento_repr=descuento_repr,
        monto_calculado=monto,
        pagos_total=pagos_total,
        pagos_count=pagos_count,
        pagos_list=pagos_list,
        saldo=saldo,
        estado_nombre=estado_nombre,
        plan_nombre=plan_nombre,
        plan_duracion=plan_duracion,
        sucursal_nombre=None,
        generated_at=generated_at,
    )

    download = request.args.get("download")
    if download:
        try:
            import importlib

            weasy = importlib.import_module("weasyprint")
            HTML = getattr(weasy, "HTML")
            pdf = HTML(string=html, base_url=request.url_root).write_pdf()
            from flask import Response

            resp = Response(pdf, mimetype="application/pdf")
            resp.headers["Content-Disposition"] = (
                f"attachment; filename=membresia-{m.id}.pdf"
            )
            return resp
        except Exception:
            # if PDF generation fails, still return HTML so the user can print/save manually
            return html

    # render public HTML view with download and print buttons
    return render_template(
        "membresias/_public_detail.html",
        m=m,
        token=token,
        cliente_fullname=cliente_fullname,
        cliente_telefono=cliente_telefono,
        precio_base=precio,
        descuento=descuento,
        descuento_repr=descuento_repr,
        monto_calculado=monto,
        pagos_total=pagos_total,
        pagos_count=pagos_count,
        pagos_list=pagos_list,
        saldo=saldo,
        estado_nombre=estado_nombre,
        plan_nombre=plan_nombre,
        plan_duracion=plan_duracion,
        sucursal_nombre=None,
        generated_at=generated_at,
    )
