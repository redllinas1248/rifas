import os
import secrets

from datetime import (
    datetime,
    timedelta
)

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


# ============================================================
# CONFIGURACIÓN DE RESERVAS
#
# Horas que un boleto puede estar "reservado" sin actividad
# antes de liberarse automáticamente.
#
# Se puede sobreescribir con la variable de entorno
# RESERVA_TTL_HORAS.
# ============================================================

RESERVA_TTL_HORAS = int(
    os.getenv(
        "RESERVA_TTL_HORAS",
        "1"
    )
)


# ============================================================
# HELPER: LIBERAR RESERVAS EXPIRADAS
#
# Se llama "lazy": no usamos cron ni Celery. Cada vez que
# alguien entra a una ruta relevante, primero limpiamos.
#
# Devuelve la cantidad de boletos liberados.
# ============================================================

def liberar_reservas_expiradas(db):

    cursor = db.cursor()

    # --------------------------------------------------------
    # Calcular el punto de corte
    # --------------------------------------------------------

    cutoff = datetime.now() - timedelta(
        hours=RESERVA_TTL_HORAS
    )

    # --------------------------------------------------------
    # Buscar boletos reservados cuya reserva ya expiró
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            id
        FROM rt_boletos
        WHERE
            estado = 'reservado'
            AND reservado_en IS NOT NULL
            AND reservado_en < %s
    """, (
        cutoff,
    ))

    filas = cursor.fetchall()

    if not filas:

        return 0

    ids = [fila["id"] for fila in filas]

    # --------------------------------------------------------
    # Borrar el progreso de publicidad asociado
    # (para que si alguien más reserve, empiece limpio)
    # --------------------------------------------------------

    cursor.execute("""
        DELETE FROM rt_progreso_publicidad
        WHERE boleto_id = ANY(%s)
    """, (
        ids,
    ))

    # --------------------------------------------------------
    # Liberar los boletos
    # --------------------------------------------------------

    cursor.execute("""
        UPDATE rt_boletos
        SET
            estado = 'disponible',
            reserva_token = NULL,
            reservado_en = NULL,
            actualizado_en = NOW()
        WHERE id = ANY(%s)
    """, (
        ids,
    ))

    return len(ids)


# ============================================================
# INICIO
# ============================================================

@app.route("/")
def inicio():

    db = get_db()

    try:

        # ----------------------------------------------------
        # Limpiar reservas expiradas
        # ----------------------------------------------------

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        # ----------------------------------------------------
        # Traer las 3 rifas activas más recientes
        # ----------------------------------------------------

        cursor = db.cursor()

        cursor.execute("""
            SELECT
                id,
                titulo,
                descripcion,
                imagen_url,
                cantidad_boletos,
                precio_boleto
            FROM rt_rifas
            WHERE estado = 'activa'
            ORDER BY creado_en DESC
            LIMIT 3
        """)

        rifas_destacadas = cursor.fetchall()

        return render_template(
            "index.html",
            rifas_destacadas=rifas_destacadas
        )

    finally:

        db.close()


@app.route("/privacidad")
def privacidad():
    return render_template("privacidad.html")

@app.route("/terminos")
def terminos():
    return render_template("terminos.html")

@app.route("/contacto")
def contacto():
    return render_template("contacto.html")


# ============================================================
# LISTADO PUBLICO DE RIFAS
# ============================================================

@app.route("/rifas")
def rifas():

    db = get_db()

    try:

        # ----------------------------------------------------
        # Limpiar reservas expiradas
        # ----------------------------------------------------

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        # ----------------------------------------------------
        # Listar rifas activas
        # ----------------------------------------------------

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


# ============================================================
# PARTICIPAR
# ============================================================

@app.route("/rifas/participar/<int:rifa_id>")
def participar(rifa_id):

    db = get_db()

    try:

        # ----------------------------------------------------
        # Limpiar reservas expiradas ANTES de listar
        # ----------------------------------------------------

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        cursor = db.cursor()

        # ----------------------------------------------------
        # Buscar rifa activa
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                titulo,
                descripcion,
                imagen_url,
                cantidad_boletos,
                precio_boleto,
                estado
            FROM rt_rifas
            WHERE id = %s
              AND estado = 'activa'
        """, (
            rifa_id,
        ))

        rifa = cursor.fetchone()

        if not rifa:

            flash(
                "La rifa no existe o ya no está disponible.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Boletos disponibles
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                numero,
                estado
            FROM rt_boletos
            WHERE rifa_id = %s
              AND estado = 'disponible'
            ORDER BY numero ASC
        """, (
            rifa_id,
        ))

        boletos = cursor.fetchall()

        return render_template(
            "participar.html",
            rifa=rifa,
            boletos=boletos
        )

    finally:

        db.close()


# ============================================================
# RESERVAR BOLETO
# ============================================================

@app.route(
    "/rifas/participar/<int:rifa_id>/reservar",
    methods=["POST"]
)
def reservar_boleto(rifa_id):

    boleto_id = request.form.get(
        "boleto_id",
        ""
    ).strip()

    if not boleto_id:

        flash(
            "Selecciona un boleto.",
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

        # ----------------------------------------------------
        # Limpiar reservas expiradas primero
        # (así el boleto seleccionado podría volver a estar
        #  disponible si su reserva previa expiró)
        # ----------------------------------------------------

        liberar_reservas_expiradas(db)

        cursor = db.cursor()

        # ----------------------------------------------------
        # Comprobar boleto disponible
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                rifa_id,
                numero,
                estado,
                reserva_token,
                reservado_en
            FROM rt_boletos
            WHERE id = %s
              AND rifa_id = %s
              AND estado = 'disponible'
            FOR UPDATE
        """, (
            boleto_id,
            rifa_id
        ))

        boleto = cursor.fetchone()

        if not boleto:

            db.rollback()

            flash(
                "Ese boleto ya no está disponible. Selecciona otro.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # ----------------------------------------------------
        # Crear token secreto
        # ----------------------------------------------------

        reserva_token = secrets.token_urlsafe(32)

        # ----------------------------------------------------
        # Reservar boleto
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE rt_boletos
            SET
                estado = 'reservado',
                reserva_token = %s,
                reservado_en = NOW(),
                actualizado_en = NOW()
            WHERE
                id = %s
                AND rifa_id = %s
                AND estado = 'disponible'
        """, (
            reserva_token,
            boleto["id"],
            rifa_id
        ))

        if cursor.rowcount != 1:

            db.rollback()

            flash(
                "No fue posible reservar el boleto.",
                "error"
            )

            return redirect(
                url_for(
                    "participar",
                    rifa_id=rifa_id
                )
            )

        # ----------------------------------------------------
        # Guardar reserva
        # ----------------------------------------------------

        db.commit()

        session["reserva_token"] = reserva_token
        session["boleto_id"] = boleto["id"]
        session["rifa_id"] = rifa_id

        return redirect(
            url_for(
                "reserva",
                reserva_token=reserva_token
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


# ============================================================
# PANTALLA DE RESERVA
# ============================================================

@app.route("/rifas/reserva/<reserva_token>")
def reserva(reserva_token):

    db = get_db()

    try:

        # ----------------------------------------------------
        # Limpiar reservas expiradas primero
        # ----------------------------------------------------

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        cursor = db.cursor()

        # ----------------------------------------------------
        # Buscar boleto reservado
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                b.id,
                b.rifa_id,
                b.numero,
                b.estado,
                b.reserva_token,
                b.reservado_en,
                b.nombre,
                b.numero_especial,
                r.titulo,
                r.descripcion,
                r.imagen_url
            FROM rt_boletos b
            INNER JOIN rt_rifas r
                ON r.id = b.rifa_id
            WHERE b.reserva_token = %s
        """, (
            reserva_token,
        ))

        boleto = cursor.fetchone()

        if not boleto:

            flash(
                "La reserva expiró o ya no está disponible. "
                "Puedes elegir otro boleto.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Estados permitidos
        # ----------------------------------------------------

        if boleto["estado"] not in (
            "reservado",
            "acreditado",
            "asignado"
        ):

            flash(
                "Esta reserva ya no está disponible.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Buscar progreso de publicidad
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                boleto_id,
                videos_completados,
                total_videos,
                estado,
                creado_en,
                actualizado_en
            FROM rt_progreso_publicidad
            WHERE boleto_id = %s
            LIMIT 1
        """, (
            boleto["id"],
        ))

        progreso = cursor.fetchone()

        # ----------------------------------------------------
        # Crear progreso si no existe
        # ----------------------------------------------------

        if not progreso:

            cursor.execute("""
                INSERT INTO rt_progreso_publicidad (
                    boleto_id,
                    videos_completados,
                    total_videos,
                    estado,
                    creado_en,
                    actualizado_en
                )
                VALUES (
                    %s,
                    0,
                    5,
                    'en_proceso',
                    NOW(),
                    NOW()
                )
                RETURNING
                    id,
                    boleto_id,
                    videos_completados,
                    total_videos,
                    estado,
                    creado_en,
                    actualizado_en
            """, (
                boleto["id"],
            ))

            progreso = cursor.fetchone()

            db.commit()

        return render_template(
            "reserva.html",
            boleto=boleto,
            progreso=progreso
        )

    finally:

        db.close()


# ============================================================
# COMPLETAR VIDEO
#
# TEMPORAL
#
# Actualmente el botón suma un video.
#
# MÁS ADELANTE:
# Google Rewarded Ads será quien confirme realmente
# que el usuario terminó el anuncio.
# ============================================================

@app.route(
    "/rifas/reserva/<reserva_token>/video",
    methods=["POST"]
)
def completar_video(reserva_token):

    db = get_db()

    try:

        cursor = db.cursor()

        # ----------------------------------------------------
        # Limpiar reservas expiradas primero
        # ----------------------------------------------------

        liberar_reservas_expiradas(db)

        # ----------------------------------------------------
        # Buscar boleto
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                rifa_id,
                numero,
                estado,
                reserva_token
            FROM rt_boletos
            WHERE reserva_token = %s
            FOR UPDATE
        """, (
            reserva_token,
        ))

        boleto = cursor.fetchone()

        if not boleto:

            db.rollback()

            flash(
                "Reserva no encontrada o expirada.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Solo permitir videos mientras esté reservado
        # ----------------------------------------------------

        if boleto["estado"] != "reservado":

            db.rollback()

            flash(
                "Esta reserva ya no puede recibir publicidad.",
                "error"
            )

            return redirect(
                url_for(
                    "reserva",
                    reserva_token=reserva_token
                )
            )

        # ----------------------------------------------------
        # Buscar progreso
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                videos_completados,
                total_videos,
                estado
            FROM rt_progreso_publicidad
            WHERE boleto_id = %s
            FOR UPDATE
        """, (
            boleto["id"],
        ))

        progreso = cursor.fetchone()

        # ----------------------------------------------------
        # Crear progreso si no existe
        # ----------------------------------------------------

        if not progreso:

            cursor.execute("""
                INSERT INTO rt_progreso_publicidad (
                    boleto_id,
                    videos_completados,
                    total_videos,
                    estado,
                    creado_en,
                    actualizado_en
                )
                VALUES (
                    %s,
                    0,
                    5,
                    'en_proceso',
                    NOW(),
                    NOW()
                )
                RETURNING
                    id,
                    videos_completados,
                    total_videos,
                    estado
            """, (
                boleto["id"],
            ))

            progreso = cursor.fetchone()

        # ----------------------------------------------------
        # Valores actuales
        # ----------------------------------------------------

        videos_actuales = progreso[
            "videos_completados"
        ]

        total_videos = progreso[
            "total_videos"
        ]

        # ----------------------------------------------------
        # Evitar superar los 5
        # ----------------------------------------------------

        if videos_actuales >= total_videos:

            db.rollback()

            flash(
                "Los 5 videos ya fueron completados.",
                "success"
            )

            return redirect(
                url_for(
                    "reserva",
                    reserva_token=reserva_token
                )
            )

        # ----------------------------------------------------
        # Sumar UN video
        # ----------------------------------------------------

        nuevos_videos = (
            videos_actuales + 1
        )

        if nuevos_videos >= total_videos:

            nuevo_estado = "completado"

        else:

            nuevo_estado = "en_proceso"

        # ----------------------------------------------------
        # Actualizar progreso
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE rt_progreso_publicidad
            SET
                videos_completados = %s,
                estado = %s,
                actualizado_en = NOW()
            WHERE boleto_id = %s
        """, (
            nuevos_videos,
            nuevo_estado,
            boleto["id"]
        ))

        # ----------------------------------------------------
        # Acreditar boleto al completar los 5
        # ----------------------------------------------------

        if nuevos_videos >= total_videos:

            cursor.execute("""
                UPDATE rt_boletos
                SET
                    estado = 'acreditado',
                    actualizado_en = NOW()
                WHERE
                    id = %s
                    AND estado = 'reservado'
            """, (
                boleto["id"],
            ))

        db.commit()

        return redirect(
            url_for(
                "reserva",
                reserva_token=reserva_token
            )
        )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL REGISTRAR VIDEO:",
            error
        )

        flash(
            "No fue posible registrar el video.",
            "error"
        )

        return redirect(
            url_for(
                "reserva",
                reserva_token=reserva_token
            )
        )

    finally:

        db.close()


# ============================================================
# FORMULARIO DE DATOS DEL PARTICIPANTE
#
# Solo accesible cuando el boleto esté "acreditado"
# ============================================================

@app.route("/rifas/reserva/<reserva_token>/datos")
def datos_participante(reserva_token):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            SELECT
                b.id,
                b.rifa_id,
                b.numero,
                b.estado,
                b.reserva_token,
                b.nombre,
                b.numero_especial,
                r.titulo,
                r.descripcion,
                r.imagen_url
            FROM rt_boletos b
            INNER JOIN rt_rifas r
                ON r.id = b.rifa_id
            WHERE b.reserva_token = %s
        """, (
            reserva_token,
        ))

        boleto = cursor.fetchone()

        if not boleto:

            flash(
                "La reserva no existe.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Solo permitir si ya completó los 5 videos
        # ----------------------------------------------------

        if boleto["estado"] not in (
            "acreditado",
            "asignado"
        ):

            flash(
                "Primero debes completar los 5 videos.",
                "error"
            )

            return redirect(
                url_for(
                    "reserva",
                    reserva_token=reserva_token
                )
            )

        # ----------------------------------------------------
        # Si ya está asignado, mandarlo directo a la tarjeta
        # ----------------------------------------------------

        if boleto["estado"] == "asignado":

            return redirect(
                url_for(
                    "tarjeta_participacion",
                    reserva_token=reserva_token
                )
            )

        return render_template(
            "datos_participante.html",
            boleto=boleto
        )

    finally:

        db.close()


# ============================================================
# GUARDAR DATOS DEL PARTICIPANTE
# ============================================================

@app.route(
    "/rifas/reserva/<reserva_token>/datos",
    methods=["POST"]
)
def guardar_datos_participante(reserva_token):

    nombre = request.form.get(
        "nombre",
        ""
    ).strip()

    numero_especial = request.form.get(
        "numero_especial",
        ""
    ).strip()

    # --------------------------------------------------------
    # Validar nombre
    # --------------------------------------------------------

    if not nombre:

        flash(
            "El nombre es obligatorio.",
            "error"
        )

        return redirect(
            url_for(
                "datos_participante",
                reserva_token=reserva_token
            )
        )

    if len(nombre) > 200:

        flash(
            "El nombre es demasiado largo (máximo 200 caracteres).",
            "error"
        )

        return redirect(
            url_for(
                "datos_participante",
                reserva_token=reserva_token
            )
        )

    # --------------------------------------------------------
    # Validar número especial (opcional)
    #
    # En la BD es VARCHAR(50), así que lo tratamos como texto.
    # --------------------------------------------------------

    if numero_especial and len(numero_especial) > 50:

        flash(
            "El número especial es demasiado largo (máximo 50 caracteres).",
            "error"
        )

        return redirect(
            url_for(
                "datos_participante",
                reserva_token=reserva_token
            )
        )

    if not numero_especial:

        numero_especial = None

    db = get_db()

    try:

        cursor = db.cursor()

        # ----------------------------------------------------
        # Bloquear fila para evitar doble envío
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                estado
            FROM rt_boletos
            WHERE reserva_token = %s
            FOR UPDATE
        """, (
            reserva_token,
        ))

        boleto = cursor.fetchone()

        if not boleto:

            db.rollback()

            flash(
                "Reserva no encontrada.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Solo permitir si aún no fue asignado
        # ----------------------------------------------------

        if boleto["estado"] not in (
            "acreditado",
            "asignado"
        ):

            db.rollback()

            flash(
                "Esta reserva no puede registrar datos todavía.",
                "error"
            )

            return redirect(
                url_for(
                    "reserva",
                    reserva_token=reserva_token
                )
            )

        # ----------------------------------------------------
        # Guardar datos y pasar a "asignado"
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE rt_boletos
            SET
                nombre = %s,
                numero_especial = %s,
                estado = 'asignado',
                asignado_en = NOW(),
                actualizado_en = NOW()
            WHERE
                id = %s
                AND estado IN ('acreditado', 'asignado')
        """, (
            nombre,
            numero_especial,
            boleto["id"]
        ))

        if cursor.rowcount != 1:

            db.rollback()

            flash(
                "No fue posible guardar los datos.",
                "error"
            )

            return redirect(
                url_for(
                    "datos_participante",
                    reserva_token=reserva_token
                )
            )

        db.commit()

        return redirect(
            url_for(
                "tarjeta_participacion",
                reserva_token=reserva_token
            )
        )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL GUARDAR DATOS:",
            error
        )

        flash(
            "Ocurrió un error al guardar los datos.",
            "error"
        )

        return redirect(
            url_for(
                "datos_participante",
                reserva_token=reserva_token
            )
        )

    finally:

        db.close()


# ============================================================
# TARJETA FINAL DE PARTICIPACIÓN
# ============================================================

@app.route("/rifas/tarjeta/<reserva_token>")
def tarjeta_participacion(reserva_token):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            SELECT
                b.id,
                b.rifa_id,
                b.numero,
                b.estado,
                b.reserva_token,
                b.nombre,
                b.numero_especial,
                b.creado_en,
                b.asignado_en,
                r.titulo,
                r.descripcion,
                r.imagen_url,
                r.fecha_sorteo
            FROM rt_boletos b
            INNER JOIN rt_rifas r
                ON r.id = b.rifa_id
            WHERE b.reserva_token = %s
        """, (
            reserva_token,
        ))

        boleto = cursor.fetchone()

        if not boleto:

            flash(
                "La participación no existe.",
                "error"
            )

            return redirect(
                url_for("rifas")
            )

        # ----------------------------------------------------
        # Solo mostrar si ya está asignado
        # ----------------------------------------------------

        if boleto["estado"] != "asignado":

            flash(
                "Aún debes completar los pasos para ver tu tarjeta.",
                "error"
            )

            return redirect(
                url_for(
                    "reserva",
                    reserva_token=reserva_token
                )
            )

        return render_template(
            "tarjeta_participacion.html",
            boleto=boleto
        )

    finally:

        db.close()


# ============================================================
# PANEL ADMINISTRATIVO
# ============================================================

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


# ============================================================
# NUEVA RIFA
# ============================================================

@app.route("/rifas/admin/nueva")
def nueva_rifa():

    return render_template(
        "nueva_rifa.html"
    )


# ============================================================
# CREAR RIFA
# ============================================================

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

    # --------------------------------------------------------
    # Validar título
    # --------------------------------------------------------

    if not titulo:

        flash(
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

    # --------------------------------------------------------
    # Validar cantidad
    # --------------------------------------------------------

    try:

        cantidad_boletos = int(
            cantidad_boletos
        )

        if cantidad_boletos <= 0:
            raise ValueError

    except (
        ValueError,
        TypeError
    ):

        flash(
            "La cantidad de boletos debe ser mayor que cero.",
            "error"
        )

        return redirect(
            url_for("nueva_rifa")
        )

    # --------------------------------------------------------
    # Validar precio
    # --------------------------------------------------------

    try:

        precio_boleto = float(
            precio_boleto
        )

        if precio_boleto < 0:
            raise ValueError

    except (
        ValueError,
        TypeError
    ):

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

        # ----------------------------------------------------
        # Crear rifa
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Crear boletos
        # ----------------------------------------------------

        for numero in range(
            1,
            cantidad_boletos + 1
        ):

            cursor.execute("""
                INSERT INTO rt_boletos (
                    rifa_id,
                    numero,
                    estado,
                    origen,
                    creado_en
                )
                VALUES (
                    %s,
                    %s,
                    'disponible',
                    'sistema',
                    NOW()
                )
            """, (
                rifa_id,
                numero
            ))

        db.commit()

        flash(
            f"Rifa creada correctamente con {cantidad_boletos} boletos.",
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


# ============================================================
# EDITAR RIFA
# ============================================================

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
        """, (
            rifa_id,
        ))

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


# ============================================================
# ACTUALIZAR RIFA
# ============================================================

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

    # --------------------------------------------------------
    # Validar título
    # --------------------------------------------------------

    if not titulo:

        flash(
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
        )

    # --------------------------------------------------------
    # Validar cantidad
    # --------------------------------------------------------

    try:

        cantidad_boletos = int(
            cantidad_boletos
        )

        if cantidad_boletos <= 0:
            raise ValueError

    except (
        ValueError,
        TypeError
    ):

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

    # --------------------------------------------------------
    # Validar precio
    # --------------------------------------------------------

    try:

        precio_boleto = float(
            precio_boleto
        )

        if precio_boleto < 0:
            raise ValueError

    except (
        ValueError,
        TypeError
    ):

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

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe.",
                "error"
            )

            return redirect(
                url_for("admin_rifas")
            )

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
            "ERROR AL ACTUALIZAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al actualizar la rifa.",
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


# ============================================================
# PUBLICAR RIFA
# ============================================================

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
        """, (
            rifa_id,
        ))

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
            "ERROR AL PUBLICAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al publicar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# ============================================================
# FINALIZAR RIFA
# ============================================================

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
        """, (
            rifa_id,
        ))

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
            "ERROR AL FINALIZAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al finalizar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# ============================================================
# CANCELAR RIFA
# ============================================================

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
        """, (
            rifa_id,
        ))

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
            "ERROR AL CANCELAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al cancelar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# ============================================================
# EJECUCIÓN LOCAL
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )