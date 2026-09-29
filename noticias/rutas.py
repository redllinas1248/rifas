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

        # ----------------------------------------------------
        # 1. Noticia destacada principal (la más reciente destacada)
        # ----------------------------------------------------

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
              AND n.destacada = TRUE
            ORDER BY n.publicado_en DESC
            LIMIT 1
        """)

        destacada = cursor.fetchone()

        # Si no hay destacada, usar la más reciente
        if not destacada:

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
                LIMIT 1
            """)

            destacada = cursor.fetchone()

        # ----------------------------------------------------
        # 2. Últimas noticias (excluyendo la destacada)
        # ----------------------------------------------------

        destacada_id = destacada["id"] if destacada else 0

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
              AND n.id != %s
            ORDER BY n.publicado_en DESC
            LIMIT 9
        """, (destacada_id,))

        ultimas = cursor.fetchall()

        # ----------------------------------------------------
        # 3. Categorías con contador
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                c.id,
                c.nombre,
                c.slug,
                c.icono,
                c.descripcion,
                COUNT(n.id) AS total
            FROM rt_noticias_categorias c
            LEFT JOIN rt_noticias n
                ON n.categoria_id = c.id
                AND n.estado = 'publicada'
            GROUP BY c.id
            ORDER BY c.orden
        """)

        categorias = cursor.fetchall()

        # ----------------------------------------------------
        # 4. Rifas activas
        # ----------------------------------------------------

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
            destacada=destacada,
            ultimas=ultimas,
            categorias=categorias,
            rifas_destacadas=rifas_destacadas
        )

    finally:

        db.close()

# ============================================================
# LISTADO COMPLETO
# ============================================================

@noticias_bp.route("/noticias")
def listado():

    db = get_db()

    try:

        cursor = db.cursor()

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
        """)

        noticias = cursor.fetchall()

        return render_template(
            "noticias_listado.html",
            noticias=noticias
        )

    finally:

        db.close()


# ============================================================
# ARTÍCULO INDIVIDUAL
# ============================================================

@noticias_bp.route("/noticias/<slug>")
def articulo(slug):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            SELECT
                n.id,
                n.titulo,
                n.slug,
                n.resumen,
                n.contenido,
                n.imagen_url,
                n.autor,
                n.vistas,
                n.publicado_en,
                c.nombre AS categoria_nombre,
                c.slug AS categoria_slug,
                c.icono AS categoria_icono
            FROM rt_noticias n
            LEFT JOIN rt_noticias_categorias c
                ON c.id = n.categoria_id
            WHERE n.slug = %s
              AND n.estado = 'publicada'
        """, (slug,))

        noticia = cursor.fetchone()

        if not noticia:
            abort(404)

        cursor.execute("""
            UPDATE rt_noticias
            SET vistas = vistas + 1
            WHERE id = %s
        """, (noticia["id"],))

        db.commit()

        cursor.execute("""
            SELECT
                n.id,
                n.titulo,
                n.slug,
                n.imagen_url,
                n.publicado_en
            FROM rt_noticias n
            WHERE n.estado = 'publicada'
              AND n.categoria_id = (
                  SELECT categoria_id
                  FROM rt_noticias
                  WHERE id = %s
              )
              AND n.id != %s
            ORDER BY n.publicado_en DESC
            LIMIT 4
        """, (noticia["id"], noticia["id"]))

        relacionadas = cursor.fetchall()

        return render_template(
            "noticias_articulo.html",
            noticia=noticia,
            relacionadas=relacionadas
        )

    finally:

        db.close()


# ============================================================
# CATEGORÍA
# ============================================================

@noticias_bp.route("/categoria/<slug>")
def categoria(slug):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            SELECT
                id,
                nombre,
                slug,
                icono,
                descripcion
            FROM rt_noticias_categorias
            WHERE slug = %s
        """, (slug,))

        cat = cursor.fetchone()

        if not cat:
            abort(404)

        cursor.execute("""
            SELECT
                n.id,
                n.titulo,
                n.slug,
                n.resumen,
                n.imagen_url,
                n.autor,
                n.publicado_en
            FROM rt_noticias n
            WHERE n.categoria_id = %s
              AND n.estado = 'publicada'
            ORDER BY n.publicado_en DESC
        """, (cat["id"],))

        noticias = cursor.fetchall()

        return render_template(
            "noticias_categoria.html",
            categoria=cat,
            noticias=noticias
        )

    finally:

        db.close()


# ============================================================
# SOBRE NOSOTROS
# ============================================================

@noticias_bp.route("/sobre")
def sobre():

    return render_template("noticias_sobre.html")