import os
import uuid
from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from db import get_db


app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "rifas-clave-local"
)

# Tiempo que un boleto permanece reservado
TIEMPO_RESERVA_MINUTOS = 15


# =========================================================
# PAGINA PRINCIPAL
# =========================================================

@app.route("/")
def inicio():
    return render_template("index.html")


# =========================================================
# LISTADO PUBLICO DE RIFAS
# =========================================================

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


# =========================================================
# SELECCIONAR BOLETO
# =========================================================

@app.route("/rifas/participar/<int:rifa_id>")
def participar(rifa_id):

    db = get_db()

    try:
        cursor = db.cursor()

        # -------------------------------------------------
        # Verificar que la rifa exista y esté activa
        # -------------------------------------------------

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
            flash("La rifa no existe.", "error")
            return redirect(url_for("rifas"))

        if rifa["estado"] != "activa":
            flash(
                "Esta rifa todavía no está disponible para participar.",
                "error"
            )
            return redirect(url_for("rifas"))

        # -------------------------------------------------
        # Liberar reservas vencidas
        # -------------------------------------------------

        cursor.execute("""
            UPDATE rt_boletos
            SET
                estado = 'disponible',
                origen = NULL,
                reserva_token = NULL,
                reservado_en = NULL
            WHERE
                rifa_id = %s
                AND estado = 'reservado'
                AND reservado_en < (
                    CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                )
        """, (rifa_id,))

        db.commit()

        # -------------------------------------------------
        # Obtener boletos
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                numero,
                estado,
                origen,
                reservado_en
            FROM rt_boletos
            WHERE rifa_id = %s
            ORDER BY numero ASC
        """, (rifa_id,))

        boletos = cursor.fetchall()

        return render_template(
            "seleccionar_boleto.html",
            rifa=rifa,
            boletos=boletos
        )

    finally:
        db.close()


# =========================================================
# RESERVAR BOLETO
# =========================================================

@app.route(
    "/rifas/participar/<int:rifa_id>/reservar",
    methods=["POST"]
)
def reservar_boleto(rifa_id):

    numero = request.form.get("numero", "").strip()

    # -----------------------------------------------------
    # Validar número
    # -----------------------------------------------------

    try:
        numero = int(numero)
    except (ValueError, TypeError):

        flash(
            "El número de boleto no es válido.",
            "error"
        )

        return redirect(
            url_for(
                "participar",
                rifa_id=rifa_id
            )
        )

    db = get_db()

    try:

        cursor = db.cursor()

        # -------------------------------------------------
        # Limpiar reservas vencidas
        # -------------------------------------------------

        cursor.execute("""
            UPDATE rt_boletos
            SET
                estado = 'disponible',
                origen = NULL,
                reserva_token = NULL,
                reservado_en = NULL
            WHERE
                rifa_id = %s
                AND estado = 'reservado'
                AND reservado_en < (
                    CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                )
        """, (rifa_id,))

        # -------------------------------------------------
        # Generar token único de reserva
        # -------------------------------------------------

        token = str(uuid.uuid4())

        # -------------------------------------------------
        # Buscar y bloquear el boleto
        #
        # FOR UPDATE es MUY importante.
        #
        # Si dos personas intentan tomar el mismo boleto
        # al mismo tiempo, PostgreSQL bloquea la fila.
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                numero,
                estado
            FROM rt_boletos
            WHERE
                rifa_id = %s
                AND numero = %s
            FOR UPDATE
        """, (
            rifa_id,
            numero
        ))

        boleto = cursor.fetchone()

        # -------------------------------------------------
        # Boleto inexistente
        # -------------------------------------------------

        if not boleto:

            db.rollback()

            flash(
                "El boleto seleccionado no existe.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # -------------------------------------------------
        # Boleto ocupado
        # -------------------------------------------------

        if boleto["estado"] != "disponible":

            db.rollback()

            flash(
                "Ese boleto ya no está disponible. "
                "Por favor selecciona otro.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # -------------------------------------------------
        # Reservar
        # -------------------------------------------------

        cursor.execute("""
            UPDATE rt_boletos
            SET
                estado = 'reservado',
                origen = 'publicidad',
                reserva_token = %s,
                reservado_en = CURRENT_TIMESTAMP
            WHERE
                id = %s
        """, (
            token,
            boleto["id"]
        ))

        db.commit()

        # -------------------------------------------------
        # Guardar la reserva en la sesión
        # -------------------------------------------------

        session["rifa_id"] = rifa_id
        session["boleto_id"] = boleto["id"]
        session["boleto_numero"] = boleto["numero"]
        session["reserva_token"] = token
        session["videos_completados"] = 0

        # -------------------------------------------------
        # Por ahora mostramos pantalla de prueba.
        #
        # Aquí posteriormente irá Google Rewarded.
        # -------------------------------------------------

        return redirect(
            url_for(
                "publicidad",
                rifa_id=rifa_id
            )
        )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL RESERVAR BOLETO:",
            error
        )

        flash(
            "Ocurrió un error al reservar el boleto.",
            "error"
        )

        return redirect(
            url_for(
                "participar",
                rifa_id=rifa_id
            )
        )

    finally:

        db.close()


# =========================================================
# PANTALLA DE PUBLICIDAD
# =========================================================

@app.route("/rifas/publicidad/<int:rifa_id>")
def publicidad(rifa_id):

    # -----------------------------------------------------
    # Verificar sesión
    # -----------------------------------------------------

    if session.get("rifa_id") != rifa_id:

        flash(
            "No tienes una reserva activa.",
            "error"
        )

        return redirect(
            url_for(
                "participar",
                rifa_id=rifa_id
            )
        )

    boleto_id = session.get("boleto_id")
    token = session.get("reserva_token")

    if not boleto_id or not token:

        flash(
            "La reserva no es válida.",
            "error"
        )

        return redirect(
            url_for(
                "participar",
                rifa_id=rifa_id
            )
        )

    db = get_db()

    try:

        cursor = db.cursor()

        # -------------------------------------------------
        # Comprobar que la reserva siga vigente
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                b.id,
                b.rifa_id,
                b.numero,
                b.estado,
                b.reserva_token,
                b.reservado_en,
                r.titulo
            FROM rt_boletos b
            INNER JOIN rt_rifas r
                ON r.id = b.rifa_id
            WHERE
                b.id = %s
                AND b.rifa_id = %s
        """, (
            boleto_id,
            rifa_id
        ))

        boleto = cursor.fetchone()

        if not boleto:

            session.clear()

            flash(
                "La reserva no existe.",
                "error"
            )

            return redirect(url_for("rifas"))

        # -------------------------------------------------
        # Verificar token
        # -------------------------------------------------

        if boleto["reserva_token"] != token:

            session.clear()

            flash(
                "La reserva no pertenece a esta sesión.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # -------------------------------------------------
        # Verificar estado
        # -------------------------------------------------

        if boleto["estado"] != "reservado":

            session.clear()

            flash(
                "El boleto ya no está reservado.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # -------------------------------------------------
        # Verificar tiempo
        # -------------------------------------------------

        if boleto["reservado_en"]:

            limite = boleto["reservado_en"] + timedelta(
                minutes=TIEMPO_RESERVA_MINUTOS
            )

            if datetime.now() > limite:

                cursor.execute("""
                    UPDATE rt_boletos
                    SET
                        estado = 'disponible',
                        origen = NULL,
                        reserva_token = NULL,
                        reservado_en = NULL
                    WHERE id = %s
                """, (boleto_id,))

                db.commit()

                session.clear()

                flash(
                    "El tiempo de reserva terminó. "
                    "Puedes seleccionar otro boleto.",
                    "error"
                )

                return redirect(
                    url_for(
                        "participar",
                        rifa_id=rifa_id
                    )
                )

        videos_completados = session.get(
            "videos_completados",
            0
        )

        return render_template(
            "publicidad.html",
            boleto=boleto,
            videos_completados=videos_completados,
            videos_totales=5
        )

    finally:

        db.close()


# =========================================================
# PANEL ADMINISTRATIVO
# =========================================================

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


# =========================================================
# NUEVA RIFA
# =========================================================

@app.route("/rifas/admin/nueva")
def nueva_rifa():

    return render_template(
        "nueva_rifa.html"
    )


# =========================================================
# CREAR RIFA
# =========================================================

@app.route(
    "/rifas/admin/nueva",
    methods=["POST"]
)
def crear_rifa():

    titulo = request.form.get(
        "titulo",
        ""
    ).strip()

    descripcion = request.form.get(
        "descripcion",
        ""
    ).strip()

    imagen_url = request.form.get(
        "imagen_url",
        ""
    ).strip()

    cantidad_boletos = request.form.get(
        "cantidad_boletos",
        ""
    ).strip()

    precio_boleto = request.form.get(
        "precio_boleto",
        ""
    ).strip()

    fecha_inicio = request.form.get(
        "fecha_inicio",
        ""
    ).strip()

    fecha_fin = request.form.get(
        "fecha_fin",
        ""
    ).strip()

    fecha_sorteo = request.form.get(
        "fecha_sorteo",
        ""
    ).strip()

    if not titulo:

        flash(
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

    try:

        cantidad_boletos = int(
            cantidad_boletos
        )

        if cantidad_boletos <= 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "La cantidad de boletos debe ser mayor que cero.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

    try:

        precio_boleto = float(
            precio_boleto
        )

        if precio_boleto < 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "El precio del boleto no es válido.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

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

        return redirect(
            url_for("admin_rifas")
        )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL CREAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al crear la rifa.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

    finally:

        db.close()


# =========================================================
# EDITAR RIFA
# =========================================================

@app.route(
    "/rifas/admin/editar/<int:rifa_id>"
)
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

            return redirect(
                url_for("admin_rifas")
            )

        return render_template(
            "nueva_rifa.html",
            rifa=rifa,
            modo_edicion=True
        )

    finally:

        db.close()


# =========================================================
# ACTUALIZAR RIFA
# =========================================================

@app.route(
    "/rifas/admin/editar/<int:rifa_id>",
    methods=["POST"]
)
def actualizar_rifa(rifa_id):

    titulo = request.form.get(
        "titulo",
        ""
    ).strip()

    descripcion = request.form.get(
        "descripcion",
        ""
    ).strip()

    imagen_url = request.form.get(
        "imagen_url",
        ""
    ).strip()

    cantidad_boletos = request.form.get(
        "cantidad_boletos",
        ""
    ).strip()

    precio_boleto = request.form.get(
        "precio_boleto",
        ""
    ).strip()

    fecha_inicio = request.form.get(
        "fecha_inicio",
        ""
    ).strip()

    fecha_fin = request.form.get(
        "fecha_fin",
        ""
    ).strip()

    fecha_sorteo = request.form.get(
        "fecha_sorteo",
        ""
    ).strip()

    if not titulo:

        flash(
            "El título es obligatorio.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
        )

    try:

        cantidad_boletos = int(
            cantidad_boletos
        )

        if cantidad_boletos <= 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "La cantidad de boletos no es válida.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
        )

    try:

        precio_boleto = float(
            precio_boleto
        )

        if precio_boleto < 0:
            raise ValueError

    except (ValueError, TypeError):

        flash(
            "El precio del boleto no es válido.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
        )

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

        db.commit()

        flash(
            "Rifa actualizada correctamente.",
            "success"
        )

        return redirect(
            url_for("admin_rifas")
        )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL ACTUALIZAR:",
            error
        )

        flash(
            "Ocurrió un error al actualizar.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
        )

    finally:

        db.close()


# =========================================================
# PUBLICAR
# =========================================================

@app.route(
    "/rifas/admin/publicar/<int:rifa_id>",
    methods=["POST"]
)
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
                "La rifa no existe o no está en borrador.",
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

        print(
            "ERROR AL PUBLICAR:",
            error
        )

        flash(
            "Ocurrió un error al publicar.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# =========================================================
# FINALIZAR
# =========================================================

@app.route(
    "/rifas/admin/finalizar/<int:rifa_id>",
    methods=["POST"]
)
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

        print(
            "ERROR AL FINALIZAR:",
            error
        )

        flash(
            "Ocurrió un error al finalizar.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# =========================================================
# CANCELAR
# =========================================================

@app.route(
    "/rifas/admin/cancelar/<int:rifa_id>",
    methods=["POST"]
)
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
                "La rifa no existe o no puede cancelarse.",
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

        print(
            "ERROR AL CANCELAR:",
            error
        )

        flash(
            "Ocurrió un error al cancelar.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# =========================================================
# EJECUCION LOCAL
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=True
    )