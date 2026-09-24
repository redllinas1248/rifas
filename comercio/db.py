import psycopg2
from flask import current_app, g

def get_db():
    """Obtiene una conexión a la base de datos PostgreSQL."""
    if 'db' not in g:
        database_url = current_app.config.get('DATABASE_URL')
        if not database_url:
            raise RuntimeError("DATABASE_URL no configurada")

        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)

        g.db = psycopg2.connect(database_url)
        g.db.autocommit = False
    return g.db

def init_db(app):
    """Inicializa la base de datos (crea tablas si no existen)."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS visitas (
                id SERIAL PRIMARY KEY,
                fecha DATE UNIQUE NOT NULL,
                total INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuracion (
                id SERIAL PRIMARY KEY,
                clave VARCHAR(100) UNIQUE NOT NULL,
                valor TEXT,
                fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()
        cur.close()