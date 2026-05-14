from gym_admin import create_app
from gym_admin.models import Usuario, Role
from gym_admin.extensions import db
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    # Obtener un rol válido
    rol = Role.query.first()
    if not rol:
        print("No hay roles creados")
        exit(1)
    
    # Verificar si el usuario ya existe
    usuario = Usuario.query.filter_by(correo='test@test.com').first()
    if usuario:
        # Actualizar contraseña
        usuario.contrasena = generate_password_hash('test123')
        db.session.commit()
        print("Usuario actualizado: test@test.com / test123")
    else:
        # Crear nuevo usuario
        usuario = Usuario(
            correo='test@test.com',
            nombre='Test User',
            rol_id=rol.id,
            contrasena=generate_password_hash('test123')
        )
        db.session.add(usuario)
        db.session.commit()
        print(f"Usuario creado: test@test.com / test123")
