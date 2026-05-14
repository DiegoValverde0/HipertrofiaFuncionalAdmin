import os
import sys

# Asegura que el directorio del proyecto esté en el path
sys.path.insert(0, os.path.dirname(__file__))

# Importa la aplicación Flask desde run.py
from run import (
    app,
)  # <-- asegúrate de que en run.py exista 'app = Flask(__name__)' o similar

# Exponer 'app' como variable global para WSGI
application = app

# (Opcional, solo si quieres ejecutar directamente este archivo)
if __name__ == "__main__":
    app.run()
