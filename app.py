from flask import Flask, render_template
from db import get_db

app = Flask(__name__)


# ==========================================
# PAGINA PRINCIPAL
# ==========================================

@app.route("/")
def inicio():
    return render_template("index.html")


# ==========================================
# LISTADO DE RIFAS
# ==========================================

@app.route("/rifas")
def rifas():

    db = get_db()

    try:
        cursor = db.cursor()

        cursor.execute("""
            SELECT
                id,
                titulo,
                descripcion,
                imagen_url,
                cantidad_boletos,
                precio_boleto,
                estado,
                fecha_inicio,
                fecha_fin,
                fecha_sorteo
            FROM rf_rifas
            WHERE estado = 'activa'
            ORDER BY creado_en DESC
        """)

        rifas = cursor.fetchall()

        return render_template(
            "rifas.html",
            rifas=rifas
        )

    finally:
        db.close()


# ==========================================
# PRUEBA DE CONEXION A POSTGRESQL
# ==========================================

@app.route("/rifas/prueba-db")
def prueba_db():

    db = get_db()

    try:
        cursor = db.cursor()

        cursor.execute("""
            SELECT
                current_database() AS base_datos,
                current_schema() AS esquema,
                COUNT(*) AS total_rifas
            FROM rf_rifas
        """)

        resultado = cursor.fetchone()

        return {
            "base_datos": resultado["base_datos"],
            "esquema": resultado["esquema"],
            "total_rifas": resultado["total_rifas"]
        }

    finally:
        db.close()


# ==========================================
# EJECUCION LOCAL
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)