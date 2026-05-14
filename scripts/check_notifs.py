from gym_admin import create_app
from gym_admin.models import Notificacion
import json

app = create_app()
with app.app_context():
    rows = [
        {
            "id": n.id,
            "tipo": n.tipo,
            "mensaje": n.mensaje,
            "leido": n.leido,
            "fecha": n.fecha_creacion.isoformat(),
        }
        for n in Notificacion.query.order_by(Notificacion.fecha_creacion.desc())
        .limit(10)
        .all()
    ]
    print(json.dumps(rows, ensure_ascii=False, default=str))
