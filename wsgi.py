"""Punto de entrada WSGI para Gunicorn: ``gunicorn wsgi:application``."""

from run import app

application = app

if __name__ == "__main__":
    app.run()
