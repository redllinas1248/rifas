from flask import (
    Blueprint,
    render_template,
    abort
)

from db import get_db


noticias_bp = Blueprint(
    "noticias",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/noticias-static"
)


# ============================================================
# HOME DEL PORTAL
# ============================================================

@noticias_bp.route("/")
def inicio():

    db = get_db()

    try:

        cursor = db.cursor()

        # Últimas noticias publicadas
        cursor.execute("""
            SELECT
                n.id,
                n.titulo,
                n.slug,
                n.resumen,
                n.imagen_url,
                n.autor,
                n.publicado_en,
                c.nombre AS categoria_nombre,
                c.slug AS categoria_slug,
                c.icono AS categoria_icono
            FROM rt_noticias n
            LEFT JOIN rt_noticias_categorias c
                ON c.id = n.categoria_id
            WHERE n.estado = 'publicada'
            ORDER BY n.publicado_en DESC
            LIMIT 12
        """)

        ultimas = cursor.fetchall()

        # Categorías
        cursor.execute("""
            SELECT
                c.id,
                c.nombre,
                c.slug,
                c.icono,
                COUNT(n.id) AS total
            FROM rt_noticias_categorias c
            LEFT JOIN rt_noticias n
                ON n.categoria_id = c.id
                AND n.estado = 'publicada'
            GROUP BY c.id
            ORDER BY c.orden
        """)

        categorias = cursor.fetchall()

        # Rifas activas
        cursor.execute("""
            SELECT
                id,
                titulo,
                descripcion,
                imagen_url,
                cantidad_boletos
            FROM rt_rifas
            WHERE estado = 'activa'
            ORDER BY creado_en DESC
            LIMIT 3
        """)

        rifas_destacadas = cursor.fetchall()

        return render_template(
            "noticias_inicio.html",
            ultimas=ultimas,
            categorias=categorias,
            rifas_destacadas=rifas_destacadas
        )

    finally:

        db.close()