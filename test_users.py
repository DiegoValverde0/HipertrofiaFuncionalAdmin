from gym_admin import create_app
from gym_admin.models import Usuario

app = create_app()
with app.app_context():
    usuarios = Usuario.query.limit(5).all()
    for u in usuarios:
        print(f"Email: {u.correo}, Nombre: {u.nombre}")
