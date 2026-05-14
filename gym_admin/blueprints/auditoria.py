from flask import Blueprint, render_template, request, jsonify
from ..models import Auditoria, Usuario
import json
from ..extensions import db
from datetime import datetime
from ..utils_timezone import now_utc, to_bolivia, to_utc_naive

auditoria_bp = Blueprint(
    "auditoria", __name__, template_folder="../templates/auditoria"
)


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

    query = Auditoria.query
    if tabla:
        query = query.filter(Auditoria.tabla_afectada.ilike(f"%{tabla}%"))
    if operacion:
        query = query.filter(Auditoria.operacion == operacion)
    if usuario_id:
        query = query.filter(Auditoria.usuario_id == usuario_id)
    elif usuario_nombre:
        ids = [
            u.id
            for u in Usuario.query.filter(Usuario.nombre.ilike(f"%{usuario_nombre}%"))
        ]
        if ids:
            query = query.filter(Auditoria.usuario_id.in_(ids))
        else:
            query = query.filter(Auditoria.usuario_id == None)
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
        # buscar en descripcion como texto
        query = query.filter(Auditoria.descripcion.ilike(f"%{q}%"))

    query = query.order_by(Auditoria.fecha.desc())
    pag = query.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for a in pag.items:
        usuario = None
        try:
            usuario = Usuario.query.get(a.usuario_id) if a.usuario_id else None
        except Exception:
            usuario = None
        # intentar parsear descripcion JSON y extraer PK si existe
        pk = None
        try:
            d = a.descripcion
            if d:
                obj = None
                try:
                    obj = __import__("json").loads(d)
                except Exception:
                    obj = None
                if obj and isinstance(obj, dict) and "pk" in obj:
                    pk = obj.get("pk")
        except Exception:
            pk = None
        items.append(
            {
                "id": a.id,
                "pk": pk,
                "usuario_id": a.usuario_id,
                "usuario": (
                    usuario.nombre if usuario else (usuario and usuario.correo) or None
                ),
                "tabla": a.tabla_afectada,
                "operacion": a.operacion,
                "fecha": a.fecha.isoformat(),
                "descripcion": a.descripcion,
            }
        )

    return jsonify(
        {
            "total": pag.total,
            "page": pag.page,
            "per_page": pag.per_page,
            "pages": pag.pages,
            "items": items,
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

    query = Auditoria.query
    if tabla:
        query = query.filter(Auditoria.tabla_afectada.ilike(f"%{tabla}%"))
    if operacion:
        query = query.filter(Auditoria.operacion == operacion)
    if usuario_id:
        query = query.filter(Auditoria.usuario_id == usuario_id)
    if usuario_nombre:
        # buscar usuarios por nombre y filtrar por ids
        ids = [
            u.id
            for u in Usuario.query.filter(Usuario.nombre.ilike(f"%{usuario_nombre}%"))
        ]
        if ids:
            query = query.filter(Auditoria.usuario_id.in_(ids))
        else:
            query = query.filter(Auditoria.usuario_id == None)
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
