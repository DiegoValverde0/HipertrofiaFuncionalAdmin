import pytest
from gym_admin import create_app
from gym_admin.extensions import db
from gym_admin.models import Sucursal, Cliente, Plan, EstadoMembresia, Promocion

class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    POST_LOGIN_TASKS_ASYNC = False
    RATELIMIT_STORAGE_URI = "memory://"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SERVER_NAME = "localhost.localdomain"

@pytest.fixture(scope="session")
def app():
    """Create and configure a new app instance for each test session."""
    # Create the app with testing configuration
    app = create_app(TestConfig)

    # Establish an application context before running the tests.
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def db_session(app):
    """Create a new database session for a test."""
    # Since we are using an in-memory sqlite database, recreating tables is fast and clean
    db.session.remove()
    db.drop_all()
    db.create_all()
    
    yield db.session
    
    db.session.remove()
    db.drop_all()

# Fixtures for model factories
@pytest.fixture
def sucursal(db_session):
    s = Sucursal(nombre="Sucursal Test")
    db.session.add(s)
    db.session.commit()
    return s

@pytest.fixture
def cliente(db_session, sucursal):
    c = Cliente(nombre="John", apellido="Doe", sucursal_id=sucursal.id)
    db.session.add(c)
    db.session.commit()
    return c

@pytest.fixture
def plan(db_session):
    p = Plan(nombre="Mensual", descripcion="Test", duracion="1 mes", precio=100.00, tipo="Basico")
    db.session.add(p)
    db.session.commit()
    return p

@pytest.fixture
def estados_membresia(db_session):
    estados = [
        EstadoMembresia(id=1, nombre="Pendiente de pago"),
        EstadoMembresia(id=2, nombre="Activa"),
        EstadoMembresia(id=3, nombre="Anulada"),
        EstadoMembresia(id=4, nombre="Inactiva"),
        EstadoMembresia(id=5, nombre="En espera")
    ]
    for e in estados:
        db.session.add(e)
    db.session.commit()
    return {e.id: e for e in estados}

@pytest.fixture
def promocion(db_session):
    p = Promocion(nombre="Promo 10", descuento=10.00)
    db.session.add(p)
    db.session.commit()
    return p
