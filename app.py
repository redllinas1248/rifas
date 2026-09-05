from flask import Flask, render_template
from db import get_db

app = Flask(__name__)


@app.route("/")
def inicio():
    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(debug=True)