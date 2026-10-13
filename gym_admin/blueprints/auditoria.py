from flask import Blueprint, render_template, request, jsonify
from ..models import Auditoria, Usuario, Cliente
import json
from ..extensions import db
from datetime import datetime
from ..utils_timezone import to_utc_naive

auditoria_bp = Blueprint(
    "auditoria", __name__, template_folder="../templates/auditoria"
)


def _safe_json_loads(value):
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _pk_to_text(pk):
    if isinstance(pk, dict):
        try:
            return ", ".join([f"{k}={v}" for k, v in pk.items()])
        except Exception:
            return ""
    return str(pk or "")


def _to_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _cliente_nombre(cliente):
    if not cliente:
        return None
    nombre = (cliente.nombre or "").strip()
    apellido = (cliente.apellido or "").strip()
    full = " ".join([p for p in [nombre, apellido] if p])
    return full or f"Cliente #{cliente.id}"


def _extract_cliente_ids(payload, tabla, pk):
    ids = set()

    if isinstance(pk, dict):
        for key, val in pk.items():
            if str(key).lower() == "cliente_id":
                cid = _to_int(val)
                if cid:
                    ids.add(cid)
            if str(key).lower() == "id" and str(tabla or "").lower() == "clientes":
                cid = _to_int(val)
                if cid:
                    ids.add(cid)

    if not isinstance(payload, dict):
        return ids

    valores = payload.get("valores") or payload.get("values") or {}
    if isinstance(valores, dict):
        for key, val in valores.items():
            key_norm = str(key).lower()
            if key_norm == "cliente_id" or (
                key_norm == "id" and str(tabla or "").lower() == "clientes"
            ):
                cid = _to_int(val)
                if cid:
                    ids.add(cid)

    cambios = payload.get("cambios") or []
    if isinstance(cambios, list):
        for ch in cambios:
            if not isinstance(ch, dict):
                continue
            col = str(ch.get("columna") or "").lower()
            if col == "cliente_id" or (col == "id" and str(tabla or "").lower() == "clientes"):
                old_id = _to_int(ch.get("anterior"))
                new_id = _to_int(ch.get("nuevo"))
                if old_id:
                    ids.add(old_id)
                if new_id:
                    ids.add(new_id)

    return ids


def _format_cliente_ref(value, clientes_map):
    cid = _to_int(value)
    if not cid:
        return None
    cliente = clientes_map.get(cid)
    if not cliente:
        return f"{cid}"
    nombre = _cliente_nombre(cliente)
    return f"{cid} - {nombre}"


def _resolve_cliente_ref(payload, tabla, pk, clientes_map):
    ids = sorted(_extract_cliente_ids(payload, tabla, pk))
    if not ids:
        return None
    cid = ids[0]
    cliente = clientes_map.get(cid)
    if not cliente:
        return {"id": cid, "nombre": None}
    return {"id": cid, "nombre": _cliente_nombre(cliente)}


def _build_resumen(operacion, payload):
    if not isinstance(payload, dict):
        return f"{operacion or 'CAMBIO'} registrado"

    accion = (payload.get("accion") or operacion or "").upper()
    if accion == "INSERT":
        return "Registro creado"
    if accion == "DELETE":
        return "Registro eliminado"
    if accion == "UPDATE":
        cambios = payload.get("cambios") or []
        if isinstance(cambios, list) and cambios:
            return f"{len(cambios)} campo(s) actualizado(s)"
        return "Registro actualizado"
    return f"{accion or 'CAMBIO'} registrado"


def _build_detail_rows(payload, pk, tabla, clientes_map):
    rows = []

    # Siempre mostrar PK para facilitar trazabilidad del registro exacto.
    if isinstance(pk, dict):
        for key, val in pk.items():
            nuevo_display = val
            if str(key).lower() == "cliente_id" or (
                str(key).lower() == "id" and str(tabla or "").lower() == "clientes"
            ):
                nuevo_display = _format_cliente_ref(val, clientes_map) or val
            rows.append(
                {
                    "campo": f"PK: {key}",
                    "anterior": None,
                    "nuevo": val,
                    "nuevo_display": nuevo_display,
                    "es_pk": True,
                }
            )
    elif pk not in (None, ""):
        rows.append(
            {
                "campo": "PK",
                "anterior": None,
                "nuevo": pk,
                "nuevo_display": pk,
                "es_pk": True,
            }
        )

    if not isinstance(payload, dict):
        return rows

    accion = (payload.get("accion") or "").upper()
    if accion in ("INSERT", "DELETE"):
        valores = payload.get("valores") or payload.get("values") or {}
        if isinstance(valores, dict):
            for campo, valor in valores.items():
                nuevo_display = valor
                if str(campo).lower() == "cliente_id" or (
                    str(campo).lower() == "id" and str(tabla or "").lower() == "clientes"
                ):
                    nuevo_display = _format_cliente_ref(valor, clientes_map) or valor
                rows.append(
                    {
                        "campo": campo,
                        "anterior": None,
                        "nuevo": valor,
                        "nuevo_display": nuevo_display,
                    }
                )
    elif accion == "UPDATE":
        cambios = payload.get("cambios") or []
        if isinstance(cambios, list):
            for ch in cambios:
                if not isinstance(ch, dict):
                    continue
                campo = ch.get("columna") or "(sin campo)"
                anterior = ch.get("anterior")
                nuevo = ch.get("nuevo")
                anterior_display = anterior
                nuevo_display = nuevo
                if str(campo).lower() == "cliente_id" or (
                    str(campo).lower() == "id" and str(tabla or "").lower() == "clientes"
                ):
                    anterior_display = _format_cliente_ref(anterior, clientes_map) or anterior
                    nuevo_display = _format_cliente_ref(nuevo, clientes_map) or nuevo
                rows.append(
                    {
                        "campo": campo,
                        "anterior": anterior,
                        "nuevo": nuevo,
                        "anterior_display": anterior_display,
                        "nuevo_display": nuevo_display,
                    }
                )
    return rows


def _apply_filters(query, tabla, operacion, usuario_id, usuario_nombre, fecha_min, fecha_max, q):
    if tabla:
        query = query.filter(Auditoria.tabla_afectada.ilike(f"%{tabla}%"))
    if operacion:
        query = query.filter(Auditoria.operacion == operacion)
    if usuario_id:
        query = query.filter(Auditoria.usuario_id == usuario_id)
    elif usuario_nombre:
        ids = [
            u.id for u in Usuario.query.filter(Usuario.nombre.ilike(f"%{usuario_nombre}%"))
        ]
        if ids:
            query = query.filter(Auditoria.usuario_id.in_(ids))
        else:
            query = query.filter(Auditoria.usuario_id.is_(None))
    if fecha_min:
        try:
            sd_b = datetime.strptime(fecha_min, "%Y-%m-%d")
            start_b = datetime(sd_b.year, sd_b.month, sd_b.day)
            start = to_utc_naive(start_b)
            query = query.filter(Auditoria.fecha >= start)
        except Exception:
            pass
    if fecha_max:
        try:
            hd_b = datetime.strptime(fecha_max, "%Y-%m-%d")
            end_b = datetime(hd_b.year, hd_b.month, hd_b.day, 23, 59, 59)
            end = to_utc_naive(end_b)
            query = query.filter(Auditoria.fecha <= end)
        except Exception:
            pass
    if q:
        query = query.filter(Auditoria.descripcion.ilike(f"%{q}%"))
    return query


@auditoria_bp.route("/")
def list_auditoria():
    # render template; the actual data will be fetched by AJAX /auditoria/search
    return render_template("auditoria/list.html")


@auditoria_bp.route("/search")
def search_auditoria():
    # AJAX endpoint: accepts filters -> tabla, operacion, usuario_id, fecha_min, fecha_max, q (search)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    tabla = request.args.get("tabla")
    operacion = request.args.get("operacion")
    usuario_id = request.args.get("usuario_id", type=int)
    usuario_nombre = request.args.get("usuario_nombre")
    fecha_min = request.args.get("fecha_min")
    fecha_max = request.args.get("fecha_max")
    q = request.args.get("q")

    base_query = _apply_filters(
        Auditoria.query,
        tabla,
        operacion,
        usuario_id,
        usuario_nombre,
        fecha_min,
        fecha_max,
        q,
    )

    stats_rows = (
        base_query.with_entities(Auditoria.operacion, db.func.count(Auditoria.id))
        .group_by(Auditoria.operacion)
        .all()
    )
    stats = {"INSERT": 0, "UPDATE": 0, "DELETE": 0}
    for op, total in stats_rows:
        key = (op or "").upper()
        if key in stats:
            stats[key] = int(total or 0)

    query = base_query.order_by(Auditoria.fecha.desc())
    pag = query.paginate(page=page, per_page=per_page, error_out=False)

    usuario_ids = list({a.usuario_id for a in pag.items if a.usuario_id})
    users_map = {}
    if usuario_ids:
        users = Usuario.query.filter(Usuario.id.in_(usuario_ids)).all()
        users_map = {u.id: u for u in users}

    pre_items = []
    cliente_ids = set()
    for a in pag.items:
        usuario = users_map.get(a.usuario_id)
        payload = _safe_json_loads(a.descripcion)
        pk = payload.get("pk") if isinstance(payload, dict) else None
        cliente_ids.update(_extract_cliente_ids(payload, a.tabla_afectada, pk))
        pre_items.append(
            {
                "id": a.id,
                "pk": pk,
                "pk_text": _pk_to_text(pk),
                "usuario_id": a.usuario_id,
                "usuario": usuario.nombre if usuario else None,
                "usuario_correo": usuario.correo if usuario else None,
                "tabla": a.tabla_afectada,
                "operacion": a.operacion,
                "fecha": a.fecha.isoformat(),
                "descripcion": a.descripcion,
                "descripcion_obj": payload,
                "resumen": _build_resumen(a.operacion, payload),
                "automatico": bool(payload.get("automatic")) if isinstance(payload, dict) else False,
            }
        )

    clientes_map = {}
    if cliente_ids:
        clientes = Cliente.query.filter(Cliente.id.in_(list(cliente_ids))).all()
        clientes_map = {c.id: c for c in clientes}

    items = []
    for item in pre_items:
        payload = item.get("descripcion_obj")
        pk = item.get("pk")
        tabla_item = item.get("tabla")
        detalle_rows = _build_detail_rows(payload, pk, tabla_item, clientes_map)
        cliente_ref = _resolve_cliente_ref(payload, tabla_item, pk, clientes_map)

        item["detalle_rows"] = detalle_rows
        item["detalle_count"] = len(detalle_rows)
        item["cliente_ref"] = cliente_ref
        items.append(item)

    return jsonify(
        {
            "total": pag.total,
            "page": pag.page,
            "per_page": pag.per_page,
            "pages": pag.pages,
            "items": items,
            "stats": stats,
        }
    )


@auditoria_bp.route("/export")
def auditoria_export():
    # export CSV according to same filters as /search
    import csv
    from io import StringIO

    tabla = request.args.get("tabla")
    operacion = request.args.get("operacion")
    usuario_id = request.args.get("usuario_id", type=int)
    usuario_nombre = request.args.get("usuario_nombre")
    fecha_min = request.args.get("fecha_min")
    fecha_max = request.args.get("fecha_max")
    q = request.args.get("q")

    query = _apply_filters(
        Auditoria.query,
        tabla,
        operacion,
        usuario_id,
        usuario_nombre,
        fecha_min,
        fecha_max,
        q,
    )

    query = query.order_by(Auditoria.fecha.desc())
    items = query.all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["fecha", "tabla", "operacion", "usuario_id", "pk", "detalle"])
    for a in items:
        pk = ""
        try:
            obj = json.loads(a.descripcion or "{}")
            pk = obj.get("pk") or ""
        except Exception:
            pk = ""
        detalle = (
            a.descripcion
            if isinstance(a.descripcion, str)
            else json.dumps(a.descripcion, ensure_ascii=False)
        )
        writer.writerow(
            [
                a.fecha.isoformat(),
                a.tabla_afectada,
                a.operacion,
                a.usuario_id or "",
                pk,
                detalle,
            ]
        )
    output = si.getvalue()
    return (
        output,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="auditoria_export.csv"',
        },
    )


@auditoria_bp.route("/users")
def auditoria_users():
    users = Usuario.query.order_by(Usuario.nombre).all()
    out = [{"id": u.id, "nombre": u.nombre or u.correo} for u in users]
    return jsonify(out)
