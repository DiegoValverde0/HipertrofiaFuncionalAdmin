"""Small test script to validate client flags calculation for memberships
Run from project root with the same virtualenv used by the app.
"""

from datetime import date, timedelta
from decimal import Decimal
import os

# bootstrap flask app context
from run import create_app
from gym_admin.extensions import db
from gym_admin.models import (
    Cliente,
    Plan,
    Promocion,
    Membresia,
    Pago,
    HistorialPago,
    EstadoMembresia,
)
from gym_admin.utils import (
    ensure_membership_state_after_payment,
    process_membership_states,
    _compute_monto_total_for_membresia,
)

app = create_app()
app.app_context().push()

# helper: clear some test data (be conservative)
print("Using database:", app.config.get("SQLALCHEMY_DATABASE_URI"))

# create minimal plan and estado if needed
plan = Plan.query.filter_by(nombre="Plan Test").first()
if not plan:
    plan = Plan(
        nombre="Plan Test",
        descripcion="Test",
        duracion="1 month",
        precio=Decimal("100.00"),
        tipo="Mensual",
    )
    db.session.add(plan)
    db.session.commit()

# ensure membership states exist
for id_name, name in [
    (1, "Pendiente"),
    (2, "Activa"),
    (3, "Anulada"),
    (4, "Inactiva"),
    (5, "En espera"),
    (6, "Vencida"),
]:
    if not EstadoMembresia.query.get(id_name):
        e = EstadoMembresia(id=id_name, nombre=name)
        db.session.add(e)
try:
    db.session.commit()
except Exception as e:
    db.session.rollback()

# create a client
c = Cliente(
    nombre="Test",
    apellido="User",
    correo="test.user@example.com",
    telefono="59112345678",
    fecha_nacimiento=date(1990, 1, 1),
    estado="Inactivo",
)
db.session.add(c)
db.session.commit()
print("Cliente id:", c.id)

# create a membership starting today
m = Membresia(
    cliente_id=c.id,
    sucursal_id=1,
    plan_id=plan.id,
    fecha_inicio=date.today(),
    fecha_fin=date.today() + timedelta(days=30),
    estado_id=1,
)
db.session.add(m)
db.session.commit()
print("Membresia id:", m.id, "estado:", m.estado_id)

# create Pago and partial HistorialPago (below min) -> should remain Pendiente
p = Pago(
    cliente_id=c.id,
    membresia_id=m.id,
    monto_total=_compute_monto_total_for_membresia(m),
)
db.session.add(p)
db.session.commit()

h = HistorialPago(pago_id=p.id, monto_pagado=Decimal("10.00"))
db.session.add(h)
db.session.commit()

# run ensure after partial
res = ensure_membership_state_after_payment(m.id)
print("After partial payment, ensure_membership_state_after_payment returned:", res)
print("Membresia estado now:", Membresia.query.get(m.id).estado_id)

# now add remaining amount
remaining = _compute_monto_total_for_membresia(m) - Decimal("10.00")
h2 = HistorialPago(pago_id=p.id, monto_pagado=remaining)
db.session.add(h2)
db.session.commit()

res2 = ensure_membership_state_after_payment(m.id)
print("After full payment, ensure_membership_state_after_payment returned:", res2)
print("Membresia estado now:", Membresia.query.get(m.id).estado_id)

# run process_membership_states for safety
process_membership_states(target_membresia_id=m.id, client_id=c.id)
print(
    "After process_membership_states, memb estado:", Membresia.query.get(m.id).estado_id
)

# compute client flags using the same logic from blueprint
from datetime import date as _date, timedelta as _td

horizon = _date.today() + _td(days=7)

has_active = False
soon = False
soon_date = None
c_ref = Cliente.query.get(c.id)
candidates = []
for mem in c_ref.membresias:
    est = getattr(mem, "estado_id", None)
    if not getattr(mem, "fecha_fin", None):
        continue
    if est == 2:
        candidates.append(mem)
        continue
    if est == 5:
        total_due = _compute_monto_total_for_membresia(mem)
        if total_due and total_due > 0:
            total_paid = Decimal("0")
            for p in mem.pagos:
                for h in p.historial:
                    total_paid += Decimal(h.monto_pagado)
            if total_paid >= total_due:
                candidates.append(mem)

if candidates:
    m_sorted = sorted(candidates, key=lambda mm: mm.fecha_fin)
    first = m_sorted[0]
    has_active = True
    if first.fecha_fin <= horizon:
        soon = True
        soon_date = first.fecha_fin

print(
    "Client flags computed: has_active=",
    has_active,
    "soon=",
    soon,
    "fecha_fin=",
    soon_date,
)

print("Test complete")
