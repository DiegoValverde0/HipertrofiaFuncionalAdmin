import os
import logging
from gym_admin import create_app

# LOG_LEVEL=DEBUG para depurar; SQL_LOG=1 registra cada consulta SQL
# (muy verboso, sólo para diagnosticar problemas de base de datos).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s",
)
if os.getenv("SQL_LOG", "0") == "1":
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

app = create_app()

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
