import os
import sys
import importlib.util

# Añadir el directorio actual al path
sys.path.insert(0, os.path.dirname(__file__))

# Cargar wsgi.py usando importlib (reemplaza al deprecado imp)
def load_wsgi():
    spec = importlib.util.spec_from_file_location("wsgi", "wsgi.py")
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None

wsgi = load_wsgi()
application = wsgi.application if wsgi else None
