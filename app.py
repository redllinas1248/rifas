import os

from flask import Flask, render_template, request, redirect, url_for, flash
from db import get_db


app = Flask(__name__)

# ==========================================
# CONFIGURACION
# ==========================================

app.secret_key = os.getenv(
    "SECRET_KEY",
    "rifas-clave-local"
)


# ==========================================
# PAGINA PRINCIPAL
# ==========================================

@app.route("/")
def inicio():
    return render_template("index.html")


# ==========================================
# LISTADO PUBLICO DE RIFAS
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
            FROM rt_rifas
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
# PANEL ADMINISTRATIVO
# ==========================================

@app.route("/rifas/admin")
def admin_rifas():

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
                fecha_sorteo,
                creado_en,
                actualizado_en
            FROM rt_rifas
            ORDER BY creado_en DESC
        """)

        rifas = cursor.fetchall()

        return render_template(
            "admin_rifas.html",
            rifas=rifas
        )

    finally:
        db.close()


# ==========================================
# NUEVA RIFA - FORMULARIO
# ==========================================

@app.route("/rifas/admin/nueva")
def nueva_rifa():

    return render_template("nueva_rifa.html")


# ==========================================
# NUEVA RIFA - GUARDAR
# ==========================================

@app.route("/rifas/admin/nueva", methods=["POST"])
def crear_rifa():

    titulo = request.form.get("titulo", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    imagen_url = request.form.get("imagen_url", "").strip()
    cantidad_boletos = request.form.get("cantidad_boletos", "").strip()
    precio_boleto = request.form.get("precio_boleto", "").strip()
    fecha_inicio = request.form.get("fecha_inicio", "").strip()
    fecha_fin = request.form.get("fecha_fin", "").strip()
    fecha_sorteo = request.form.get("fecha_sorteo", "").strip()

    # ==========================================
    # VALIDAR TITULO
    # ==========================================

    if not titulo:

        flash(
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(url_for("nueva_rifa"))

    # ==========================================
    # VALIDAR CANTIDAD DE BOLETOS
    # ==========================================

    try:

        cantidad_boletos = int(cantidad_boletos)

        if cantidad_boletos <= 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "La cantidad de boletos debe ser un número mayor que cero.",
            "error"
        )

        return redirect(url_for("nueva_rifa"))

    # ==========================================
    # VALIDAR PRECIO
    # ==========================================

    try:

        precio_boleto = float(precio_boleto)

        if precio_boleto < 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "El precio del boleto no es válido.",
            "error"
        )

        return redirect(url_for("nueva_rifa"))

    # ==========================================
    # GUARDAR RIFA
    # ==========================================

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            INSERT INTO rt_rifas (
                titulo,
                descripcion,
                imagen_url,
                cantidad_boletos,
                precio_boleto,
                estado,
                fecha_inicio,
                fecha_fin,
                fecha_sorteo,
                creado_en,
                actualizado_en
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                'borrador',
                NULLIF(%s, '')::timestamp,
                NULLIF(%s, '')::timestamp,
                NULLIF(%s, '')::timestamp,
                NOW(),
                NOW()
            )
            RETURNING id
        """, (
            titulo,
            descripcion,
            imagen_url,
            cantidad_boletos,
            precio_boleto,
            fecha_inicio,
            fecha_fin,
            fecha_sorteo
        ))

        rifa_id = cursor.fetchone()["id"]

        db.commit()

        flash(
            f"Rifa creada correctamente. ID: {rifa_id}",
            "success"
        )

        return redirect(url_for("admin_rifas"))

    except Exception as error:

        db.rollback()

        print("ERROR AL CREAR RIFA:", error)

        flash(
            "Ocurrió un error al crear la rifa.",
            "error"
        )

        return redirect(url_for("nueva_rifa"))

    finally:

        db.close()


# ==========================================
# EDITAR RIFA - FORMULARIO
# ==========================================

@app.route("/rifas/admin/editar/<int:rifa_id>")
def editar_rifa(rifa_id):

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
            FROM rt_rifas
            WHERE id = %s
        """, (rifa_id,))

        rifa = cursor.fetchone()

        if not rifa:

            flash(
                "La rifa no existe.",
                "error"
            )

            return redirect(url_for("admin_rifas"))

        return render_template(
            "nueva_rifa.html",
            rifa=rifa,
            modo_edicion=True
        )

    finally:

        db.close()


# ==========================================
# EDITAR RIFA - GUARDAR
# ==========================================

@app.route("/rifas/admin/editar/<int:rifa_id>", methods=["POST"])
def actualizar_rifa(rifa_id):

    titulo = request.form.get("titulo", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    imagen_url = request.form.get("imagen_url", "").strip()
    cantidad_boletos = request.form.get("cantidad_boletos", "").strip()
    precio_boleto = request.form.get("precio_boleto", "").strip()
    fecha_inicio = request.form.get("fecha_inicio", "").strip()
    fecha_fin = request.form.get("fecha_fin", "").strip()
    fecha_sorteo = request.form.get("fecha_sorteo", "").strip()

    # ==========================================
    # VALIDACIONES
    # ==========================================

    if not titulo:

        flash(
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(
            url_for("editar_rifa", rifa_id=rifa_id)
        )

    try:

        cantidad_boletos = int(cantidad_boletos)

        if cantidad_boletos <= 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "La cantidad de boletos no es válida.",
            "error"
        )

        return redirect(
            url_for("editar_rifa", rifa_id=rifa_id)
        )

    try:

        precio_boleto = float(precio_boleto)

        if precio_boleto < 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "El precio del boleto no es válido.",
            "error"
        )

        return redirect(
            url_for("editar_rifa", rifa_id=rifa_id)
        )

    # ==========================================
    # ACTUALIZAR
    # ==========================================

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            UPDATE rt_rifas
            SET
                titulo = %s,
                descripcion = %s,
                imagen_url = %s,
                cantidad_boletos = %s,
                precio_boleto = %s,
                fecha_inicio = NULLIF(%s, '')::timestamp,
                fecha_fin = NULLIF(%s, '')::timestamp,
                fecha_sorteo = NULLIF(%s, '')::timestamp,
                actualizado_en = NOW()
            WHERE id = %s
        """, (
            titulo,
            descripcion,
            imagen_url,
            cantidad_boletos,
            precio_boleto,
            fecha_inicio,
            fecha_fin,
            fecha_sorteo,
            rifa_id
        ))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe.",
                "error"
            )

            return redirect(url_for("admin_rifas"))

        db.commit()

        flash(
            "Rifa actualizada correctamente.",
            "success"
        )

        return redirect(url_for("admin_rifas"))

    except Exception as error:

        db.rollback()

        print("ERROR AL ACTUALIZAR RIFA:", error)

        flash(
            "Ocurrió un error al actualizar la rifa.",
            "error"
        )

        return redirect(
            url_for("editar_rifa", rifa_id=rifa_id)
        )

    finally:

        db.close()


# ==========================================
# PUBLICAR RIFA
# BORRADOR -> ACTIVA
# ==========================================

@app.route("/rifas/admin/publicar/<int:rifa_id>", methods=["POST"])
def publicar_rifa(rifa_id):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            UPDATE rt_rifas
            SET
                estado = 'activa',
                actualizado_en = NOW()
            WHERE
                id = %s
                AND estado = 'borrador'
        """, (rifa_id,))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe o no se encuentra en estado borrador.",
                "error"
            )

        else:

            db.commit()

            flash(
                "Rifa publicada correctamente.",
                "success"
            )

    except Exception as error:

        db.rollback()

        print("ERROR AL PUBLICAR RIFA:", error)

        flash(
            "Ocurrió un error al publicar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(url_for("admin_rifas"))


# ==========================================
# FINALIZAR RIFA
# ACTIVA -> FINALIZADA
# ==========================================

@app.route("/rifas/admin/finalizar/<int:rifa_id>", methods=["POST"])
def finalizar_rifa(rifa_id):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            UPDATE rt_rifas
            SET
                estado = 'finalizada',
                actualizado_en = NOW()
            WHERE
                id = %s
                AND estado = 'activa'
        """, (rifa_id,))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe o no está activa.",
                "error"
            )

        else:

            db.commit()

            flash(
                "Rifa finalizada correctamente.",
                "success"
            )

    except Exception as error:

        db.rollback()

        print("ERROR AL FINALIZAR RIFA:", error)

        flash(
            "Ocurrió un error al finalizar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(url_for("admin_rifas"))


# ==========================================
# CANCELAR RIFA
# BORRADOR/ACTIVA -> CANCELADA
# ==========================================

@app.route("/rifas/admin/cancelar/<int:rifa_id>", methods=["POST"])
def cancelar_rifa(rifa_id):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            UPDATE rt_rifas
            SET
                estado = 'cancelada',
                actualizado_en = NOW()
            WHERE
                id = %s
                AND estado IN ('borrador', 'activa')
        """, (rifa_id,))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe o no puede ser cancelada.",
                "error"
            )

        else:

            db.commit()

            flash(
                "Rifa cancelada correctamente.",
                "success"
            )

    except Exception as error:

        db.rollback()

        print("ERROR AL CANCELAR RIFA:", error)

        flash(
            "Ocurrió un error al cancelar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(url_for("admin_rifas"))


# ==========================================
# EJECUCION LOCAL
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)