"""Client service layer - business logic for client management."""
from flask import current_app
from ..extensions import db
from sqlalchemy import and_, or_, true
from ..models import Cliente, Membresia
from .membership_service import get_membership_status
from ..utils_timezone import local_today


def clean_client_query(q):
    """Normaliza el texto de búsqueda de clientes.

    El navegador puede autocompletar el campo con el texto completo de una
    opción elegida antes, p. ej. "Ana Paz - ana@mail.comTiene"; se conserva
    sólo la parte anterior a " - " (nombre y apellido).
    """
    q = (q or "").strip()
    if " - " in q:
        q = q.split(" - ", 1)[0]
    return " ".join(q.split())


def client_search_filter(q):
    """Filtro SQLAlchemy para buscar clientes por palabras.

    Cada palabra debe aparecer en el nombre, apellido, correo o teléfono, así
    "ana paz" encuentra a "Ana María Paz" sin importar el orden ni las
    mayúsculas.
    """
    words = clean_client_query(q).split()
    if not words:
        return true()
    fields = (Cliente.nombre, Cliente.apellido, Cliente.correo, Cliente.telefono)
    return and_(
        *[or_(*[f.icontains(w, autoescape=True) for f in fields]) for w in words]
    )


def compute_age(fecha_nacimiento):
    """Compute age from birth date. Returns None if invalid."""
    try:
        if not fecha_nacimiento:
            return None
        today = local_today()
        age = today.year - fecha_nacimiento.year
        if (today.month, today.day) < (
            fecha_nacimiento.month,
            fecha_nacimiento.day,
        ):
            age -= 1
        return age
    except Exception:
        return None


def get_client_with_flags(cliente_id):
    """Get client with membership status flags.

    Returns dict:
    - cliente: Cliente object
    - has_active_membership: bool
    - membership_expires_soon: bool (within 7 days)
    - days_until_expiration: int or None
    - age: int or None
    """
    try:
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            return None

        # Get membership status
        status = get_membership_status(cliente_id, horizon_days=7)

        # Compute age
        age = compute_age(cliente.fecha_nacimiento)

        # Compute days until expiration
        days_until = None
        if status["last_fecha_fin"]:
            days_until = (
                status["last_fecha_fin"] - local_today()
            ).days

        return {
            "cliente": cliente,
            "has_active_membership": status["has"],
            "membership_expires_soon": status["soon"],
            "last_membership_id": status["last_id"],
            "days_until_expiration": days_until,
            "age": age,
        }

    except Exception as e:
        try:
            current_app.logger.exception(f"Error fetching client with flags: {e}")
        except Exception:
            pass
        return None


def create_client(
    nombre,
    apellido=None,
    correo=None,
    telefono=None,
    fecha_nacimiento=None,
    tipo_cliente='Individual',
    sucursal_id=None,
):
    """Create a new client.

    Cliente starts in estado='Inactivo'. Estado transitions happen via membresías.

    Returns (success: bool, cliente: Cliente or None, error_msg: str or None)
    """
    try:
        # Validate nombre
        if not nombre or not nombre.strip():
            return False, None, "Nombre es requerido"

        # Validate email uniqueness (if provided)
        if correo:
            existing = Cliente.query.filter_by(correo=correo).first()
            if existing:
                return False, None, "Correo ya registrado"

        # Validate phone uniqueness (if provided)
        if telefono:
            existing = Cliente.query.filter_by(telefono=telefono).first()
            if existing:
                return False, None, "Teléfono ya registrado"

        # Validate tipo_cliente
        if not tipo_cliente:
            tipo_cliente = 'Individual'

        # Validate sucursal_id (required)
        if not sucursal_id:
            return False, None, "sucursal_id es requerido"

        # Create client (always starts Inactivo)
        cliente = Cliente(
            nombre=nombre.strip(),
            apellido=apellido.strip() if apellido else None,
            correo=correo.strip() if correo else None,
            telefono=telefono.strip() if telefono else None,
            fecha_nacimiento=fecha_nacimiento,
            tipo_cliente=tipo_cliente,
            estado='Inactivo',  # Default estado
            sucursal_id=sucursal_id,
        )

        db.session.add(cliente)
        db.session.commit()

        return True, cliente, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error creating client: {e}")
        except Exception:
            pass
        return False, None, str(e)


def update_client(cliente_id, **kwargs):
    """Update client fields with validation.

    Allowed fields: nombre, correo, telefono, fecha_nacimiento, tipo_cliente
    Note: estado_id is managed via membresías, not directly editable here.

    Returns (success: bool, error_msg: str or None)
    """
    try:
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            return False, "Cliente no existe"

        allowed_fields = {
            "nombre",
            "apellido",
            "correo",
            "telefono",
            "fecha_nacimiento",
            "tipo_cliente",
        }

        for key, value in kwargs.items():
            if key not in allowed_fields:
                continue

            if key == "nombre" and value:
                value = value.strip()
                if not value:
                    return False, "Nombre no puede estar vacío"

            if key == "apellido" and value:
                value = value.strip()

            if key == "correo" and value:
                value = value.strip()
                # Check uniqueness (excluding self)
                existing = Cliente.query.filter(
                    Cliente.correo == value, Cliente.id != cliente_id
                ).first()
                if existing:
                    return False, "Correo ya registrado"

            if key == "telefono" and value:
                value = value.strip()
                # Check uniqueness (excluding self)
                existing = Cliente.query.filter(
                    Cliente.telefono == value, Cliente.id != cliente_id
                ).first()
                if existing:
                    return False, "Teléfono ya registrado"

            if key == "tipo_cliente" and value:
                if not isinstance(value, str):
                    return False, "Tipo cliente debe ser string"

            setattr(cliente, key, value)

        db.session.commit()
        return True, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error updating client: {e}")
        except Exception:
            pass
        return False, str(e)


def delete_client(cliente_id):
    """Delete a client (only if no membresías linked).

    Returns (success: bool, error_msg: str or None)
    """
    try:
        cliente = db.session.get(Cliente, cliente_id)
        if not cliente:
            return False, "Cliente no existe"

        # Check for membresías
        membresias = Membresia.query.filter_by(cliente_id=cliente_id).count()
        if membresias > 0:
            return False, f"Cliente tiene {membresias} membresía(s). Elimina primero."

        db.session.delete(cliente)
        db.session.commit()
        return True, None

    except Exception as e:
        try:
            db.session.rollback()
            current_app.logger.exception(f"Error deleting client: {e}")
        except Exception:
            pass
        return False, str(e)
