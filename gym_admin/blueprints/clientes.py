from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    g,
)
from ..models import Cliente, Sucursal
from ..services.client_service import (
    create_client,
    update_client,
    delete_client,
    compute_age,
)
from flask_login import current_user
from ..utils import (
    _compute_monto_total_for_membresia,
    admin_required,
    api_key_required,
    verify_sucursal_access,
)
from sqlalchemy import or_
from datetime import date, datetime, timedelta

clientes_bp = Blueprint("clientes", __name__)


def _compute_client_flags_global(clients_list, horizon_days=7, sucursal_id=None):
    """Compute has_active, soon and fecha_fin flags for a list of Cliente objects.
    Uses the same business rules as the per-page helper in the template (estado codes and payment checks).
    Returns a dict mapping cliente.id -> flags dict."""
    from datetime import date as _d, timedelta
    from decimal import Decimal

    flags = {}
    try:
        horizon = _d.today() + timedelta(days=horizon_days)
        for c in clients_list:
            has_active = False
            soon = False
            soon_date = None
            try:
                candidates = []
                # Filtrar membresías por sucursal si se proporciona el ID
                membresias_a_revisar = c.membresias
                if sucursal_id:
                    membresias_a_revisar = [
                        m for m in c.membresias if m.sucursal_id == sucursal_id
                    ]

                for m in membresias_a_revisar:
                    getattr(m, "estado_id", None)
                    if not getattr(m, "fecha_fin", None):
                        continue
                    if m.is_activa:
                        candidates.append(m)
                        continue
                    if m.is_en_espera:
                        try:
                            total_due = _compute_monto_total_for_membresia(m)
                        except Exception:
                            total_due = None
                        if total_due and total_due > 0:
                            total_paid = Decimal("0")
                            try:
                                for p in m.pagos:
                                    for h in p.historial:
                                        try:
                                            total_paid += Decimal(h.monto_pagado)
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                            if total_paid >= total_due:
                                candidates.append(m)

                if candidates:
                    m_sorted = sorted(candidates, key=lambda mm: mm.fecha_fin)
                    first = m_sorted[0]
                    has_active = True
                    if first.fecha_fin <= horizon:
                        soon = True
                        soon_date = first.fecha_fin
                else:
                    has_active = False
            except Exception:
                has_active = False
                soon = False
                soon_date = None
            flags[c.id] = {
                "has_active": has_active,
                "soon": soon,
                "fecha_fin": str(soon_date) if soon_date else None,
            }
    except Exception:
        return {}
    return flags


@clientes_bp.route("/")
def list_clientes():
    # filtros
    q = request.args.get("q", type=str)
    estado = request.args.get("estado")
    tipo = request.args.get("tipo")

    # --- LÓGICA DE FILTRADO POR SUCURSAL UNIFICADA ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and session.get("sucursal_id") != 0:
            # Usar la sucursal de la sesión solo si el usuario no tiene una asignada
            sucursal_id = int(session.get("sucursal_id"))

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    # support `expiring` filter: number of days from today to consider memberships that will expire
    expiring_days = request.args.get("expiring", type=int)
    expiring_client_ids = None
    if expiring_days:
        try:
            # Build a base client query applying the same search/estado/tipo/sucursal filters
            base_q = Cliente.query
            if q:
                like = f"%{q}%"
                base_q = base_q.filter(
                    or_(
                        Cliente.nombre.ilike(like),
                        Cliente.apellido.ilike(like),
                        Cliente.correo.ilike(like),
                        Cliente.telefono.ilike(like),
                    )
                )
            if estado:
                base_q = base_q.filter_by(estado=estado)
            if tipo:
                base_q = base_q.filter_by(tipo_cliente=tipo)
            if sucursal_id and sucursal_id > 0:
                base_q = base_q.filter_by(sucursal_id=sucursal_id)

            # Fetch candidate clients (we need their memberships to compute flags)
            candidate_clients = base_q.all()
            # compute flags using the same business rules, respetando la sucursal
            flags = _compute_client_flags_global(
                candidate_clients, horizon_days=expiring_days, sucursal_id=sucursal_id
            )
            expiring_client_ids = [cid for cid, f in flags.items() if f.get("soon")]
        except Exception:
            expiring_client_ids = None

    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.apellido.ilike(like),
                Cliente.correo.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )
    if estado:
        query = query.filter_by(estado=estado)
    if tipo:
        query = query.filter_by(tipo_cliente=tipo)
    # Si sucursal_id es None -> mostrar todos (incluyendo NULL), si tiene valor >0 -> filtrar
    if sucursal_id and sucursal_id > 0:
        query = query.filter_by(sucursal_id=sucursal_id)

    # apply expiring client filter if requested
    if expiring_days is not None:
        if expiring_client_ids is None:
            # something went wrong computing ids; return no results
            query = Cliente.query.filter(Cliente.id == None)
        else:
            if len(expiring_client_ids) == 0:
                query = Cliente.query.filter(Cliente.id == None)
            else:
                query = query.filter(Cliente.id.in_(expiring_client_ids))

    pag = query.order_by(Cliente.nombre.asc(), Cliente.apellido.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    from datetime import date as _date

    items = pag.items

    # compute flags helper (extracted to reuse for AJAX partials)
    def _compute_client_flags(items_list):
        from datetime import date as _d, timedelta
        from decimal import Decimal

        flags = {}
        try:
            horizon = _d.today() + timedelta(days=7)
            for c in items_list:
                has_active = False
                soon = False
                soon_date = None
                has_manual = False
                manual_membresia_id = None

                try:
                    candidates = []
                    from ..services.attendance_service import manual_attendance_summary
                    for m in c.membresias:
                        getattr(m, "estado_id", None)
                        
                        # Check manual attendance
                        if getattr(m, "is_manual_asistencia", False):
                            summary = manual_attendance_summary(m)
                            if summary.get("puede_marcar"):
                                has_manual = True
                                manual_membresia_id = m.id
                        
                        if not getattr(m, "fecha_fin", None):
                            continue
                        if m.is_activa:
                            candidates.append(m)
                            continue
                        if m.is_en_espera:
                            try:
                                total_due = _compute_monto_total_for_membresia(m)
                            except Exception:
                                total_due = None
                            if total_due and total_due > 0:
                                total_paid = Decimal("0")
                                try:
                                    for p in m.pagos:
                                        for h in p.historial:
                                            try:
                                                total_paid += Decimal(h.monto_pagado)
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                if total_paid >= total_due:
                                    candidates.append(m)

                    if candidates:
                        m_sorted = sorted(candidates, key=lambda mm: mm.fecha_fin)
                        first = m_sorted[0]
                        has_active = True
                        if first.fecha_fin <= horizon:
                            soon = True
                            soon_date = first.fecha_fin
                    else:
                        has_active = False
                except Exception:
                    has_active = False
                    soon = False
                    soon_date = None
                    has_manual = False
                    manual_membresia_id = None
                flags[c.id] = {
                    "has_active": has_active,
                    "soon": soon,
                    "fecha_fin": str(soon_date) if soon_date else None,
                    "has_manual": has_manual,
                    "manual_membresia_id": manual_membresia_id,
                }
        except Exception:
            pass
        return flags

    client_flags = _compute_client_flags(items)

    # pass current filter params so the template can reflect selected values
    return render_template(
        "clientes/list.html",
        pagination=pag,
        clientes=items,
        today=_date.today(),
        reminders=client_flags,
        q=q,
        estado=estado,
        tipo=tipo,
        per_page=per_page,
        page=page,
        expiring_days=expiring_days,
    )


@clientes_bp.route("/<int:cliente_id>")
def view_cliente(cliente_id):
    # cargar cliente con relaciones relevantes para detalle
    c = Cliente.query.get_or_404(cliente_id)
    # force load relaciones (membresias, pagos, historiales) para evitar consultas en la plantilla
    membresias = []
    try:
        for m in c.membresias:
            pagos = []
            try:
                for p in m.pagos:
                    historial = list(p.historial)
                    pagos.append({"pago": p, "historial": historial})
            except Exception:
                pagos = []
            membresias.append({"membresia": m, "pagos": pagos})
    except Exception:
        membresias = []
    from datetime import date as _date

    return render_template(
        "clientes/detail.html", cliente=c, membresias=membresias, today=_date.today()
    )


@clientes_bp.route("/search")
def search_clientes():
    # endpoint JSON para búsqueda en tiempo real
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
    # --- FILTRAR BÚSQUEDA POR SUCURSAL ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and session.get("sucursal_id") != 0:
            sucursal_id = session.get("sucursal_id")

    if sucursal_id:
        query = query.filter(Cliente.sucursal_id == sucursal_id)

    rows = query.limit(50).all()
    result = [
        {"id": r.id, "text": f"{r.nombre} {r.apellido} - {r.correo or r.telefono}"}
        for r in rows
    ]
    return jsonify(result)


@clientes_bp.route("/table")
def clientes_table():
    # devuelve la tabla renderizada (partial) para recarga por AJAX
    # Reusar la misma lógica de filtros que list_clientes
    q = request.args.get("q", type=str)
    estado = request.args.get("estado")
    tipo = request.args.get("tipo")
    # page y per_page son incluidos para la renderización
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    # --- LÓGICA DE FILTRADO POR SUCURSAL UNIFICADA (igual que list_clientes) ---
    sucursal_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif "sucursal_id" in session and session.get("sucursal_id") != 0:
            # Usar la sucursal de la sesión solo si el usuario no tiene una asignada
            sucursal_id = int(session.get("sucursal_id"))

    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.apellido.ilike(like),
                Cliente.correo.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )
    if estado:
        query = query.filter_by(estado=estado)
    if tipo:
        query = query.filter_by(tipo_cliente=tipo)
    if sucursal_id and sucursal_id > 0:
        query = query.filter_by(sucursal_id=sucursal_id)

    # support expiring filter for AJAX partials
    expiring_days = request.args.get("expiring", type=int)
    if expiring_days:
        try:
            # Build base query applying same filters
            base_q = Cliente.query
            if q:
                like = f"%{q}%"
                base_q = base_q.filter(
                    or_(
                        Cliente.nombre.ilike(like),
                        Cliente.apellido.ilike(like),
                        Cliente.correo.ilike(like),
                        Cliente.telefono.ilike(like),
                    )
                )
            if estado:
                base_q = base_q.filter_by(estado=estado)
            if tipo:
                base_q = base_q.filter_by(tipo_cliente=tipo)
            if sucursal_id and sucursal_id > 0:
                base_q = base_q.filter_by(sucursal_id=sucursal_id)
            candidate_clients = base_q.all()
            flags = _compute_client_flags_global(
                candidate_clients, horizon_days=expiring_days, sucursal_id=sucursal_id
            )
            expiring_client_ids = [cid for cid, f in flags.items() if f.get("soon")]
            if expiring_client_ids:
                query = query.filter(Cliente.id.in_(expiring_client_ids))
            else:
                query = Cliente.query.filter(Cliente.id == None)
        except Exception:
            query = Cliente.query.filter(Cliente.id == None)

    pag = query.order_by(Cliente.nombre.asc(), Cliente.apellido.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    from datetime import date as _date

    mode = request.args.get("mode")

    # compute reminders/flags for the partial table as well (AJAX reloads expect it)
    def _compute_client_flags(items_list):
        from datetime import date as _d, timedelta
        from decimal import Decimal

        flags = {}
        try:
            horizon = _d.today() + timedelta(days=7)
            for c in items_list:
                has_active = False
                soon = False
                soon_date = None
                has_manual = False
                manual_membresia_id = None

                try:
                    candidates = []
                    from ..services.attendance_service import manual_attendance_summary
                    for m in c.membresias:
                        getattr(m, "estado_id", None)
                        
                        # Check manual attendance
                        if getattr(m, "is_manual_asistencia", False):
                            summary = manual_attendance_summary(m)
                            if summary.get("puede_marcar"):
                                has_manual = True
                                manual_membresia_id = m.id
                        
                        if not getattr(m, "fecha_fin", None):
                            continue
                        if m.is_activa:
                            candidates.append(m)
                            continue
                        if m.is_en_espera:
                            try:
                                total_due = _compute_monto_total_for_membresia(m)
                            except Exception:
                                total_due = None
                            if total_due and total_due > 0:
                                total_paid = Decimal("0")
                                try:
                                    for p in m.pagos:
                                        for h in p.historial:
                                            try:
                                                total_paid += Decimal(h.monto_pagado)
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                if total_paid >= total_due:
                                    candidates.append(m)

                    if candidates:
                        m_sorted = sorted(candidates, key=lambda mm: mm.fecha_fin)
                        first = m_sorted[0]
                        has_active = True
                        if first.fecha_fin <= horizon:
                            soon = True
                            soon_date = first.fecha_fin
                    else:
                        has_active = False
                except Exception:
                    has_active = False
                    soon = False
                    soon_date = None
                    has_manual = False
                    manual_membresia_id = None
                flags[c.id] = {
                    "has_active": has_active,
                    "soon": soon,
                    "fecha_fin": str(soon_date) if soon_date else None,
                    "has_manual": has_manual,
                    "manual_membresia_id": manual_membresia_id,
                }
        except Exception:
            pass
        return flags

    client_flags = _compute_client_flags(pag.items)

    # include total count for UI (pagination.total)
    ctx = dict(
        pagination=pag,
        clientes=pag.items,
        today=_date.today(),
        reminders=client_flags,
        total=pag.total,
        q=q,
        estado=estado,
        tipo=tipo,
        per_page=per_page,
        page=page,
        expiring_days=expiring_days,
    )
    if mode == "accordion":
        return render_template("clientes/_accordion.html", **ctx)
    return render_template("clientes/_table.html", **ctx)


@clientes_bp.route("/export.csv")
def export_clientes_csv():
    # Exportar clientes actuales según filtros a CSV
    q = request.args.get("q", type=str)
    estado = request.args.get("estado")
    tipo = request.args.get("tipo")
    sucursal_id = request.args.get("sucursal_id", type=int)

    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.apellido.ilike(like),
                Cliente.correo.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )
    if estado:
        query = query.filter_by(estado=estado)
    if tipo:
        query = query.filter_by(tipo_cliente=tipo)
    if sucursal_id and sucursal_id > 0:
        query = query.filter_by(sucursal_id=sucursal_id)

    rows = query.order_by(Cliente.nombre.asc(), Cliente.apellido.asc()).all()

    import csv
    from io import StringIO

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(
        [
            "id",
            "nombre",
            "apellido",
            "correo",
            "telefono",
            "fecha_nacimiento",
            "tipo_cliente",
            "estado",
            "sucursal_id",
        ]
    )
    for r in rows:
        cw.writerow(
            [
                r.id,
                r.nombre,
                r.apellido,
                r.correo or "",
                r.telefono or "",
                r.fecha_nacimiento or "",
                r.tipo_cliente,
                r.estado,
                r.sucursal_id or "",
            ]
        )
    output = si.getvalue()
    return (
        output,
        200,
        {
            "Content-Type": "text/csv",
            "Content-Disposition": 'attachment; filename="clientes_export.csv"',
        },
    )


@clientes_bp.route("/print")
def print_clientes():
    # vista optimizada para imprimir según filtros
    q = request.args.get("q", type=str)
    estado = request.args.get("estado")
    tipo = request.args.get("tipo")
    sucursal_id = request.args.get("sucursal_id", type=int)

    query = Cliente.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.apellido.ilike(like),
                Cliente.correo.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )
    if estado:
        query = query.filter_by(estado=estado)
    if tipo:
        query = query.filter_by(tipo_cliente=tipo)
    if sucursal_id and sucursal_id > 0:
        query = query.filter_by(sucursal_id=sucursal_id)

    rows = query.order_by(Cliente.nombre.asc(), Cliente.apellido.asc()).all()
    from datetime import datetime as _dt

    return render_template("clientes/print.html", clientes=rows, now=_dt.utcnow())


@clientes_bp.route("/create", methods=["GET", "POST"])
def create_cliente():
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        apellido = (request.form.get("apellido") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        telefono = (request.form.get("telefono") or "").strip()
        fecha_nacimiento_raw = request.form.get("fecha_nacimiento")
        tipo_cliente = request.form.get("tipo_cliente") or "Individual"

        # Validar fecha y edad antes de llamar al servicio
        errors = {}
        if not fecha_nacimiento_raw:
            errors["fecha_nacimiento"] = "Fecha de nacimiento requerida"
        else:
            try:
                fecha_nacimiento = datetime.strptime(
                    fecha_nacimiento_raw, "%Y-%m-%d"
                ).date()
            except Exception:
                errors["fecha_nacimiento"] = "Fecha de nacimiento inválida"
                fecha_nacimiento = None

            if fecha_nacimiento:
                edad = compute_age(fecha_nacimiento)
                if edad is None or edad < 12:
                    errors["fecha_nacimiento"] = "La edad del cliente debe ser al menos 12 años"

        if errors:
            if is_ajax:
                return jsonify({"success": False, "message": "Error de validación", "errors": errors}), 400
            else:
                for field, msg in errors.items():
                    flash(msg)
                return redirect(url_for("clientes.create_cliente"))

        # Determinar sucursal
        sucursal_id = None
        if current_user and current_user.is_authenticated and current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif request.form.get("sucursal_id"):
            try:
                sucursal_id = int(request.form.get("sucursal_id"))
            except (ValueError, TypeError):
                pass
        elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
            try:
                sucursal_id = int(session.get("sucursal_id"))
            except (ValueError, TypeError):
                pass

        # Usar servicio para crear cliente
        success, cliente, error_msg = create_client(
            nombre=nombre,
            apellido=apellido,
            correo=correo or None,
            telefono=telefono or None,
            fecha_nacimiento=fecha_nacimiento,
            tipo_cliente=tipo_cliente,
            sucursal_id=sucursal_id,
        )

        if success:
            if is_ajax:
                return jsonify({
                    "success": True,
                    "message": "Cliente creado exitosamente",
                    "cliente_id": cliente.id
                })
            else:
                flash("Cliente creado")
                return redirect(url_for("clientes.list_clientes"))
        else:
            if is_ajax:
                return jsonify({"success": False, "message": f"Error: {error_msg}"}), 400
            else:
                flash(f"Error: {error_msg}")
                return redirect(url_for("clientes.create_cliente"))

    # GET - Cargar formulario vacío
    sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
    sucursal_actual_id = None
    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_actual_id = current_user.sucursal_id
        elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
            sucursal_actual_id = int(session.get("sucursal_id"))

    # Si es AJAX, devolver solo el formulario sin estructura de página
    if is_ajax:
        return render_template(
            "clientes/form_modal.html",
            cliente=None,
            sucursales=sucursales,
            sucursal_actual_id=sucursal_actual_id,
        )

    # Si es página regular, devolver con estructura completa
    return render_template(
        "clientes/form.html",
        cliente=None,
        sucursales=sucursales,
        sucursal_actual_id=sucursal_actual_id,
    )


@clientes_bp.route("/<int:cliente_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_cliente(cliente_id):
    c = Cliente.query.get_or_404(cliente_id)
    verify_sucursal_access(c)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        apellido = (request.form.get("apellido") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        telefono = (request.form.get("telefono") or "").strip()
        fecha_nacimiento_raw = request.form.get("fecha_nacimiento")
        tipo_cliente = request.form.get("tipo_cliente") or c.tipo_cliente

        # Validar edad
        errors = {}
        if fecha_nacimiento_raw:
            try:
                fecha_nacimiento = datetime.strptime(
                    fecha_nacimiento_raw, "%Y-%m-%d"
                ).date()
            except Exception:
                errors["fecha_nacimiento"] = "Fecha de nacimiento inválida"
                fecha_nacimiento = c.fecha_nacimiento

            if not errors and fecha_nacimiento:
                edad = compute_age(fecha_nacimiento)
                if edad is None or edad < 12:
                    errors["fecha_nacimiento"] = "La edad del cliente debe ser al menos 12 años"
        else:
            fecha_nacimiento = c.fecha_nacimiento

        if errors:
            if is_ajax:
                return jsonify({"success": False, "message": "Error de validación", "errors": errors}), 400
            else:
                for field, msg in errors.items():
                    flash(msg)
                return redirect(url_for("clientes.edit_cliente", cliente_id=cliente_id))

        # Determinar sucursal
        sucursal_id = c.sucursal_id
        if request.form.get("sucursal_id"):
            try:
                sucursal_id = int(request.form.get("sucursal_id"))
            except (ValueError, TypeError):
                pass

        # Usar servicio para actualizar
        success, error_msg = update_client(
            cliente_id=cliente_id,
            nombre=nombre,
            apellido=apellido,
            correo=correo or None,
            telefono=telefono or None,
            fecha_nacimiento=fecha_nacimiento,
            tipo_cliente=tipo_cliente,
            sucursal_id=sucursal_id,
        )

        if success:
            if is_ajax:
                return jsonify({
                    "success": True,
                    "message": "Cliente actualizado exitosamente",
                    "cliente_id": cliente_id
                })
            else:
                flash("Cliente actualizado")
                return redirect(url_for("clientes.list_clientes"))
        else:
            if is_ajax:
                return jsonify({"success": False, "message": f"Error: {error_msg}"}), 400
            else:
                flash(f"Error: {error_msg}")
                return redirect(url_for("clientes.edit_cliente", cliente_id=cliente_id))

    # GET - Cargar formulario con datos existentes
    if is_ajax:
        sucursales = Sucursal.query.order_by(Sucursal.nombre).all()
        return render_template(
            "clientes/form_modal.html",
            cliente=c,
            sucursales=sucursales,
            sucursal_actual_id=c.sucursal_id
        )

    return render_template("clientes/form.html", cliente=c)


@clientes_bp.route("/<int:cliente_id>/delete", methods=["POST"])
@admin_required
def delete_cliente(cliente_id):
    c = Cliente.query.get_or_404(cliente_id)
    verify_sucursal_access(c)
    try:
        pass
    except Exception:
        pass

    if not (
        current_user
        and getattr(current_user, "is_authenticated", False)
        and getattr(current_user, "rol_id", None) == 1
    ):
        flash("No autorizado")
        return redirect(url_for("index"))

    success, error_msg = delete_client(cliente_id)
    if success:
        flash("Cliente eliminado")
    else:
        flash(f"Error: {error_msg}")

    return redirect(url_for("clientes.list_clientes"))


@clientes_bp.route("/api/list", methods=["GET"])
@api_key_required  # Este decorador debe setear g.api_key_user y g.api_key_sucursal_id
def api_list_clientes():
    try:
        # 1. Obtener contexto de seguridad desde el decorador
        getattr(g, "api_key_user", None)
        api_sucursal_id = getattr(g, "api_key_sucursal_id", None)

        # 2. Obtener y sanear parámetros de búsqueda
        estado = request.args.get("estado", type=str)
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
        vencer_en_dias = request.args.get("vencer_en_dias", type=int)

        # 3. Lógica de Sucursal (Prioridad: API Key > Query Param)
        sucursal_id = api_sucursal_id or request.args.get("sucursal_id", type=int)

        # 4. Construcción de Query Base
        query = Cliente.query

        if estado:
            if estado not in ["Activo", "Inactivo"]:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": 'Estado inválido. Debe ser "Activo" o "Inactivo"',
                            "data": None,
                        }
                    ),
                    400,
                )
            query = query.filter_by(estado=estado)

        if sucursal_id:
            query = query.filter_by(sucursal_id=sucursal_id)

        # 5. Filtro de Vencimiento (Optimizado)
        if vencer_en_dias is not None:
            vencer_en_dias = max(1, vencer_en_dias)
            hoy = date.today()
            horizonte = hoy + timedelta(days=vencer_en_dias)

            # Filtramos clientes que tengan membresías activas o en espera
            # cuya fecha_fin esté entre hoy y el horizonte.
            from ..models import EstadoMembresia
            activa_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("activ%")).first()
            espera_estado = EstadoMembresia.query.filter(EstadoMembresia.nombre.ilike("%espera%")).first()
            activa_id = activa_estado.id if activa_estado else 2
            espera_id = espera_estado.id if espera_estado else 5

            query = (
                query.join(Cliente.membresias)
                .filter(
                    Cliente.membresias.property.mapper.class_.estado_id.in_([activa_id, espera_id]),
                    (Cliente.membresias.property.mapper.class_.fecha_fin >= hoy),
                    (Cliente.membresias.property.mapper.class_.fecha_fin <= horizonte),
                )
                .distinct()
            )

        # 6. Ejecutar Paginación
        pagination = query.order_by(
            Cliente.nombre.asc(), Cliente.apellido.asc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        # 7. Serialización de Datos
        clientes_data = []
        for cliente in pagination.items:
            # Lógica de membresía para el JSON de respuesta
            prox_venc = None
            tiene_activa = False

            # Buscamos la membresía más cercana a vencer
            membresias_validas = [
                m
                for m in cliente.membresias
                if getattr(m, "estado_id", None) == 2 and m.fecha_fin
            ]
            if membresias_validas:
                # Ordenamos por fecha_fin para obtener la más próxima
                m_proxima = min(membresias_validas, key=lambda x: x.fecha_fin)
                if m_proxima.fecha_fin >= date.today():
                    prox_venc = m_proxima.fecha_fin
                    tiene_activa = True

            clientes_data.append(
                {
                    "id": cliente.id,
                    "nombre": cliente.nombre or "",
                    "apellido": cliente.apellido or "",
                    "correo": cliente.correo or "",
                    "telefono": cliente.telefono or "",
                    "fecha_nacimiento": (
                        str(cliente.fecha_nacimiento)
                        if cliente.fecha_nacimiento
                        else None
                    ),
                    "estado": cliente.estado,
                    "sucursal_id": cliente.sucursal_id,
                    "tiene_membresia_activa": tiene_activa,
                    "fecha_vencimiento_proxima": str(prox_venc) if prox_venc else None,
                    "dias_para_vencer": (
                        (prox_venc - date.today()).days if prox_venc else None
                    ),
                }
            )

        return (
            jsonify(
                {
                    "success": True,
                    "data": {
                        "clientes": clientes_data,
                        "pagination": {
                            "total": pagination.total,
                            "total_pages": pagination.pages,
                            "current_page": page,
                            "per_page": per_page,
                        },
                        "filters": {
                            "estado": estado,
                            "sucursal_id": sucursal_id,
                            "vencer_en_dias": vencer_en_dias,
                        },
                    },
                }
            ),
            200,
        )

    except Exception as e:
        # Registro del error real para el desarrollador
        print(f"DEBUG ERROR: {str(e)}")
        return jsonify({"success": False, "error": "Error interno del servidor"}), 500
