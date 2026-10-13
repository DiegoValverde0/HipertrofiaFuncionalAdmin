from datetime import datetime, date
from .extensions import db

try:
    from flask_login import UserMixin
except Exception:
    # fallback cuando flask-login no está instalado (permite importar modelos)
    class UserMixin:
        pass


from flask import session
from sqlalchemy import event
from sqlalchemy.orm.attributes import get_history
import json
from flask import g

try:
    from flask_login import current_user
except Exception:
    current_user = None


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    usuarios = db.relationship("Usuario", backref="rol", lazy=True)

    def __repr__(self):
        return f"<Role {self.nombre}>"


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    correo = db.Column(db.String(150), unique=True)
    contrasena = db.Column(db.String(255))
    rol_id = db.Column(db.Integer, db.ForeignKey("roles.id"))
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=True)
    estado = db.Column(db.Boolean, default=True)

    gastos = db.relationship("Gasto", backref="usuario", lazy=True)
    ventas = db.relationship("Venta", backref="usuario", lazy=True)
    auditorias = db.relationship("Auditoria", backref="usuario", lazy=True)
    api_keys = db.relationship(
        "APIKey", backref="usuario", lazy=True, cascade="all, delete-orphan"
    )

    # Compatibilidad con flask-login y con el fallback de autenticación
    def get_id(self):
        try:
            return str(self.id)
        except Exception:
            return None

    @property
    def is_authenticated(self):
        # un usuario persistido se considera autenticado en el fallback
        return True

    def is_active(self):
        return bool(self.estado)

    def is_anonymous(self):
        return False

    def __repr__(self):
        return f"<Usuario {self.correo}>"


class APIKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_uso = db.Column(db.DateTime, nullable=True)

    sucursal = db.relationship("Sucursal", backref="api_keys")

    def __repr__(self):
        return f"<APIKey {self.nombre} usuario_id={self.usuario_id}>"


class Sucursal(db.Model):
    __tablename__ = "sucursales"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    direccion = db.Column(db.String(255))
    telefono = db.Column(db.String(20))
    estado = db.Column(db.String(20), default="Activo")

    clientes = db.relationship("Cliente", backref="sucursal", lazy=True)
    membresias = db.relationship("Membresia", backref="sucursal", lazy=True)
    # Relación al objeto de asociación Inventario
    inventarios = db.relationship(
        "Inventario", back_populates="sucursal", cascade="all, delete-orphan"
    )
    pagos = db.relationship("Pago", backref="sucursal", lazy=True)
    ventas = db.relationship("Venta", backref="sucursal", lazy=True)
    gastos = db.relationship("Gasto", backref="sucursal", lazy=True)
    notificaciones = db.relationship("Notificacion", backref="sucursal", lazy=True)
    usuarios = db.relationship("Usuario", backref="sucursal", lazy=True)

    def __repr__(self):
        return f"<Sucursal {self.nombre}>"


class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    apellido = db.Column(db.String(100))
    correo = db.Column(db.String(150), unique=True)
    telefono = db.Column(db.String(20), unique=True)
    fecha_registro = db.Column(db.Date, default=date.today)
    fecha_nacimiento = db.Column(db.Date)
    estado = db.Column(db.String(20), default="Activo", nullable=False)
    tipo_cliente = db.Column(db.String(20), default="Individual", nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)

    membresias = db.relationship("Membresia", backref="cliente", lazy=True)
    pagos = db.relationship("Pago", backref="cliente", lazy=True)
    ventas = db.relationship("Venta", backref="cliente", lazy=True)
    notificaciones = db.relationship("Notificacion", backref="cliente", lazy=True)

    def __repr__(self):
        return f"<Cliente {self.nombre} {self.apellido}>"


class Plan(db.Model):
    __tablename__ = "planes"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    duracion = db.Column(db.String(20), nullable=False)
    duracion_tipo = db.Column(db.String(20), nullable=False, default="meses")
    duracion_valor = db.Column(db.Integer, nullable=False, default=1)
    tipo_uso = db.Column(db.String(30), nullable=False, default="tiempo")
    cupo_marcajes = db.Column(db.Integer, nullable=True)
    precio = db.Column(db.Numeric(10, 2), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    fecha_creacion = db.Column(
        db.DateTime, default=datetime.utcnow, server_default=None
    )
    estado = db.Column(db.String(10), default="Activo", nullable=False)

    membresias = db.relationship("Membresia", backref="plan", lazy=True)

    def __repr__(self):
        return f"<Plan {self.nombre}>"


class Promocion(db.Model):
    __tablename__ = "promociones"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    descuento = db.Column(db.Numeric(5, 2))
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    estado = db.Column(db.String(20), default="Activo")

    membresias = db.relationship("Membresia", backref="promocion", lazy=True)

    def __repr__(self):
        return f"<Promocion {self.nombre}>"


class EstadoMembresia(db.Model):
    __tablename__ = "estados_membresias"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50))

    membresias = db.relationship("Membresia", backref="estado_membresia", lazy=True)

    def __repr__(self):
        return f"<EstadoMembresia {self.nombre}>"


class Membresia(db.Model):
    __tablename__ = "membresias"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes.id"), nullable=False)
    promocion_id = db.Column(db.Integer, db.ForeignKey("promociones.id"), nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    estado_id = db.Column(db.Integer, db.ForeignKey("estados_membresias.id"))
    tipo_uso = db.Column(db.String(30), nullable=False, default="tiempo")
    cupo_marcajes = db.Column(db.Integer, nullable=True)
    marcajes_usados = db.Column(db.Integer, nullable=False, default=0)
    
    # NUEVO: Registrar si fue 'new' o 'extend' para auditoría e intención
    tipo_creacion = db.Column(
        db.String(10), 
        default='new',
        nullable=False,
        comment="'new' = nueva membresía, 'extend' = extensión de anterior"
    )

    pagos = db.relationship("Pago", backref="membresia", lazy=True)
    marcajes_asistencia = db.relationship(
        "MarcajeAsistencia",
        backref="membresia",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Membresia {self.id} cliente={self.cliente_id}>"

    @property
    def is_activa(self):
        try:
            return self.estado_membresia and self.estado_membresia.nombre.lower().startswith("activ")
        except Exception:
            return self.estado_id == 2

    @property
    def is_pendiente(self):
        try:
            return self.estado_membresia and self.estado_membresia.nombre.lower().startswith("pendient")
        except Exception:
            return self.estado_id == 1

    @property
    def is_en_espera(self):
        try:
            return self.estado_membresia and "espera" in self.estado_membresia.nombre.lower()
        except Exception:
            return self.estado_id == 5

    @property
    def is_anulada(self):
        try:
            return self.estado_membresia and self.estado_membresia.nombre.lower().startswith("anulad")
        except Exception:
            return self.estado_id == 3

    @property
    def is_inactiva(self):
        try:
            return self.estado_membresia and self.estado_membresia.nombre.lower().startswith("inactiv")
        except Exception:
            return self.estado_id == 4

    @property
    def is_manual_asistencia(self):
        try:
            return (self.tipo_uso or "").lower() == "asistencia_manual"
        except Exception:
            return False


# Asignar automáticamente la sucursal actual desde la sesión si no se proporciona
def _assign_sucursal_from_session(mapper, connection, target):
    """
    Listener antes de insertar que asigna `sucursal_id` desde la session
    (clave 'sucursal_id') si el objeto no tiene `sucursal_id`.
    Se envuelve en try/except para ignorar cuando no haya contexto de request.
    """
    try:
        # sólo asignar si no está definido o es None
        if getattr(target, "sucursal_id", None) in (None, 0):
            suc = session.get("sucursal_id")
            if suc:
                try:
                    target.sucursal_id = int(suc)
                except Exception:
                    target.sucursal_id = suc
    except RuntimeError:
        # No hay contexto de Flask (por ejemplo en scripts fuera de request)
        pass


class Pago(db.Model):
    __tablename__ = "pagos"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    membresia_id = db.Column(db.Integer, db.ForeignKey("membresias.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    monto_total = db.Column(db.Numeric(10, 2))
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    metodo_pago = db.Column(db.String(20))
    comentarios = db.Column(db.String(255))

    historial = db.relationship(
        "HistorialPago", back_populates="pago", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Pago {self.id} monto={self.monto_total}>"


class HistorialPago(db.Model):
    __tablename__ = "historial_pagos"
    id = db.Column(db.Integer, primary_key=True)
    pago_id = db.Column(db.Integer, db.ForeignKey("pagos.id"), nullable=False)
    monto_pagado = db.Column(db.Numeric(10, 2), nullable=False)
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    metodo_pago = db.Column(db.String(50))
    comentarios = db.Column(db.String(255))

    pago = db.relationship("Pago", back_populates="historial")

    def __repr__(self):
        return f"<HistorialPago pago_id={self.pago_id} monto={self.monto_pagado}>"


class MarcajeAsistencia(db.Model):
    __tablename__ = "marcajes_asistencia"
    id = db.Column(db.Integer, primary_key=True)
    membresia_id = db.Column(db.Integer, db.ForeignKey("membresias.id"), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    tipo_registro = db.Column(db.String(20), nullable=False, default="manual")
    observacion = db.Column(db.String(255), nullable=True)

    cliente = db.relationship("Cliente", backref="marcajes_asistencia")
    sucursal = db.relationship("Sucursal", backref="marcajes_asistencia")
    usuario = db.relationship("Usuario", backref="marcajes_asistencia")

    def __repr__(self):
        return f"<MarcajeAsistencia membresia_id={self.membresia_id} fecha={self.fecha_registro}>"


class Cuenta(db.Model):
    __tablename__ = "cuentas"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True)

    gastos = db.relationship("Gasto", backref="cuenta", lazy=True)

    def __repr__(self):
        return f"<Cuenta {self.nombre}>"


class CategoriaGasto(db.Model):
    __tablename__ = "categorias_gasto"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50))

    gastos = db.relationship("Gasto", backref="categoria", lazy=True)

    def __repr__(self):
        return f"<CategoriaGasto {self.nombre}>"


class Gasto(db.Model):
    __tablename__ = "gastos"
    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(255))
    monto = db.Column(db.Numeric(10, 2))
    fecha_gasto = db.Column(db.DateTime, default=datetime.utcnow)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias_gasto.id"))
    cuenta_id = db.Column(db.Integer, db.ForeignKey("cuentas.id"))
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    comentarios = db.Column(db.String(255))

    def __repr__(self):
        return f"<Gasto {self.id} monto={self.monto}>"


class Inventario(db.Model):
    __tablename__ = "inventario"
    __table_args__ = (
        db.UniqueConstraint(
            "producto_id", "sucursal_id", name="uq_inventario_producto_sucursal"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    cantidad = db.Column(db.Integer, default=0)

    # Relaciones con back_populates para eliminar ambigüedad
    sucursal = db.relationship("Sucursal", back_populates="inventarios")
    producto = db.relationship("Producto", back_populates="inventarios")

    def __repr__(self):
        return f"<Inventario Prod:{self.producto_id} Suc:{self.sucursal_id} Cant:{self.cantidad}>"


# 2. CLASE MODIFICADA: Producto ahora es un 'Catálogo Global'
class Producto(db.Model):
    __tablename__ = "productos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    precio = db.Column(db.Numeric(10, 2))
    # stock = db.Column(db.Integer)  <-- ELIMINADO (ahora está en Inventario)
    # sucursal_id = ...              <-- ELIMINADO (el producto ya no pertenece a una sola sucursal)
    estado = db.Column(db.String(20))

    # Relación al objeto de asociación Inventario
    inventarios = db.relationship(
        "Inventario", back_populates="producto", cascade="all, delete-orphan"
    )

    detalles = db.relationship("DetalleVenta", backref="producto", lazy=True)

    # --- MÉTODOS DE APOYO (HELPER METHODS) ---
    # Estos métodos te ayudan a mantener la lógica simple en tus rutas de Flask

    def obtener_stock(self, sucursal_id):
        """Retorna el stock disponible en una sucursal específica"""
        inv = Inventario.query.filter_by(
            producto_id=self.id, sucursal_id=sucursal_id
        ).first()
        return inv.cantidad if inv else 0

    def actualizar_stock(self, sucursal_id, cantidad, operacion="sumar"):
        """Actualiza el stock de forma segura"""
        inv = Inventario.query.filter_by(
            producto_id=self.id, sucursal_id=sucursal_id
        ).first()

        # Si no existe registro de inventario en esa sucursal, lo creamos
        if not inv:
            inv = Inventario(producto_id=self.id, sucursal_id=sucursal_id, cantidad=0)
            db.session.add(inv)

        if operacion == "sumar":
            inv.cantidad += cantidad
        elif operacion == "restar":
            if inv.cantidad >= cantidad:
                inv.cantidad -= cantidad
            else:
                raise ValueError("Stock insuficiente")

        return inv.cantidad

    def __repr__(self):
        return f"<Producto {self.nombre}>"


class Venta(db.Model):
    __tablename__ = "ventas"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    monto_total = db.Column(db.Numeric(10, 2))
    fecha_venta = db.Column(db.DateTime, default=datetime.utcnow)
    metodo_pago = db.Column(db.String(20))

    detalles = db.relationship("DetalleVenta", backref="venta", lazy=True)

    def __repr__(self):
        return f"<Venta {self.id} monto={self.monto_total}>"


class DetalleVenta(db.Model):
    __tablename__ = "detalle_ventas"
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey("ventas.id"))
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"))
    cantidad = db.Column(db.Integer)
    precio_unitario = db.Column(db.Numeric(10, 2))
    subtotal = db.Column(db.Numeric(10, 2))

    def __repr__(self):
        return f"<DetalleVenta venta={self.venta_id} producto={self.producto_id}>"


class Notificacion(db.Model):
    __tablename__ = "notificaciones"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    tipo = db.Column(db.String(50))
    mensaje = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    leido = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Notificacion {self.id} tipo={self.tipo}>"


class Auditoria(db.Model):
    __tablename__ = "auditoria"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    tabla_afectada = db.Column(db.String(100))
    operacion = db.Column(db.String(20))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    descripcion = db.Column(db.Text)

    def __repr__(self):
        return f"<Auditoria {self.tabla_afectada} op={self.operacion}>"


# --- Auditoría automática en sesión ---------------------------------
def _format_value(v):
    # Serializa valores simples para descripción (fechas, Decimals, etc.)
    if v is None:
        return None
    try:
        # JSON serializable types pass
        json.dumps(v)
        return v
    except Exception:
        try:
            return str(v)
        except Exception:
            return None


def _should_audit_instance(obj):
    # Auditar solo objetos mapeados que tengan __table__ y que no sean Auditoria
    if obj is None:
        return False
    cls = type(obj)
    if getattr(cls, "__tablename__", None) is None:
        return False
    # evitar auditar la tabla de auditoria para no crear ciclos
    if getattr(cls, "__tablename__", "").lower() in ("auditoria", "audits", "audit"):
        return False
    return True


def _gather_state(obj):
    # devuelve dict {col: valor} para columnas simples
    out = {}
    try:
        cols = getattr(obj.__table__, "columns", [])
        for c in cols:
            try:
                out[c.name] = _format_value(getattr(obj, c.name, None))
            except Exception:
                out[c.name] = None
    except Exception:
        pass
    return out


# registrar el listener en la sesión principal de SQLAlchemy
def _collect_before_flush(session, flush_context, instances):
    # build pending audit descriptors and stash in session.info
    try:
        pending = session.info.setdefault("_audit_pending", [])
        actor = None
        automatic = False
        try:
            actor = getattr(g, "audit_actor", None)
            automatic = bool(getattr(g, "audit_automatic", False))
        except Exception:
            actor = None
            automatic = False
        try:
            if (
                not actor
                and current_user is not None
                and getattr(current_user, "is_authenticated", False)
            ):
                actor = getattr(current_user, "id", None)
        except Exception:
            actor = actor

        # NEW
        for obj in list(session.new):
            if not _should_audit_instance(obj):
                continue
            tabla = getattr(type(obj), "__tablename__", None)
            values = _gather_state(obj)
            pending.append(
                {
                    "action": "INSERT",
                    "tabla": tabla,
                    "actor": actor,
                    "automatic": automatic,
                    "values": values,
                    "obj": obj,
                }
            )

        # UPDATES
        for obj in list(session.dirty):
            if not _should_audit_instance(obj):
                continue
            try:
                if not session.is_modified(obj, include_collections=False):
                    continue
            except Exception:
                pass
            tabla = getattr(type(obj), "__tablename__", None)
            changes = []
            try:
                cols = getattr(obj.__table__, "columns", [])
                for c in cols:
                    try:
                        hist = get_history(obj, c.name)
                        if hist.has_changes():
                            old = hist.deleted[0] if hist.deleted else None
                            new = (
                                hist.added[0]
                                if hist.added
                                else getattr(obj, c.name, None)
                            )
                            changes.append(
                                {
                                    "columna": c.name,
                                    "anterior": _format_value(old),
                                    "nuevo": _format_value(new),
                                }
                            )
                    except Exception:
                        continue
            except Exception:
                pass
            if changes:
                pending.append(
                    {
                        "action": "UPDATE",
                        "tabla": tabla,
                        "actor": actor,
                        "automatic": automatic,
                        "changes": changes,
                        "obj": obj,
                    }
                )

        # DELETES
        for obj in list(session.deleted):
            if not _should_audit_instance(obj):
                continue
            tabla = getattr(type(obj), "__tablename__", None)
            values = _gather_state(obj)
            pending.append(
                {
                    "action": "DELETE",
                    "tabla": tabla,
                    "actor": actor,
                    "automatic": automatic,
                    "values": values,
                    "obj": obj,
                }
            )
    except Exception:
        try:
            import logging

            logging.getLogger(__name__).exception(
                "Error colectando auditoría antes de flush"
            )
        except Exception:
            pass


def _after_flush_persist(session, flush_context):
    # persist collected audit entries using core insert to avoid recursion
    try:
        pending = (
            session.info.pop("_audit_pending", [])
            if "_audit_pending" in session.info
            else []
        )
        if not pending:
            return
        inserts = []
        for item in pending:
            try:
                obj = item.get("obj")
                # try to determine primary key(s)
                pk = None
                try:
                    mapper = getattr(type(obj), "__mapper__", None)
                    if mapper is not None:
                        pk_cols = [c.key for c in mapper.primary_key]
                        pk = {k: _format_value(getattr(obj, k, None)) for k in pk_cols}
                except Exception:
                    pk = None
                payload = {
                    "accion": item.get("action"),
                    "automatic": bool(item.get("automatic", False)),
                }
                if item.get("action") in ("INSERT", "DELETE"):
                    payload["valores"] = item.get("values")
                else:
                    payload["cambios"] = item.get("changes")
                if pk is not None:
                    payload["pk"] = pk
                    # ensure valores contains pk values for INSERT/DELETE so id is visible
                    if item.get("action") in ("INSERT", "DELETE") and isinstance(
                        payload.get("valores"), dict
                    ):
                        for k, v in pk.items():
                            try:
                                # if valores lacks the pk or is None, set it
                                if payload["valores"].get(k) in (None, ""):
                                    payload["valores"][k] = v
                            except Exception:
                                try:
                                    payload["valores"][k] = v
                                except Exception:
                                    pass
                descripcion = json.dumps(payload, default=str, ensure_ascii=False)
                inserts.append(
                    {
                        "usuario_id": item.get("actor"),
                        "tabla_afectada": item.get("tabla"),
                        "operacion": item.get("action"),
                        "descripcion": descripcion,
                        "fecha": datetime.utcnow(),
                    }
                )
            except Exception:
                continue
        if inserts:
            conn = session.connection()
            conn.execute(Auditoria.__table__.insert(), inserts)
    except Exception:
        try:
            import logging

            logging.getLogger(__name__).exception(
                "Error persistiendo auditoría después de flush"
            )
        except Exception:
            pass


# Registrar listeners para los modelos que ya tienen `sucursal_id`
event.listen(Cliente, "before_insert", _assign_sucursal_from_session)
event.listen(Membresia, "before_insert", _assign_sucursal_from_session)
event.listen(Pago, "before_insert", _assign_sucursal_from_session)
event.listen(Venta, "before_insert", _assign_sucursal_from_session)
event.listen(Gasto, "before_insert", _assign_sucursal_from_session)
event.listen(Notificacion, "before_insert", _assign_sucursal_from_session)

# register listeners
event.listen(db.session, "before_flush", _collect_before_flush)
event.listen(db.session, "after_flush", _after_flush_persist)
