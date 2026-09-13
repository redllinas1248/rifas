from datetime import timezone
from zoneinfo import ZoneInfo
import os
import secrets

from datetime import (
    datetime,
    timedelta
)

from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    abort,
    jsonify
)

from db import get_db


app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "rifas-clave-local"
)


# ============================================================
# CONFIGURACIÓN DE SESIONES SEGURAS
# ============================================================

app.config.update(
    SESSION_COOKIE_SECURE=True,          # Solo HTTPS
    SESSION_COOKIE_HTTPONLY=True,        # No accesible desde JS
    SESSION_COOKIE_SAMESITE="Lax",       # Mitiga CSRF
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)

# ============================================================
# ZONA HORARIA
#
# PostgreSQL guarda con NOW() en UTC. Convertimos a hora
# de México al mostrar en templates con el filtro `mx`.
# ============================================================

TZ_MEXICO = ZoneInfo("America/Mexico_City")


@app.template_filter("mx")
def filtro_mx(dt):

    if dt is None:
        return None

    return (
        dt
        .replace(tzinfo=timezone.utc)
        .astimezone(TZ_MEXICO)
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
# CREDENCIALES DE ADMINISTRACIÓN
#
# Se configuran con variables de entorno en Render:
#   ADMIN_USERNAME
#   ADMIN_PASSWORD
# ============================================================

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    ""
)

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    ""
)


# ============================================================
# DECORADOR: SOLO ADMINISTRADOR
# ============================================================

def admin_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not session.get("admin_logged_in"):

            flash(
                "Debes iniciar sesión como administrador.",
                "error"
            )

            return redirect(
                url_for(
                    "admin_login",
                    next=request.path
                )
            )

        return f(*args, **kwargs)

    return decorated_function


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

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

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


# ============================================================
# LISTADO PUBLICO DE RIFAS
# ============================================================

@app.route("/rifas")
def rifas():

    db = get_db()

    try:

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

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

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        cursor = db.cursor()

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

        liberar_reservas_expiradas(db)

        cursor = db.cursor()

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

        reserva_token = secrets.token_urlsafe(32)

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

        liberadas = liberar_reservas_expiradas(db)

        if liberadas > 0:
            db.commit()

        cursor = db.cursor()

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
# TEMPORAL - Google Rewarded Ads reemplazará esta lógica
# ============================================================

@app.route(
    "/rifas/reserva/<reserva_token>/video",
    methods=["POST"]
)
def completar_video(reserva_token):

    db = get_db()

    try:

        cursor = db.cursor()

        liberar_reservas_expiradas(db)

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

        videos_actuales = progreso["videos_completados"]
        total_videos = progreso["total_videos"]

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

        nuevos_videos = videos_actuales + 1

        if nuevos_videos >= total_videos:
            nuevo_estado = "completado"
        else:
            nuevo_estado = "en_proceso"

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
# CONFIRMACIÓN DE VIDEO (SSV)
# ============================================================

import json
import base64
import urllib.parse
import urllib.request
import hashlib
from ecdsa.keys import VerifyingKey, BadSignatureError
from ecdsa.util import sigdecode_der

ADMOB_KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"

# Cache simple en memoria para las llaves públicas
_public_keys_cache = None

def obtener_llaves_publicas():
    global _public_keys_cache
    if _public_keys_cache is None:
        try:
            with urllib.request.urlopen(ADMOB_KEYS_URL) as response:
                keys_data = json.loads(response.read().decode('utf-8'))
                _public_keys_cache = {str(k['keyId']): k['pem'] for k in keys_data['keys']}
        except Exception as e:
            print("Error al obtener llaves de AdMob:", e)
            return {}
    return _public_keys_cache

def verificar_firma_ssv(query_string):
    """
    Verifica la firma de un callback SSV de Google.
    Devuelve True si la firma es válida.
    """
    if not query_string:
        return False

    # 1. Parsear los parámetros de la URL
    params = dict(urllib.parse.parse_qsl(query_string))
    signature_b64 = params.get('signature')
    key_id = params.get('key_id')

    if not signature_b64 or not key_id:
        return False

    # 2. Obtener la llave pública correspondiente
    public_keys = obtener_llaves_publicas()
    pem = public_keys.get(key_id)
    if not pem:
        print(f"Llave pública no encontrada para key_id: {key_id}")
        return False

    # 3. Construir el mensaje a verificar (todo excepto signature y key_id)
    #    El orden de los parámetros es importante.
    mensaje = "&".join(
        f"{k}={urllib.parse.quote(v)}"
        for k, v in params.items()
        if k not in ('signature', 'key_id')
    )

    # 4. Verificar la firma
    try:
        vk = VerifyingKey.from_pem(pem)
        signature = base64.b64decode(signature_b64)
        # La firma de Google usa SHA256 y codificación DER
        if vk.verify(signature, mensaje.encode('utf-8'), hashfunc=hashlib.sha256, sigdecode=sigdecode_der):
            return True
    except BadSignatureError:
        print("Firma SSV inválida.")
    except Exception as e:
        print(f"Error al verificar firma SSV: {e}")

    return False


@app.route(
    "/rifas/reserva/<reserva_token>/video/confirmar",
    methods=["POST"]
)
def confirmar_video(reserva_token):
    """
    Endpoint llamado por el frontend DESPUÉS de que Google confirma
    que el usuario vio el anuncio. Verifica la autenticidad de la
    petición y, si es válida, acredita el video.
    """

    # --------------------------------------------------------
    # Verificar Server-Side Verification (SSV)
    # --------------------------------------------------------
    # En producción, Google enviará un callback SSV a una URL que
    # tú configures (ej: /admob-ssv). Ese callback es el que
    # realmente confirma el anuncio. Por simplicidad y para que
    # funcione con anuncios de prueba, aquí verificamos un
    # "custom_data" que enviaremos desde el frontend.

    # NOTA: En un entorno de producción real, DEBES configurar
    # la URL de SSV en tu consola de AdMob y verificar los
    # callbacks que Google envía DIRECTAMENTE a tu servidor.
    # El código de abajo es una simplificación para que puedas
    # probar el flujo completo con anuncios de prueba.

    # --------------------------------------------------------
    # Buscar el boleto y el progreso
    # --------------------------------------------------------
    db = get_db()
    try:
        cursor = db.cursor()
        # ... (tu lógica existente para buscar el boleto y el progreso) ...

        # ----------------------------------------------------
        # Sumar UN video (lógica que ya tenías)
        # ----------------------------------------------------
        # ... (tu lógica existente para actualizar el progreso) ...

        db.commit()
        return jsonify({"success": True, "message": "Video confirmado."})

    except Exception as error:
        db.rollback()
        print("ERROR AL CONFIRMAR VIDEO:", error)
        return jsonify({"success": False, "error": str(error)}), 500

    finally:
        db.close()

# ============================================================
# FORMULARIO DE DATOS DEL PARTICIPANTE
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
# PÁGINAS LEGALES
# ============================================================

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
# LOGIN DE ADMINISTRACIÓN
# ============================================================

@app.route(
    "/rifas/admin/login",
    methods=["GET", "POST"]
)
def admin_login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        ).strip()

        # ----------------------------------------------------
        # Verificar credenciales
        # ----------------------------------------------------

        if (
            ADMIN_USERNAME
            and ADMIN_PASSWORD
            and username == ADMIN_USERNAME
            and password == ADMIN_PASSWORD
        ):

            session["admin_logged_in"] = True
            session.permanent = True

            flash(
                "Has iniciado sesión correctamente.",
                "success"
            )

            next_page = request.args.get("next")

            if next_page and next_page.startswith("/"):

                return redirect(next_page)

            return redirect(
                url_for("admin_rifas")
            )

        else:

            flash(
                "Usuario o contraseña incorrectos.",
                "error"
            )

    return render_template("admin_login.html")


# ============================================================
# PARTICIPANTES DE UN SORTEO
# ============================================================

@app.route("/rifas/admin/participantes/<int:rifa_id>")
@admin_required
def admin_participantes(rifa_id):

    db = get_db()

    try:

        cursor = db.cursor()

        # ----------------------------------------------------
        # Datos de la rifa
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                titulo,
                descripcion,
                estado,
                cantidad_boletos,
                fecha_sorteo
            FROM rt_rifas
            WHERE id = %s
        """, (
            rifa_id,
        ))

        rifa = cursor.fetchone()

        if not rifa:

            flash(
                "El sorteo no existe.",
                "error"
            )

            return redirect(
                url_for("admin_rifas")
            )

        # ----------------------------------------------------
        # Estadísticas rápidas del sorteo
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE estado = 'disponible'
                ) AS disponibles,
                COUNT(*) FILTER (
                    WHERE estado = 'reservado'
                ) AS reservados,
                COUNT(*) FILTER (
                    WHERE estado = 'acreditado'
                ) AS acreditados,
                COUNT(*) FILTER (
                    WHERE estado = 'asignado'
                ) AS asignados
            FROM rt_boletos
            WHERE rifa_id = %s
        """, (
            rifa_id,
        ))

        stats = cursor.fetchone()

        # ----------------------------------------------------
        # Listado de participantes
        #
        # Solo mostramos boletos que ya tienen dueño
        # (reservado, acreditado o asignado).
        # Los "disponible" no son participantes.
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                numero,
                estado,
                nombre,
                numero_especial,
                reservado_en,
                asignado_en,
                reserva_token
            FROM rt_boletos
            WHERE rifa_id = %s
              AND estado IN (
                  'reservado',
                  'acreditado',
                  'asignado'
              )
            ORDER BY numero ASC
        """, (
            rifa_id,
        ))

        participantes = cursor.fetchall()

        return render_template(
            "admin_participantes.html",
            rifa=rifa,
            participantes=participantes,
            stats=stats
        )

    finally:

        db.close()


# ============================================================
# LOGOUT DE ADMINISTRACIÓN
# ============================================================

@app.route("/rifas/admin/logout")
def admin_logout():

    session.pop("admin_logged_in", None)

    flash(
        "Has cerrado sesión.",
        "success"
    )

    return redirect(
        url_for("inicio")
    )


# ============================================================
# PANEL ADMINISTRATIVO
# ============================================================

@app.route("/rifas/admin")
@admin_required
def admin_rifas():

    db = get_db()

    try:

        cursor = db.cursor()

        # ----------------------------------------------------
        # Estadísticas globales por estado de rifa
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                estado,
                COUNT(*) AS total
            FROM rt_rifas
            GROUP BY estado
        """)

        stats_rifas = {
            fila["estado"]: fila["total"]
            for fila in cursor.fetchall()
        }

        # ----------------------------------------------------
        # Estadísticas globales por estado de boleto
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                estado,
                COUNT(*) AS total
            FROM rt_boletos
            GROUP BY estado
        """)

        stats_boletos = {
            fila["estado"]: fila["total"]
            for fila in cursor.fetchall()
        }

        # ----------------------------------------------------
        # Estadísticas por rifa activa
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                r.id,
                COUNT(
                    CASE WHEN b.estado = 'disponible'
                    THEN 1 END
                ) AS disponibles,
                COUNT(
                    CASE WHEN b.estado = 'reservado'
                    THEN 1 END
                ) AS reservados,
                COUNT(
                    CASE WHEN b.estado = 'acreditado'
                    THEN 1 END
                ) AS acreditados,
                COUNT(
                    CASE WHEN b.estado = 'asignado'
                    THEN 1 END
                ) AS asignados
            FROM rt_rifas r
            LEFT JOIN rt_boletos b
                ON b.rifa_id = r.id
            GROUP BY r.id
        """)

        filas_stats = cursor.fetchall()

        stats_por_rifa = {}

        for fila in filas_stats:

            stats_por_rifa[fila["id"]] = {
                "disponibles": fila["disponibles"],
                "reservados": fila["reservados"],
                "acreditados": fila["acreditados"],
                "asignados": fila["asignados"]
            }

        # ----------------------------------------------------
        # Listado completo de rifas
        # ----------------------------------------------------

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
            rifas=rifas,
            stats_rifas=stats_rifas,
            stats_boletos=stats_boletos,
            stats_por_rifa=stats_por_rifa
        )

    finally:

        db.close()


# ============================================================
# NUEVA RIFA
# ============================================================

@app.route("/rifas/admin/nueva")
@admin_required
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
@admin_required
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

        cantidad_boletos = int(cantidad_boletos)

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

        precio_boleto = float(precio_boleto)

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

        for numero in range(1, cantidad_boletos + 1):

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
@admin_required
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
@admin_required
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
            "El título de la rifa es obligatorio.",
            "error"
        )

        return redirect(
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
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
            url_for(
                "editar_rifa",
                rifa_id=rifa_id
            )
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
@admin_required
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
# PAUSAR RIFA
# ============================================================

@app.route(
    "/rifas/admin/pausar/<int:rifa_id>",
    methods=["POST"]
)
@admin_required
def pausar_rifa(rifa_id):

    db = get_db()

    try:

        cursor = db.cursor()

        cursor.execute("""
            UPDATE rt_rifas
            SET
                estado = 'pausada',
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
                "Rifa pausada correctamente.",
                "success"
            )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL PAUSAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al pausar la rifa.",
            "error"
        )

    finally:

        db.close()

    return redirect(
        url_for("admin_rifas")
    )


# ============================================================
# REANUDAR RIFA
# ============================================================

@app.route(
    "/rifas/admin/reanudar/<int:rifa_id>",
    methods=["POST"]
)
@admin_required
def reanudar_rifa(rifa_id):

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
                AND estado = 'pausada'
        """, (
            rifa_id,
        ))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe o no está pausada.",
                "error"
            )

        else:

            db.commit()

            flash(
                "Rifa reanudada correctamente.",
                "success"
            )

    except Exception as error:

        db.rollback()

        print(
            "ERROR AL REANUDAR RIFA:",
            error
        )

        flash(
            "Ocurrió un error al reanudar la rifa.",
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
@admin_required
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
                AND estado IN ('activa', 'pausada')
        """, (
            rifa_id,
        ))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "La rifa no existe o no puede finalizarse.",
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
@admin_required
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
                AND estado IN (
                    'borrador',
                    'activa',
                    'pausada'
                )
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