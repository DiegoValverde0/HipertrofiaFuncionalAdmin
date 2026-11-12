"""Service layer for the interactive client segmentation & remarketing report."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import case, func, or_
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import (
    Cliente,
    HistorialPago,
    MarcajeAsistencia,
    Membresia,
    Pago,
    SeguimientoCliente,
    Venta,
)
from ..utils_timezone import format_dt_local, local_today, utcnow
from .client_service import client_search_filter, compute_age


SEGMENT_META = {
    "por_vencer": {
        "key": "por_vencer",
        "label": "Por Vencer (≤ 7d)",
        "short_label": "Por Vencer",
        "rank": 1,
        "description": "Tiene membresía vigente cuya cobertura vence entre hoy y los próximos 7 días (sin renovación futura pagada).",
        "remarketing_tip": "Recordatorio preventivo de renovación antes de que pierda continuidad.",
        "badge_class": "bg-amber-100 text-amber-800 border-amber-300",
        "row_class": "border-l-4 border-l-amber-500 bg-amber-50/25 hover:bg-amber-50/50",
        "dot_class": "bg-amber-500",
    },
    "frecuente_inactivo": {
        "key": "frecuente_inactivo",
        "label": "Frecuente Inactivo",
        "short_label": "Frecuente Inactivo",
        "rank": 2,
        "description": "Tuvo 2 o más membresías pagadas/activas en su histórico, pero actualmente no tiene cobertura vigente.",
        "remarketing_tip": "Prioridad alta de recuperación: ya conoce y confía en el gimnasio; ideal para oferta de regreso.",
        "badge_class": "bg-rose-100 text-rose-800 border-rose-300",
        "row_class": "border-l-4 border-l-rose-500 bg-rose-50/20 hover:bg-rose-50/45",
        "dot_class": "bg-rose-500",
    },
    "unica_vez": {
        "key": "unica_vez",
        "label": "Única Vez (Vencido)",
        "short_label": "Única Vez",
        "rank": 3,
        "description": "Adquirió exactamente 1 membresía en su histórico y ya caducó.",
        "remarketing_tip": "Campaña de segunda compra: preguntar experiencia y ofrecer incentivo para retomar hábito.",
        "badge_class": "bg-orange-100 text-orange-800 border-orange-300",
        "row_class": "border-l-4 border-l-orange-400 bg-orange-50/20 hover:bg-orange-50/40",
        "dot_class": "bg-orange-400",
    },
    "nunca": {
        "key": "nunca",
        "label": "Prospecto (Sin Membresía)",
        "short_label": "Nunca Adquirió",
        "rank": 4,
        "description": "Cliente registrado que nunca ha concretado una membresía pagada o activada (0 membresías válidas).",
        "remarketing_tip": "Campaña de conversión: ofrecer clase de prueba, valoración física o promo de primer mes.",
        "badge_class": "bg-slate-100 text-slate-700 border-slate-300",
        "row_class": "border-l-4 border-l-slate-300 bg-slate-50/30 hover:bg-slate-100/50",
        "dot_class": "bg-slate-400",
    },
    "activo_nuevo": {
        "key": "activo_nuevo",
        "label": "Activo Nuevo",
        "short_label": "Activo Nuevo",
        "rank": 5,
        "description": "Tiene membresía vigente (> 7 días restantes) y es su primera membresía en el histórico.",
        "remarketing_tip": "Seguimiento de adaptación (onboarding): asegurar asistencia para convertirlo en cliente frecuente.",
        "badge_class": "bg-sky-100 text-sky-800 border-sky-300",
        "row_class": "border-l-4 border-l-sky-500 bg-white hover:bg-sky-50/25",
        "dot_class": "bg-sky-500",
    },
    "activo_frecuente": {
        "key": "activo_frecuente",
        "label": "Activo Frecuente",
        "short_label": "Frecuente",
        "rank": 6,
        "description": "Cliente fiel con membresía vigente (> 7 días restantes) y 2 o más membresías adquiridas en su histórico.",
        "remarketing_tip": "Fidelización y referidos: agradecer lealtad o proponer planes de mayor plazo (trimestral/anual).",
        "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "row_class": "border-l-4 border-l-emerald-500 bg-white hover:bg-emerald-50/25",
        "dot_class": "bg-emerald-500",
    },
}

CONTACTO_META = {
    "sin_contacto": {
        "key": "sin_contacto",
        "label": "Sin contactar",
        "short_label": "Sin contacto",
        "rank": 1,
        "badge_class": "bg-slate-100 text-slate-600 border-slate-200",
        "dot_class": "bg-slate-400",
        "icon": "ti-phone-off",
        "description": "Aún no se registró ningún intento de contacto con este cliente.",
    },
    "no_contesto": {
        "key": "no_contesto",
        "label": "No contestó",
        "short_label": "No contestó",
        "rank": 2,
        "badge_class": "bg-amber-100 text-amber-800 border-amber-300",
        "dot_class": "bg-amber-500",
        "icon": "ti-phone-x",
        "description": "Se intentó contactar, pero no respondió. Conviene reintentar.",
    },
    "contactado": {
        "key": "contactado",
        "label": "Contactado",
        "short_label": "Contactado",
        "rank": 3,
        "badge_class": "bg-blue-50 text-blue-700 border-blue-200",
        "dot_class": "bg-blue-500",
        "icon": "ti-check",
        "description": "Se dejó mensaje o se realizó un primer contacto.",
    },
    "contesto": {
        "key": "contesto",
        "label": "Contestó",
        "short_label": "Contestó",
        "rank": 4,
        "badge_class": "bg-cyan-50 text-cyan-800 border-cyan-300",
        "dot_class": "bg-cyan-500",
        "icon": "ti-message-check",
        "description": "El cliente respondió al contacto y recibió la información.",
    },
    "comprometido": {
        "key": "comprometido",
        "label": "Se comprometió a volver",
        "short_label": "Comprometido",
        "rank": 5,
        "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "dot_class": "bg-emerald-500",
        "icon": "ti-heart-handshake",
        "description": "Confirmó interés y compromiso de regresar o renovar.",
    },
    "no_interesado": {
        "key": "no_interesado",
        "label": "No interesado / Pausa",
        "short_label": "No interesado",
        "rank": 6,
        "badge_class": "bg-slate-200 text-slate-700 border-slate-300",
        "dot_class": "bg-slate-500",
        "icon": "ti-ban",
        "description": "Indicó que no retomará por el momento.",
    },
}

VALID_RESULTADOS = tuple(k for k in CONTACTO_META if k != "sin_contacto")
CANALES_CONTACTO = ("Llamada", "WhatsApp", "Presencial", "Otro")

VENTANA_LABELS = {
    "por_vencer_7d": ("Por vencer (≤ 7d)", "bg-amber-50 text-amber-800 border-amber-200"),
    "reciente_7d": ("Vencido esta semana (1–7d)", "bg-amber-100 text-amber-900 border-amber-300"),
    "mes_8_30d": ("Vencido este mes (8–30d)", "bg-orange-100 text-orange-800 border-orange-300"),
    "trimestre_31_90d": ("Abandono 1–3 meses (31–90d)", "bg-rose-100 text-rose-800 border-rose-300"),
    "moroso_mas_90d": ("Moroso largo (> 90d)", "bg-red-100 text-red-900 border-red-300"),
    "activo_ok": ("Vigente (> 7d)", "bg-emerald-50 text-emerald-700 border-emerald-200"),
    "sin_membresia": ("Nunca adquirió", "bg-slate-100 text-slate-600 border-slate-200"),
}


def _normalize_phone_for_whatsapp(telefono):
    """Normaliza el número telefónico al formato internacional usado por la app (+591 por defecto)."""
    raw = (telefono or "").strip()
    if not raw:
        return ""
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned.lstrip("+")
    return f"591{cleaned}"


def build_whatsapp_message(
    nombre_completo,
    segmento_key,
    dias_vencido=None,
    dias_restantes=None,
    ultimo_plan=None,
    campana="auto",
):
    """Genera un mensaje sugerido de remarketing por WhatsApp según segmento o plantilla."""
    nombre = (nombre_completo or "").strip() or "cliente"
    plan_txt = f" ({ultimo_plan})" if ultimo_plan else ""

    if campana == "descuento_15":
        return (
            f"¡Hola {nombre}! Te saludamos de Hipertrofia Funcional. "
            f"Queremos verte entrenar de nuevo: tenemos un 15% de descuento especial "
            f"para reactivar tu membresía{plan_txt} esta semana. ¿Te reservamos tu cupo?"
        )
    if campana == "descuento_25":
        return (
            f"¡Hola {nombre}! Extrañamos verte en Hipertrofia Funcional. "
            f"Por ser parte de nuestra comunidad te ofrecemos un 25% de descuento de reactivación "
            f"en tu próximo plan. Escríbenos para activarlo hoy mismo."
        )
    if campana == "reciente":
        return (
            f"Hola {nombre}, te saludamos de Hipertrofia Funcional. "
            f"Vimos que tu membresía{plan_txt} venció recientemente. "
            f"Aún estás a tiempo de renovar manteniendo tu ritmo de entrenamiento. ¿Te ayudamos con la renovación?"
        )
    if campana == "prospecto":
        return (
            f"¡Hola {nombre}! Te saludamos de Hipertrofia Funcional. "
            f"Vimos tu registro con nosotros y queremos invitarte a iniciar tu entrenamiento "
            f"con nuestros planes vigentes. ¿Qué horario te queda más cómodo para empezar?"
        )

    if segmento_key == "por_vencer":
        detalle = "vence hoy" if dias_restantes == 0 else f"vence en {dias_restantes} día(s)"
        return (
            f"Estimado(a) {nombre}, te escribimos desde Hipertrofia Funcional para recordarte "
            f"que tu membresía{plan_txt} {detalle}. Puedes renovarla por adelantado sin perder días."
        )
    if segmento_key == "frecuente_inactivo":
        dias_txt = f" hace {dias_vencido} días" if dias_vencido is not None else ""
        return (
            f"¡Hola {nombre}! En Hipertrofia Funcional valoramos mucho tu constancia previa. "
            f"Tu última membresía{plan_txt} venció{dias_txt} y queremos darte una atención preferencial "
            f"para que retomes tus entrenamientos. ¿Conversamos?"
        )
    if segmento_key == "unica_vez":
        dias_txt = f" hace {dias_vencido} días" if dias_vencido is not None else ""
        return (
            f"¡Hola {nombre}! Te saludamos de Hipertrofia Funcional. "
            f"Tu membresía{plan_txt} finalizó{dias_txt}. Nos encantaría saber cómo te fue "
            f"y ofrecerte una promoción especial para tu segunda etapa de entrenamiento."
        )
    if segmento_key == "nunca":
        return (
            f"¡Hola {nombre}! Te saludamos de Hipertrofia Funcional. "
            f"Vimos que estás registrado(a) con nosotros pero aún no activaste tu primera membresía. "
            f"Te invitamos a conocer nuestras promociones vigentes para empezar esta semana."
        )
    if segmento_key == "activo_nuevo":
        return (
            f"¡Hola {nombre}! Te saludamos de Hipertrofia Funcional. "
            f"¿Cómo te estás sintiendo en tus primeros entrenamientos? "
            f"Cualquier consulta con tu rutina o plan, estamos para ayudarte."
        )
    return (
        f"¡Hola {nombre}! Gracias por ser parte fiel de Hipertrofia Funcional. "
        f"Cualquier consulta o si deseas conocer beneficios por renovación anticipada, estamos a tu disposición."
    )


def build_whatsapp_url(telefono, message):
    """Construye la URL de WhatsApp Web / App para el cliente."""
    phone_norm = _normalize_phone_for_whatsapp(telefono)
    if not phone_norm:
        return None
    return f"https://wa.me/{phone_norm}?text={quote(message)}"


def _build_agg_subqueries():
    """Construye subconsultas SQLAlchemy agnósticas (MySQL + SQLite) por cliente."""
    valid_cond = Membresia.estado_id.notin_([1, 3])
    non_annulled_cond = Membresia.estado_id != 3

    memb_agg = (
        db.session.query(
            Membresia.cliente_id.label("cliente_id"),
            func.sum(case((valid_cond, 1), else_=0)).label("valid_count"),
            func.sum(case((non_annulled_cond, 1), else_=0)).label("solicitudes_count"),
            func.min(case((valid_cond, Membresia.fecha_inicio), else_=None)).label(
                "primera_inicio"
            ),
            func.max(case((valid_cond, Membresia.fecha_inicio), else_=None)).label(
                "ultima_inicio"
            ),
            func.max(case((valid_cond, Membresia.fecha_fin), else_=None)).label(
                "ultima_fin"
            ),
        )
        .group_by(Membresia.cliente_id)
        .subquery("memb_agg")
    )

    hp_sub = (
        db.session.query(
            HistorialPago.pago_id.label("pago_id"),
            func.sum(HistorialPago.monto_pagado).label("abonos"),
        )
        .group_by(HistorialPago.pago_id)
        .subquery("hp_sub")
    )

    comprometido = func.coalesce(Pago.monto_total, 0)
    real_paid = case(
        (func.coalesce(hp_sub.c.abonos, 0) > 0, hp_sub.c.abonos),
        else_=comprometido,
    )

    pago_agg = (
        db.session.query(
            Membresia.cliente_id.label("cliente_id"),
            func.coalesce(func.sum(real_paid), 0).label("total_pagado_memb"),
        )
        .join(Pago, Pago.membresia_id == Membresia.id)
        .outerjoin(hp_sub, hp_sub.c.pago_id == Pago.id)
        .filter(Membresia.estado_id != 3)
        .group_by(Membresia.cliente_id)
        .subquery("pago_agg")
    )

    venta_agg = (
        db.session.query(
            Venta.cliente_id.label("cliente_id"),
            func.count(Venta.id).label("total_compras_pos"),
            func.coalesce(func.sum(Venta.monto_total), 0).label("total_pos"),
        )
        .filter(Venta.cliente_id.isnot(None))
        .group_by(Venta.cliente_id)
        .subquery("venta_agg")
    )

    asist_agg = (
        db.session.query(
            MarcajeAsistencia.cliente_id.label("cliente_id"),
            func.count(MarcajeAsistencia.id).label("total_asistencias"),
            func.max(MarcajeAsistencia.fecha_registro).label("ultima_asistencia"),
        )
        .group_by(MarcajeAsistencia.cliente_id)
        .subquery("asist_agg")
    )

    seg_max = (
        db.session.query(
            SeguimientoCliente.cliente_id.label("cliente_id"),
            func.max(SeguimientoCliente.id).label("last_id"),
            func.count(SeguimientoCliente.id).label("total_contactos"),
        )
        .group_by(SeguimientoCliente.cliente_id)
        .subquery("seg_max")
    )

    seg_agg = (
        db.session.query(
            seg_max.c.cliente_id.label("cliente_id"),
            seg_max.c.last_id.label("last_id"),
            seg_max.c.total_contactos.label("total_contactos"),
            SeguimientoCliente.resultado.label("ultimo_resultado"),
            SeguimientoCliente.canal.label("ultimo_canal"),
            SeguimientoCliente.fecha_contacto.label("ultima_fecha_contacto"),
            SeguimientoCliente.fecha_recontacto.label("fecha_recontacto"),
            SeguimientoCliente.nota.label("ultima_nota"),
        )
        .join(SeguimientoCliente, SeguimientoCliente.id == seg_max.c.last_id)
        .subquery("seg_agg")
    )

    return memb_agg, pago_agg, venta_agg, asist_agg, seg_agg


def _segment_case_expr(memb_agg, today):
    """Expresión SQL CASE mutuamente excluyente para el segmento del cliente."""
    vc = func.coalesce(memb_agg.c.valid_count, 0)
    uf = memb_agg.c.ultima_fin
    horizon = today + timedelta(days=7)

    return case(
        (or_(vc == 0, uf.is_(None)), "nunca"),
        ((uf >= today) & (uf <= horizon), "por_vencer"),
        ((uf > horizon) & (vc == 1), "activo_nuevo"),
        ((uf > horizon) & (vc >= 2), "activo_frecuente"),
        ((uf < today) & (vc == 1), "unica_vez"),
        else_="frecuente_inactivo",
    )


def _segment_rank_expr(segment_expr):
    return case(
        (segment_expr == "por_vencer", 1),
        (segment_expr == "frecuente_inactivo", 2),
        (segment_expr == "unica_vez", 3),
        (segment_expr == "nunca", 4),
        (segment_expr == "activo_nuevo", 5),
        else_=6,
    )


def _ventana_expr(memb_agg, today):
    """Expresión SQL CASE para agrupar por ventana temporal de vencimiento/vigencia."""
    vc = func.coalesce(memb_agg.c.valid_count, 0)
    uf = memb_agg.c.ultima_fin
    horizon = today + timedelta(days=7)
    d1 = today - timedelta(days=1)
    d7 = today - timedelta(days=7)
    d8 = today - timedelta(days=8)
    d30 = today - timedelta(days=30)
    d31 = today - timedelta(days=31)
    d90 = today - timedelta(days=90)

    return case(
        (or_(vc == 0, uf.is_(None)), "sin_membresia"),
        ((uf >= today) & (uf <= horizon), "por_vencer_7d"),
        (uf > horizon, "activo_ok"),
        ((uf <= d1) & (uf >= d7), "reciente_7d"),
        ((uf <= d8) & (uf >= d30), "mes_8_30d"),
        ((uf <= d31) & (uf >= d90), "trimestre_31_90d"),
        else_="moroso_mas_90d",
    )


def _ventana_rank_expr(ventana_expr):
    return case(
        (ventana_expr == "por_vencer_7d", 1),
        (ventana_expr == "reciente_7d", 2),
        (ventana_expr == "mes_8_30d", 3),
        (ventana_expr == "trimestre_31_90d", 4),
        (ventana_expr == "moroso_mas_90d", 5),
        (ventana_expr == "sin_membresia", 6),
        else_=7,
    )


def _contacto_expr(seg_agg):
    return case(
        (seg_agg.c.last_id.is_(None), "sin_contacto"),
        else_=func.coalesce(seg_agg.c.ultimo_resultado, "contactado"),
    )


def _contacto_rank_expr(contacto_expr):
    return case(
        (contacto_expr == "sin_contacto", 1),
        (contacto_expr == "no_contesto", 2),
        (contacto_expr == "contactado", 3),
        (contacto_expr == "contesto", 4),
        (contacto_expr == "comprometido", 5),
        else_=6,
    )


def _apply_report_filters(
    query,
    filters,
    memb_agg,
    seg_agg,
    segment_expr,
    contacto_expr,
    today,
    sucursal_id=None,
):
    """Aplica todos los filtros dinámicos de forma segura sobre la consulta."""
    if sucursal_id and sucursal_id > 0:
        query = query.filter(Cliente.sucursal_id == sucursal_id)

    q = (filters.get("q") or "").strip()
    if q:
        query = query.filter(client_search_filter(q))

    tipo = (filters.get("tipo") or "").strip()
    if tipo in ("Individual", "Corporativo"):
        query = query.filter(Cliente.tipo_cliente == tipo)

    vc = func.coalesce(memb_agg.c.valid_count, 0)
    uf = memb_agg.c.ultima_fin

    segmento = (filters.get("segmento") or "").strip()
    if segmento in SEGMENT_META:
        query = query.filter(segment_expr == segmento)
    elif segmento == "vencidos_todos":
        query = query.filter(vc > 0, uf.isnot(None), uf < today)
    elif segmento == "activos_todos":
        query = query.filter(vc > 0, uf.isnot(None), uf >= today)

    ventana = (filters.get("ventana") or "").strip()
    if ventana == "vence_hoy":
        query = query.filter(vc > 0, uf == today)
    elif ventana == "ayer":
        query = query.filter(vc > 0, uf == (today - timedelta(days=1)))
    elif ventana == "semana":
        query = query.filter(
            vc > 0, uf <= (today - timedelta(days=1)), uf >= (today - timedelta(days=7))
        )
    elif ventana == "mes":
        query = query.filter(
            vc > 0, uf <= (today - timedelta(days=8)), uf >= (today - timedelta(days=30))
        )
    elif ventana == "reciente_30d":
        query = query.filter(
            vc > 0, uf <= (today - timedelta(days=1)), uf >= (today - timedelta(days=30))
        )
    elif ventana == "trimestre":
        query = query.filter(
            vc > 0, uf <= (today - timedelta(days=31)), uf >= (today - timedelta(days=90))
        )
    elif ventana == "mas_90d":
        query = query.filter(vc > 0, uf < (today - timedelta(days=90)))
    elif ventana == "por_vencer_7d":
        query = query.filter(vc > 0, uf >= today, uf <= (today + timedelta(days=7)))
    elif ventana == "sin_membresia":
        query = query.filter(or_(vc == 0, uf.is_(None)))
    elif ventana == "personalizado":
        dias_min = filters.get("dias_min")
        dias_max = filters.get("dias_max")
        if dias_min is not None or dias_max is not None:
            query = query.filter(vc > 0, uf.isnot(None))
            if dias_min is not None:
                query = query.filter(uf <= (today - timedelta(days=max(0, dias_min))))
            if dias_max is not None:
                query = query.filter(uf >= (today - timedelta(days=max(0, dias_max))))

    historial = (filters.get("historial") or "").strip()
    if historial == "0":
        query = query.filter(vc == 0)
    elif historial == "1":
        query = query.filter(vc == 1)
    elif historial == "2_3":
        query = query.filter(vc >= 2, vc <= 3)
    elif historial == "4_plus":
        query = query.filter(vc >= 4)

    contacto = (filters.get("contacto") or "").strip()
    if contacto in CONTACTO_META:
        query = query.filter(contacto_expr == contacto)
    elif contacto == "contactado_reciente":
        cutoff_7d = datetime.combine(today - timedelta(days=7), time.min)
        query = query.filter(
            seg_agg.c.last_id.isnot(None),
            seg_agg.c.ultima_fecha_contacto >= cutoff_7d,
        )
    elif contacto == "requiere_recontacto":
        cutoff_2d = datetime.combine(today - timedelta(days=2), time.max)
        query = query.filter(
            or_(
                (seg_agg.c.fecha_recontacto.isnot(None) & (seg_agg.c.fecha_recontacto <= today)),
                (
                    (seg_agg.c.ultimo_resultado == "no_contesto")
                    & (seg_agg.c.ultima_fecha_contacto <= cutoff_2d)
                ),
                (
                    seg_agg.c.last_id.is_(None)
                    & segment_expr.in_(["por_vencer", "frecuente_inactivo", "unica_vez", "nunca"])
                ),
            )
        )

    return query


def _apply_report_sorting(
    query,
    sort_by,
    sort_dir,
    agrupar,
    memb_agg,
    pago_agg,
    venta_agg,
    asist_agg,
    seg_agg,
    segment_rank_expr,
    ventana_rank_expr,
    contacto_rank_expr,
):
    """Aplica ordenamiento dinámico (y agrupación prioritaria si está activa) compatible MySQL/SQLite."""
    order_clauses = []

    if agrupar == "segmento":
        order_clauses.append(segment_rank_expr.asc())
    elif agrupar == "ventana":
        order_clauses.append(ventana_rank_expr.asc())
    elif agrupar == "contacto":
        order_clauses.append(contacto_rank_expr.asc())

    is_desc = (sort_dir or "").lower() == "desc"
    vc_col = func.coalesce(memb_agg.c.valid_count, 0)
    uf_col = memb_agg.c.ultima_fin
    ui_col = memb_agg.c.ultima_inicio
    ltv_col = func.coalesce(pago_agg.c.total_pagado_memb, 0) + func.coalesce(
        venta_agg.c.total_pos, 0
    )
    ua_col = asist_agg.c.ultima_asistencia
    uc_col = seg_agg.c.ultima_fecha_contacto
    fr_col = seg_agg.c.fecha_recontacto

    if sort_by == "nombre":
        if is_desc:
            order_clauses.extend([Cliente.nombre.desc(), Cliente.apellido.desc()])
        else:
            order_clauses.extend([Cliente.nombre.asc(), Cliente.apellido.asc()])
    elif sort_by == "membresias":
        order_clauses.append(vc_col.desc() if is_desc else vc_col.asc())
    elif sort_by == "ultima_compra":
        order_clauses.append(case((ui_col.is_(None), 1), else_=0).asc())
        order_clauses.append(ui_col.desc() if is_desc else ui_col.asc())
    elif sort_by == "fecha_caducidad":
        order_clauses.append(case((uf_col.is_(None), 1), else_=0).asc())
        order_clauses.append(uf_col.desc() if is_desc else uf_col.asc())
    elif sort_by == "segmento":
        order_clauses.append(segment_rank_expr.desc() if is_desc else segment_rank_expr.asc())
    elif sort_by == "ltv":
        order_clauses.append(ltv_col.desc() if is_desc else ltv_col.asc())
    elif sort_by == "ultima_asistencia":
        order_clauses.append(case((ua_col.is_(None), 1), else_=0).asc())
        order_clauses.append(ua_col.desc() if is_desc else ua_col.asc())
    elif sort_by == "ultimo_contacto":
        order_clauses.append(case((uc_col.is_(None), 1), else_=0).asc())
        order_clauses.append(uc_col.desc() if is_desc else uc_col.asc())
    elif sort_by == "fecha_recontacto":
        order_clauses.append(case((fr_col.is_(None), 1), else_=0).asc())
        order_clauses.append(fr_col.desc() if is_desc else fr_col.asc())
    else:
        order_clauses.append(case((uf_col.is_(None), 1), else_=0).asc())
        order_clauses.append(uf_col.asc() if is_desc else uf_col.desc())

    order_clauses.append(Cliente.id.asc())
    return query.order_by(*order_clauses)


def _compute_kpis(sucursal_id, today):
    """Calcula KPIs de segmentación y métricas de seguimiento/contacto de la sucursal."""
    memb_agg, _, _, _, seg_agg = _build_agg_subqueries()
    segment_expr = _segment_case_expr(memb_agg, today)
    contacto_expr = _contacto_expr(seg_agg)
    vc = func.coalesce(memb_agg.c.valid_count, 0)
    uf = memb_agg.c.ultima_fin
    cutoff_7d = datetime.combine(today - timedelta(days=7), time.min)
    cutoff_2d = datetime.combine(today - timedelta(days=2), time.max)

    requiere_recontacto_cond = or_(
        (seg_agg.c.fecha_recontacto.isnot(None) & (seg_agg.c.fecha_recontacto <= today)),
        (
            (seg_agg.c.ultimo_resultado == "no_contesto")
            & (seg_agg.c.ultima_fecha_contacto <= cutoff_2d)
        ),
        (
            seg_agg.c.last_id.is_(None)
            & segment_expr.in_(["por_vencer", "frecuente_inactivo", "unica_vez", "nunca"])
        ),
    )

    q = (
        db.session.query(
            func.count(Cliente.id).label("total"),
            func.sum(case((segment_expr == "nunca", 1), else_=0)).label("nunca"),
            func.sum(case((segment_expr == "por_vencer", 1), else_=0)).label("por_vencer"),
            func.sum(case((segment_expr == "frecuente_inactivo", 1), else_=0)).label(
                "frecuente_inactivo"
            ),
            func.sum(
                case(
                    (
                        (vc > 0)
                        & uf.isnot(None)
                        & (uf <= (today - timedelta(days=1)))
                        & (uf >= (today - timedelta(days=30))),
                        1,
                    ),
                    else_=0,
                )
            ).label("vencidos_30d"),
            func.sum(
                case(
                    (
                        (vc > 0) & uf.isnot(None) & (uf < (today - timedelta(days=90))),
                        1,
                    ),
                    else_=0,
                )
            ).label("morosos_90d"),
            func.sum(case((contacto_expr == "sin_contacto", 1), else_=0)).label("sin_contacto"),
            func.sum(case((contacto_expr == "no_contesto", 1), else_=0)).label("no_contesto"),
            func.sum(case((contacto_expr == "contesto", 1), else_=0)).label("contesto"),
            func.sum(case((contacto_expr == "comprometido", 1), else_=0)).label("comprometido"),
            func.sum(
                case(
                    (
                        seg_agg.c.last_id.isnot(None)
                        & (seg_agg.c.ultima_fecha_contacto >= cutoff_7d),
                        1,
                    ),
                    else_=0,
                )
            ).label("contactados_7d"),
            func.sum(case((requiere_recontacto_cond, 1), else_=0)).label("requiere_recontacto"),
        )
        .outerjoin(memb_agg, memb_agg.c.cliente_id == Cliente.id)
        .outerjoin(seg_agg, seg_agg.c.cliente_id == Cliente.id)
    )
    if sucursal_id and sucursal_id > 0:
        q = q.filter(Cliente.sucursal_id == sucursal_id)

    row = q.first()
    total = int(getattr(row, "total", 0) or 0)
    contactados_total = total - int(getattr(row, "sin_contacto", 0) or 0)
    respuestas_positivas = int(getattr(row, "contesto", 0) or 0) + int(
        getattr(row, "comprometido", 0) or 0
    )
    tasa_respuesta = (
        round((respuestas_positivas / contactados_total) * 100)
        if contactados_total > 0
        else 0
    )

    return {
        "total": total,
        "nunca": int(getattr(row, "nunca", 0) or 0),
        "por_vencer": int(getattr(row, "por_vencer", 0) or 0),
        "frecuente_inactivo": int(getattr(row, "frecuente_inactivo", 0) or 0),
        "vencidos_30d": int(getattr(row, "vencidos_30d", 0) or 0),
        "morosos_90d": int(getattr(row, "morosos_90d", 0) or 0),
        "sin_contacto": int(getattr(row, "sin_contacto", 0) or 0),
        "no_contesto": int(getattr(row, "no_contesto", 0) or 0),
        "contesto": int(getattr(row, "contesto", 0) or 0),
        "comprometido": int(getattr(row, "comprometido", 0) or 0),
        "contactados_7d": int(getattr(row, "contactados_7d", 0) or 0),
        "requiere_recontacto": int(getattr(row, "requiere_recontacto", 0) or 0),
        "tasa_respuesta": tasa_respuesta,
    }


def _fetch_latest_plans_map(client_ids):
    """Obtiene el último plan contratado por cliente en una sola consulta ligera para la página actual."""
    if not client_ids:
        return {}
    rows = (
        Membresia.query.options(joinedload(Membresia.plan))
        .filter(Membresia.cliente_id.in_(client_ids), Membresia.estado_id.notin_([1, 3]))
        .order_by(Membresia.fecha_fin.desc(), Membresia.id.desc())
        .all()
    )
    out = {}
    for m in rows:
        if m.cliente_id not in out:
            out[m.cliente_id] = m.plan.nombre if m.plan else None
    return out


def _format_inactivity_badge(valid_count, ultima_fin, fecha_registro, today):
    """Construye el texto y estilo del contador de caducidad / inactividad."""
    if not valid_count or not ultima_fin:
        if fecha_registro:
            reg_days = max(0, (today - fecha_registro).days)
            return {
                "text": f"Reg. hace {reg_days} d",
                "subtext": "Sin compras",
                "badge_class": "bg-slate-100 text-slate-600 border-slate-200",
                "dias_vencido": None,
                "dias_restantes": None,
            }
        return {
            "text": "Sin compras",
            "subtext": "",
            "badge_class": "bg-slate-100 text-slate-600 border-slate-200",
            "dias_vencido": None,
            "dias_restantes": None,
        }

    diff = (today - ultima_fin).days
    if diff > 0:
        txt = "Venció ayer (1 d)" if diff == 1 else f"Hace {diff} días"
        if diff <= 7:
            cls = "bg-amber-100 text-amber-800 border-amber-300"
        elif diff <= 30:
            cls = "bg-orange-100 text-orange-800 border-orange-300"
        elif diff <= 90:
            cls = "bg-rose-100 text-rose-800 border-rose-300"
        else:
            cls = "bg-red-100 text-red-900 border-red-300"
        return {
            "text": txt,
            "subtext": "Sin membresía activa",
            "badge_class": cls,
            "dias_vencido": diff,
            "dias_restantes": None,
        }

    remaining = abs(diff)
    if remaining == 0:
        txt = "Vence hoy"
        cls = "bg-amber-100 text-amber-800 border-amber-300"
    elif remaining <= 7:
        txt = f"Vence en {remaining} d"
        cls = "bg-amber-50 text-amber-700 border-amber-200"
    else:
        txt = f"Vigente ({remaining} d)"
        cls = "bg-emerald-50 text-emerald-700 border-emerald-200"
    return {
        "text": txt,
        "subtext": "Cobertura activa",
        "badge_class": cls,
        "dias_vencido": None,
        "dias_restantes": remaining,
    }


def _format_contact_info(raw, today):
    """Prepara la información visual del último seguimiento del cliente."""
    contacto_key = raw.contacto_key or "sin_contacto"
    meta = CONTACTO_META.get(contacto_key, CONTACTO_META["sin_contacto"])
    ultima_fecha = raw.ultima_fecha_contacto
    fecha_recontacto = raw.fecha_recontacto
    total_contactos = int(raw.total_contactos or 0)

    fecha_texto = None
    dias_desde_contacto = None
    if ultima_fecha:
        fecha_texto = format_dt_local(ultima_fecha, "%d/%m %H:%M")
        u_date = ultima_fecha.date() if hasattr(ultima_fecha, "date") else ultima_fecha
        dias_desde_contacto = max(0, (today - u_date).days)

    recontacto_vencido = bool(fecha_recontacto and fecha_recontacto <= today)
    return {
        "key": contacto_key,
        "meta": meta,
        "canal": raw.ultimo_canal,
        "fecha_dt": ultima_fecha,
        "fecha_texto": fecha_texto,
        "dias_desde_contacto": dias_desde_contacto,
        "fecha_recontacto": fecha_recontacto,
        "recontacto_vencido": recontacto_vencido,
        "nota": raw.ultima_nota,
        "total_contactos": total_contactos,
    }


def register_client_contact(
    cliente_id,
    resultado,
    canal="Llamada",
    nota=None,
    fecha_recontacto=None,
    usuario_id=None,
):
    """Registra un contacto o resultado de seguimiento en la base de datos."""
    cliente = db.session.get(Cliente, cliente_id)
    if not cliente:
        return False, None, "Cliente no encontrado"

    resultado_clean = (resultado or "").strip().lower()
    if resultado_clean not in VALID_RESULTADOS:
        return False, None, "Resultado de contacto inválido"

    canal_clean = (canal or "Llamada").strip()
    if canal_clean not in CANALES_CONTACTO:
        canal_clean = "Otro"

    nota_clean = (nota or "").strip()[:255] or None

    parsed_recontacto = None
    if fecha_recontacto:
        if hasattr(fecha_recontacto, "year"):
            parsed_recontacto = fecha_recontacto
        else:
            try:
                parsed_recontacto = datetime.strptime(str(fecha_recontacto).strip(), "%Y-%m-%d").date()
            except ValueError:
                return False, None, "Fecha de recontacto inválida"

    seg = SeguimientoCliente(
        cliente_id=cliente.id,
        sucursal_id=cliente.sucursal_id,
        usuario_id=usuario_id,
        canal=canal_clean,
        resultado=resultado_clean,
        fecha_contacto=utcnow(),
        fecha_recontacto=parsed_recontacto,
        nota=nota_clean,
    )
    db.session.add(seg)
    db.session.commit()
    return True, seg, None


def get_client_contact_history(cliente_id, limit=10):
    """Devuelve el historial reciente de contactos de un cliente para el modal de detalle."""
    rows = (
        SeguimientoCliente.query.options(joinedload(SeguimientoCliente.usuario))
        .filter_by(cliente_id=cliente_id)
        .order_by(SeguimientoCliente.fecha_contacto.desc(), SeguimientoCliente.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for s in rows:
        meta = CONTACTO_META.get(s.resultado, CONTACTO_META["contactado"])
        out.append(
            {
                "id": s.id,
                "canal": s.canal,
                "resultado": s.resultado,
                "resultado_label": meta["label"],
                "badge_class": meta["badge_class"],
                "fecha_contacto": format_dt_local(s.fecha_contacto, "%d/%m/%Y %H:%M")
                if s.fecha_contacto
                else "",
                "fecha_recontacto": s.fecha_recontacto.strftime("%Y-%m-%d")
                if s.fecha_recontacto
                else None,
                "fecha_recontacto_fmt": s.fecha_recontacto.strftime("%d/%m/%Y")
                if s.fecha_recontacto
                else None,
                "nota": s.nota or "",
                "usuario": s.usuario.nombre if s.usuario and s.usuario.nombre else "Sistema",
            }
        )
    return out


def get_client_report_data(filters, sucursal_id=None, page=1, per_page=25, today=None):
    """Ejecuta la consulta paginada del informe de clientes y prepara datos listos para la vista."""
    today = today or local_today()
    per_page = per_page if per_page in (15, 25, 50, 100) else 25
    page = max(1, int(page or 1))

    memb_agg, pago_agg, venta_agg, asist_agg, seg_agg = _build_agg_subqueries()
    segment_expr = _segment_case_expr(memb_agg, today)
    segment_rank_expr = _segment_rank_expr(segment_expr)
    ventana_expr = _ventana_expr(memb_agg, today)
    ventana_rank_expr = _ventana_rank_expr(ventana_expr)
    contacto_expr = _contacto_expr(seg_agg)
    contacto_rank_expr = _contacto_rank_expr(contacto_expr)

    query = (
        db.session.query(
            Cliente,
            func.coalesce(memb_agg.c.valid_count, 0).label("valid_count"),
            func.coalesce(memb_agg.c.solicitudes_count, 0).label("solicitudes_count"),
            memb_agg.c.primera_inicio.label("primera_inicio"),
            memb_agg.c.ultima_inicio.label("ultima_inicio"),
            memb_agg.c.ultima_fin.label("ultima_fin"),
            func.coalesce(pago_agg.c.total_pagado_memb, 0).label("total_pagado_memb"),
            func.coalesce(venta_agg.c.total_compras_pos, 0).label("total_compras_pos"),
            func.coalesce(venta_agg.c.total_pos, 0).label("total_pos"),
            func.coalesce(asist_agg.c.total_asistencias, 0).label("total_asistencias"),
            asist_agg.c.ultima_asistencia.label("ultima_asistencia"),
            func.coalesce(seg_agg.c.total_contactos, 0).label("total_contactos"),
            seg_agg.c.ultimo_canal.label("ultimo_canal"),
            seg_agg.c.ultima_fecha_contacto.label("ultima_fecha_contacto"),
            seg_agg.c.fecha_recontacto.label("fecha_recontacto"),
            seg_agg.c.ultima_nota.label("ultima_nota"),
            contacto_expr.label("contacto_key"),
            segment_expr.label("segmento_key"),
            ventana_expr.label("ventana_key"),
        )
        .outerjoin(memb_agg, memb_agg.c.cliente_id == Cliente.id)
        .outerjoin(pago_agg, pago_agg.c.cliente_id == Cliente.id)
        .outerjoin(venta_agg, venta_agg.c.cliente_id == Cliente.id)
        .outerjoin(asist_agg, asist_agg.c.cliente_id == Cliente.id)
        .outerjoin(seg_agg, seg_agg.c.cliente_id == Cliente.id)
    )

    query = _apply_report_filters(
        query,
        filters,
        memb_agg,
        seg_agg,
        segment_expr,
        contacto_expr,
        today,
        sucursal_id=sucursal_id,
    )

    sort_by = (filters.get("sort") or "dias_sin_membresia").strip()
    sort_dir = (filters.get("dir") or "asc").strip()
    agrupar = (filters.get("agrupar") or "").strip()

    query = _apply_report_sorting(
        query,
        sort_by=sort_by,
        sort_dir=sort_dir,
        agrupar=agrupar,
        memb_agg=memb_agg,
        pago_agg=pago_agg,
        venta_agg=venta_agg,
        asist_agg=asist_agg,
        seg_agg=seg_agg,
        segment_rank_expr=segment_rank_expr,
        ventana_rank_expr=ventana_rank_expr,
        contacto_rank_expr=contacto_rank_expr,
    )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    visible_ids = [row[0].id for row in pagination.items]
    latest_plans = _fetch_latest_plans_map(visible_ids)
    campana = (filters.get("campana") or "auto").strip()

    rows = []
    for raw in pagination.items:
        cliente = raw[0]
        valid_count = int(raw.valid_count or 0)
        solicitudes_count = int(raw.solicitudes_count or 0)
        ultima_fin = raw.ultima_fin
        ultima_inicio = raw.ultima_inicio
        total_pagado = float(Decimal(str(raw.total_pagado_memb or 0)))
        total_pos = float(Decimal(str(raw.total_pos or 0)))
        ltv = round(total_pagado + total_pos, 2)
        total_asistencias = int(raw.total_asistencias or 0)
        ultima_asistencia = raw.ultima_asistencia
        segmento_key = raw.segmento_key
        ventana_key = raw.ventana_key

        seg_meta = SEGMENT_META.get(segmento_key, SEGMENT_META["nunca"])
        vent_label, vent_badge = VENTANA_LABELS.get(
            ventana_key, ("Sin clasificar", "bg-slate-100 text-slate-600 border-slate-200")
        )
        ultimo_plan = latest_plans.get(cliente.id)
        counter = _format_inactivity_badge(
            valid_count, ultima_fin, cliente.fecha_registro, today
        )
        contacto_info = _format_contact_info(raw, today)

        nombre_completo = f"{cliente.nombre or ''} {cliente.apellido or ''}".strip()
        wa_msg = build_whatsapp_message(
            nombre_completo=nombre_completo,
            segmento_key=segmento_key,
            dias_vencido=counter["dias_vencido"],
            dias_restantes=counter["dias_restantes"],
            ultimo_plan=ultimo_plan,
            campana=campana,
        )
        wa_url = build_whatsapp_url(cliente.telefono, wa_msg)

        dias_sin_asistir = None
        if ultima_asistencia:
            u_date = (
                ultima_asistencia.date()
                if hasattr(ultima_asistencia, "date")
                else ultima_asistencia
            )
            dias_sin_asistir = max(0, (today - u_date).days)

        pendientes_extra = max(0, solicitudes_count - valid_count)

        rows.append(
            {
                "cliente": cliente,
                "nombre_completo": nombre_completo,
                "edad": compute_age(cliente.fecha_nacimiento),
                "valid_count": valid_count,
                "pendientes_extra": pendientes_extra,
                "ultimo_plan": ultimo_plan,
                "ultima_inicio": ultima_inicio,
                "ultima_fin": ultima_fin,
                "segmento_key": segmento_key,
                "segmento": seg_meta,
                "ventana_key": ventana_key,
                "ventana_label": vent_label,
                "ventana_badge": vent_badge,
                "counter": counter,
                "contacto": contacto_info,
                "total_pagado": round(total_pagado, 2),
                "ltv": ltv,
                "total_compras_pos": int(raw.total_compras_pos or 0),
                "total_asistencias": total_asistencias,
                "ultima_asistencia": ultima_asistencia,
                "dias_sin_asistir": dias_sin_asistir,
                "wa_message": wa_msg,
                "wa_url": wa_url,
            }
        )

    kpis = _compute_kpis(sucursal_id, today)

    return {
        "rows": rows,
        "pagination": pagination,
        "kpis": kpis,
        "today": today,
        "segment_meta": SEGMENT_META,
        "contacto_meta": CONTACTO_META,
    }
