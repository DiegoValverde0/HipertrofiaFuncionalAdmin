from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify,
)
from ..extensions import db
from ..models import Pago, HistorialPago, Membresia, Cliente
from ..services.payment_service import (
    add_payment_history,
    ensure_membership_state_after_payment,
)
from sqlalchemy import func
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from ..utils_timezone import now_utc, to_bolivia, to_utc_naive
from ..utils import (
    process_membership_states,
    _compute_monto_total_for_membresia,
    verify_sucursal_access,
)

pagos_bp = Blueprint("pagos", __name__)


# Usamos la implementación centralizada de `_compute_monto_total_for_membresia`
# importada desde `..utils` para asegurar comportamiento consistente.


def _total_pagado(pago: Pago) -> Decimal:
    total = Decimal("0.00")
    for h in pago.historial:
        try:
            total += Decimal(h.monto_pagado)
        except Exception:
            pass
    return total.quantize(Decimal("0.01"))


@pagos_bp.route("/")
def list_pagos():
    # server-side paginated, filterable list to support real-time search and pagination
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = request.args.get("q", type=str)
    period = request.args.get("period", "all")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    request.args.get("metodo_pago")

    query = Pago.query.join(Cliente, Pago.cliente_id == Cliente.id)
    # apply search by cliente nombre/apellido
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like))
        )

    # filter by metodo_pago

    # filter by period or explicit dates
    try:
        # interpret periods and date ranges as Bolivia local time, convert to UTC naive for DB comparison
        try:
            # use current instant in UTC, then convert to Bolivia local to compute day/week/month boundaries
            if period and period != "all" and not (fecha_desde and fecha_hasta):
                now_b = to_bolivia(now_utc())
                if period == "today":
                    start_b = datetime(now_b.year, now_b.month, now_b.day)
                    end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
                elif period == "week":
                    start_day = datetime(
                        now_b.year, now_b.month, now_b.day
                    ) - timedelta(days=now_b.weekday())
                    start_b = start_day
                    end_b = start_b + timedelta(
                        days=6, hours=23, minutes=59, seconds=59
                    )
                elif period == "month":
                    start_b = datetime(now_b.year, now_b.month, 1)
                    if now_b.month == 12:
                        nm = datetime(now_b.year + 1, 1, 1)
                    else:
                        nm = datetime(now_b.year, now_b.month + 1, 1)
                    end_b = nm - timedelta(seconds=1)
                elif period == "year":
                    start_b = datetime(now_b.year, 1, 1)
                    end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
                else:
                    start_b = None
                    end_b = None
                if start_b and end_b:
                    start = to_utc_naive(start_b)
                    end = to_utc_naive(end_b)
                    query = query.filter(
                        Pago.fecha_pago >= start, Pago.fecha_pago <= end
                    )
            elif fecha_desde and fecha_hasta:
                try:
                    # fecha_desde/hasta come en 'YYYY-MM-DD' (date inputs). Interpret as Bolivia local day boundaries.
                    sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
                    hd_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
                    # start at 00:00 Bolivia, end at 23:59:59 Bolivia
                    start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
                    end_b = datetime(hd_b.year, hd_b.month, hd_b.day, 23, 59, 59)
                    start = to_utc_naive(start_b)
                    end = to_utc_naive(end_b)
                    query = query.filter(
                        Pago.fecha_pago >= start, Pago.fecha_pago <= end
                    )
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass

    # --- LÓGICA DE FILTRADO POR SUCURSAL UNIFICADA ---
    sucursal_id = None
    from flask_login import current_user
    from flask import session

    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
            sucursal_id = int(session.get("sucursal_id"))

    if sucursal_id:
        query = query.filter(Pago.sucursal_id == sucursal_id)

    pag = query.order_by(Pago.fecha_pago.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = pag.items

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("partial") == "1"
    )
    if is_ajax:
        return render_template("pagos/_table.html", pagination=pag, pagos=items, q=q)
    return render_template("pagos/list.html", pagination=pag, pagos=items, q=q)


@pagos_bp.route("/reporte")
def reporte_detallado():
    """
    Vista de reporte que muestra una lista plana de HistorialPago (abonos individuales)
    para permitir un filtrado y análisis más detallado.
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    q = request.args.get("q", type=str)
    period = request.args.get("period", "all")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    metodo_pago_filter = request.args.get("metodo_pago")

    # La consulta base es sobre HistorialPago, uniéndose a Pago y Cliente
    query = HistorialPago.query.join(Pago, HistorialPago.pago_id == Pago.id).join(
        Cliente, Pago.cliente_id == Cliente.id
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            (Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like))
        )

    if metodo_pago_filter:
        query = query.filter(HistorialPago.metodo_pago == metodo_pago_filter)

    # --- LÓGICA DE FILTRADO POR SUCURSAL UNIFICADA ---
    sucursal_id = None
    from flask_login import current_user
    from flask import session

    if current_user and current_user.is_authenticated:
        if current_user.sucursal_id:
            sucursal_id = current_user.sucursal_id
        elif session.get("sucursal_id") and str(session.get("sucursal_id")) != "0":
            sucursal_id = int(session.get("sucursal_id"))

    if sucursal_id:
        query = query.filter(Pago.sucursal_id == sucursal_id)

    # Filtro por fecha (aplicado a HistorialPago.fecha_pago)
    # interpret periods and date ranges as Bolivia local time, convert to UTC naive for DB comparison
    try:
        if period and period != "all" and not (fecha_desde and fecha_hasta):
            now_b = to_bolivia(now_utc())
            if period == "today":
                start_b = datetime(now_b.year, now_b.month, now_b.day)
                end_b = datetime(now_b.year, now_b.month, now_b.day, 23, 59, 59)
            elif period == "week":
                start_day = datetime(now_b.year, now_b.month, now_b.day) - timedelta(
                    days=now_b.weekday()
                )
                start_b = start_day
                end_b = start_b + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif period == "month":
                start_b = datetime(now_b.year, now_b.month, 1)
                if now_b.month == 12:
                    nm = datetime(now_b.year + 1, 1, 1)
                else:
                    nm = datetime(now_b.year, now_b.month + 1, 1)
                end_b = nm - timedelta(seconds=1)
            elif period == "year":
                start_b = datetime(now_b.year, 1, 1)
                end_b = datetime(now_b.year, 12, 31, 23, 59, 59)
            else:
                start_b = None
                end_b = None
            if start_b and end_b:
                start = to_utc_naive(start_b)
                end = to_utc_naive(end_b)
                query = query.filter(
                    HistorialPago.fecha_pago >= start, HistorialPago.fecha_pago <= end
                )
        elif fecha_desde and fecha_hasta:
            try:
                sd_b = datetime.strptime(fecha_desde, "%Y-%m-%d")
                hd_b = datetime.strptime(fecha_hasta, "%Y-%m-%d")
                start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
                end_b = datetime(hd_b.year, hd_b.month, hd_b.day, 23, 59, 59)
                start = to_utc_naive(start_b)
                end = to_utc_naive(end_b)
                query = query.filter(
                    HistorialPago.fecha_pago >= start, HistorialPago.fecha_pago <= end
                )
            except Exception:
                pass
    except Exception:
        pass

    # Calcular el total de los resultados filtrados ANTES de la paginación
    total_filtrado = query.with_entities(
        func.sum(HistorialPago.monto_pagado)
    ).scalar() or Decimal("0.00")

    pag = query.order_by(HistorialPago.fecha_pago.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = pag.items

    return render_template(
        "pagos/reporte_detallado.html",
        pagination=pag,
        abonos=items,
        q=q,
        metodo_pago_filter=metodo_pago_filter,
        period=period,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        total_filtrado=total_filtrado,
    )


@pagos_bp.route("/create", methods=["GET", "POST"])
def create_pago():
    membresia_id = request.args.get("membresia_id", type=int) or request.form.get(
        "membresia_id", type=int
    )
    membresia = db.session.get(Membresia, membresia_id) if membresia_id else None
    if membresia:
        verify_sucursal_access(membresia)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        membresia_id = request.form.get("membresia_id", type=int)
        membresia = db.session.get(Membresia, membresia_id)
        if not membresia:
            if is_ajax:
                return jsonify({"success": False, "message": "Membresía no encontrada"}), 400
            flash("Membresía no encontrada")
            return redirect(url_for("pagos.create_pago"))

        # Validate membership is Pending
        if not getattr(membresia, "is_pendiente", False):
            flash("No se puede crear pago: membresía no está pendiente de pago")
            return redirect(request.referrer or url_for("pagos.create_pago"))

        monto_total = _compute_monto_total_for_membresia(membresia)

        # Parse initial abono
        inicial_raw = request.form.get("monto_inicial")
        try:
            inicial = (
                Decimal(inicial_raw).quantize(Decimal("0.01"))
                if inicial_raw and inicial_raw.strip()
                else None
            )
        except InvalidOperation:
            inicial = None

        if inicial is None or inicial <= Decimal("0.01"):
            flash("Abono inicial requerido (mayor a 0)")
            return redirect(request.referrer or url_for("pagos.create_pago"))

        # Handle split payment
        is_split_payment = request.form.get("is_split_payment") == "on"
        metodo = request.form.get("metodo_pago", "")
        comentarios = request.form.get("comentarios") or ""

        if is_split_payment:
            try:
                monto_efectivo = Decimal(
                    request.form.get("monto_efectivo") or "0"
                ).quantize(Decimal("0.01"))
                monto_qr = Decimal(request.form.get("monto_qr") or "0").quantize(
                    Decimal("0.01")
                )
            except InvalidOperation:
                flash("Montos divididos deben ser números válidos")
                return redirect(request.referrer or url_for("pagos.create_pago"))

            if (monto_efectivo + monto_qr) != inicial:
                flash("Suma de montos divididos no coincide")
                return redirect(request.referrer or url_for("pagos.create_pago"))

            metodo = "QR/Efectivo"
            comentarios += f" Pago dividido: {monto_efectivo} Efectivo, {monto_qr} QR."
        
        if not metodo:
            if is_ajax:
                return jsonify({"success": False, "message": "Método de pago requerido"}), 400
            flash("Método de pago requerido")
            return redirect(request.referrer or url_for("pagos.create_pago"))

        try:
            # Get or create Pago (enforcement: only 1 per membership)
            p = Pago.query.filter_by(membresia_id=membresia.id).first()
            if not p:
                p = Pago(
                    cliente_id=membresia.cliente_id,
                    membresia_id=membresia.id,
                    sucursal_id=membresia.sucursal_id,
                    monto_total=monto_total,
                    metodo_pago=metodo,
                    comentarios=comentarios.strip(),
                )
                db.session.add(p)
                db.session.flush()

            # Register historial entries using service (validates amount doesn't exceed balance)
            if is_split_payment:
                if monto_efectivo > 0:
                    success, hist, err = add_payment_history(
                        pago_id=p.id,
                        abono=monto_efectivo,
                        metodo_pago="Efectivo",
                        comentarios=comentarios.strip(),
                    )
                    if not success:
                        db.session.rollback()
                        if is_ajax:
                            return jsonify({"success": False, "message": f"Error abono efectivo: {err}"}), 400
                        flash(f"Error abono efectivo: {err}")
                        return redirect(url_for("pagos.create_pago"))

                if monto_qr > 0:
                    success, hist, err = add_payment_history(
                        pago_id=p.id,
                        abono=monto_qr,
                        metodo_pago="Pago QR",
                        comentarios=comentarios.strip(),
                    )
                    if not success:
                        db.session.rollback()
                        if is_ajax:
                            return jsonify({"success": False, "message": f"Error abono QR: {err}"}), 400
                        flash(f"Error abono QR: {err}")
                        return redirect(url_for("pagos.create_pago"))
            else:
                success, hist, err = add_payment_history(
                    pago_id=p.id,
                    abono=inicial,
                    metodo_pago=metodo,
                    comentarios=comentarios.strip(),
                )
                if not success:
                    db.session.rollback()
                    if is_ajax:
                        return jsonify({"success": False, "message": f"Error registrando abono: {err}"}), 400
                    flash(f"Error registrando abono: {err}")
                    return redirect(url_for("pagos.create_pago"))

            # Commit if all successful
            db.session.commit()

            # Process membership state after payment (may activate membership)
            try:
                success, new_estado_id, err = ensure_membership_state_after_payment(
                    membresia.id
                )
            except Exception:
                current_app.logger.exception("Error procesando estado tras abono")

            if is_ajax:
                return jsonify({"success": True, "message": "Abono registrado", "pago_id": p.id})
            flash("Abono registrado")
            return redirect(url_for("pagos.view_pago", pago_id=p.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating payment: %s", e)
            if is_ajax:
                return jsonify({"success": False, "message": f"Error creando pago: {e}"}), 500
            flash(f"Error creando pago: {e}")
            return redirect(url_for("pagos.create_pago"))

    # GET
    monto_a_pagar = Decimal("0.00")
    if membresia:
        monto_a_pagar = _compute_monto_total_for_membresia(membresia)
        pago_existente = Pago.query.filter_by(membresia_id=membresia.id).first()
        if pago_existente:
            monto_a_pagar -= _total_pagado(pago_existente)
    if is_ajax:
        return render_template("pagos/form_modal.html", membresia=membresia, monto_a_pagar=monto_a_pagar)
    return render_template(
        "pagos/form.html", membresia=membresia, monto_a_pagar=monto_a_pagar
    )


@pagos_bp.route("/<int:pago_id>")
def view_pago(pago_id):
    p = Pago.query.get_or_404(pago_id)
    verify_sucursal_access(p)
    # ordenar historial para que el abono más reciente aparezca primero
    try:
        p.historial = sorted(
            p.historial, key=lambda h: h.fecha_pago or datetime.min, reverse=True
        )
    except Exception:
        pass
    pagado = _total_pagado(p)
    pendiente = (Decimal(p.monto_total or 0) - pagado).quantize(Decimal("0.01"))
    return render_template(
        "pagos/by_membresia.html", pago=p, pagado=pagado, pendiente=pendiente
    )


@pagos_bp.route("/search_membresias")
def search_membresias():
    q = request.args.get("q", type=str) or ""
    if not q:
        return jsonify([])
    like = f"%{q}%"
    # permitir búsqueda por ID exacto o por nombre/apellido de cliente
    results = []
    try:
        # si q es numérico, buscar por id
        if q.isdigit():
            m = db.session.get(Membresia, int(q))
            if m and getattr(m, "is_pendiente", False):
                monto = float(_compute_monto_total_for_membresia(m))
                pagado = 0.0
                for p in m.pagos:
                    for h in p.historial:
                        try:
                            pagado += float(h.monto_pagado)
                        except Exception:
                            pass
                pendiente = round(monto - pagado, 2)
                results.append(
                    {
                        "id": m.id,
                        "cliente_nombre": f"{m.cliente.nombre} {m.cliente.apellido}",
                        "plan": m.plan.nombre if m.plan else None,
                        "fecha_fin": str(m.fecha_fin),
                        "monto_calculado": monto,
                        "pendiente": pendiente,
                    }
                )
                return jsonify(results)

        # búsqueda por cliente nombre/apellido (sólo membresías pendientes)
        from ..models import EstadoMembresia
        membres = (
            Membresia.query.join(Cliente)
            .join(EstadoMembresia)
            .filter((Cliente.nombre.ilike(like)) | (Cliente.apellido.ilike(like)))
            .filter(EstadoMembresia.nombre.ilike("pendient%"))
            .limit(30)
            .all()
        )
        for m in membres:
            monto = float(_compute_monto_total_for_membresia(m))
            pagado = 0.0
            # calcular pagado sumando historial de todos los pagos asociados
            for p in m.pagos:
                for h in p.historial:
                    try:
                        pagado += float(h.monto_pagado)
                    except Exception:
                        pass
            pendiente = round(monto - pagado, 2)
            results.append(
                {
                    "id": m.id,
                    "cliente_nombre": f"{m.cliente.nombre} {m.cliente.apellido}",
                    "plan": m.plan.nombre if m.plan else None,
                    "fecha_fin": str(m.fecha_fin),
                    "monto_calculado": monto,
                    "pendiente": pendiente,
                }
            )
    except Exception:
        current_app.logger.exception("Error buscando membresias")
    return jsonify(results)


@pagos_bp.route("/<int:pago_id>/abonar", methods=["POST"])
def abonar(pago_id):
    p = Pago.query.get_or_404(pago_id)
    verify_sucursal_access(p)

    # --- LÓGICA PARA PAGOS DIVIDIDOS (también en abonos) ---
    monto_raw = request.form.get("monto")
    is_split_payment = request.form.get("is_split_payment") == "on"
    metodo = request.form.get("metodo_pago")
    comentarios = request.form.get("comentarios") or ""

    try:
        monto = Decimal(monto_raw).quantize(Decimal("0.01"))
    except Exception:
        flash("Monto inválido")
        return redirect(url_for("pagos.view_pago", pago_id=p.id))

    if is_split_payment:
        try:
            monto_efectivo = Decimal(
                request.form.get("monto_efectivo") or "0"
            ).quantize(Decimal("0.01"))
            monto_qr = Decimal(request.form.get("monto_qr") or "0").quantize(
                Decimal("0.01")
            )
        except InvalidOperation:
            flash("Los montos para el pago dividido deben ser números válidos.")
            return redirect(url_for("pagos.view_pago", pago_id=p.id))

        # La suma de los montos divididos debe ser igual al monto total del abono
        if (monto_efectivo + monto_qr) != monto:
            flash(
                f"La suma de los montos divididos ({monto_efectivo + monto_qr}) no coincide con el monto total a abonar ({monto})."
            )
            return redirect(url_for("pagos.view_pago", pago_id=p.id))

        metodo = "QR/Efectivo"
        comentarios += (
            f" Pago dividido: {monto_efectivo} en Efectivo, {monto_qr} en QR."
        )

    if not metodo:
        flash("El método de pago es obligatorio.")
        return redirect(url_for("pagos.view_pago", pago_id=p.id))

    if monto <= 0:
        flash("El monto debe ser mayor que cero")
        return redirect(url_for("pagos.view_pago", pago_id=p.id))

    pagado = _total_pagado(p)
    total = Decimal(p.monto_total or 0).quantize(Decimal("0.01"))
    restante = (total - pagado).quantize(Decimal("0.01"))
    # Usar una pequeña tolerancia para evitar errores de punto flotante
    if monto > (restante + Decimal("0.01")):
        flash(f"El monto excede el saldo pendiente ({restante})")
        return redirect(url_for("pagos.view_pago", pago_id=p.id))

    # --- LÓGICA MEJORADA PARA REGISTRAR HISTORIAL DE ABONOS ---
    if is_split_payment:
        if monto_efectivo > 0:
            h_efectivo = HistorialPago(
                pago_id=p.id,
                monto_pagado=monto_efectivo,
                metodo_pago="Efectivo",
                comentarios=comentarios.strip(),
            )
            db.session.add(h_efectivo)
        if monto_qr > 0:
            h_qr = HistorialPago(
                pago_id=p.id,
                monto_pagado=monto_qr,
                metodo_pago="Pago QR",
                comentarios=comentarios.strip(),
            )
            db.session.add(h_qr)
        p.metodo_pago = "QR/Efectivo"  # Actualizar el método en el pago principal
    else:
        h = HistorialPago(
            pago_id=p.id,
            monto_pagado=monto,
            metodo_pago=metodo,
            comentarios=comentarios.strip(),
        )
        db.session.add(h)
        p.metodo_pago = metodo  # Actualizar el método en el pago principal
    # Actualizar siempre el comentario en el pago principal
    p.comentarios = comentarios.strip()

    # si completa el pago, podemos actualizar fecha_pago del Pago (opcional)
    try:
        db.session.commit()
        # después de registrar el abono, procesar estados de membresías relacionadas
        try:
            current_app.logger.debug(
                "Calling process_membership_states for membresia %s after abonar",
                p.membresia_id,
            )
            updated = ensure_membership_state_after_payment(p.membresia_id)
            if not updated:
                process_membership_states(target_membresia_id=p.membresia_id)
        except Exception:
            current_app.logger.exception("Error procesando estados después de abono")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error al registrar abono: %s", e)
        flash(f"Error al registrar abono: {e}")
        return redirect(url_for("pagos.view_pago", pago_id=p.id))
    flash("Abono registrado")
    return redirect(url_for("pagos.view_pago", pago_id=p.id))
