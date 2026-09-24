from flask import Blueprint, render_template, redirect, url_for, request, jsonify, current_app
from db import get_db
from security import get_current_user, require_api_admin
from werkzeug.utils import secure_filename
import cloudinary.uploader
import os
from PIL import Image
import io
import json
from pywebpush import webpush, WebPushException
from datetime import datetime

views_bp = Blueprint('views', __name__)

DEFAULT_LOGO = '/static/img/banner.svg'

# Claves VAPID (deben estar en variables de entorno)
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_CLAIMS = {
    'sub': 'mailto:tu-email@example.com'  # CAMBIA ESTO POR TU EMAIL
}


def _config_value(clave, default=None):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "SELECT valor FROM configuracion WHERE clave = %s LIMIT 1",
            (clave,)
        )
        row = cur.fetchone()
        return row[0] if row else default
    except Exception:
        return default
    finally:
        cur.close()


@views_bp.app_context_processor
def inject_site_config():
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM visitas")
        row = cur.fetchone()
        visitas_totales = int(row[0] or 0)
    except Exception:
        visitas_totales = 0
    finally:
        cur.close()

    return {
        'visitas_totales': visitas_totales,
        'logo_url': _config_value('logo_url', DEFAULT_LOGO),
        'default_og_image': '/static/img/og-image.jpg'
    }


def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for('views.login'))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for('views.login'))
        if user['rol'] != 'admin':
            return redirect(url_for('views.index'))
        return f(*args, **kwargs)

    return decorated


# ============================================================
# RUTAS PÚBLICAS CON META TAGS PARA SEO
# ============================================================

@views_bp.route('/')
def index():
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO visitas (fecha, total)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (fecha) DO UPDATE SET total = visitas.total + 1
        """)
        db.commit()
    finally:
        cur.close()

    # ===== OBTENER CONFIGURACIÓN DE BOTONES PERSONALIZADOS =====
    btn_entretenimiento = get_boton_config('entretenimiento')
    btn_educacion = get_boton_config('educacion')

    return render_template('index.html',
        meta_title='Ventas Locales José Azueta - Compra, vende y conecta',
        meta_description='Plataforma de compra, venta y servicios locales en José Azueta. Publica tus productos, encuentra servicios y conecta con tu comunidad.',
        btn_entretenimiento=btn_entretenimiento,
        btn_educacion=btn_educacion
    )


@views_bp.route('/login')
def login():
    if get_current_user():
        return redirect(url_for('views.index'))
    return render_template('auth.html',
        meta_title='Iniciar sesión - Ventas Locales José Azueta',
        meta_description='Accede a tu cuenta de Ventas Locales José Azueta para publicar, comentar y vender.'
    )


@views_bp.route('/perfil')
@login_required
def perfil():
    return render_template('perfil.html',
        meta_title='Mi perfil - Ventas Locales José Azueta',
        meta_description='Gestiona tu perfil, publicaciones y puntos en Ventas Locales José Azueta.'
    )


@views_bp.route('/mensajes')
@login_required
def mensajes():
    return render_template('mensajes.html',
        meta_title='Mensajes - Ventas Locales José Azueta',
        meta_description='Tus conversaciones con otros usuarios de Ventas Locales José Azueta.'
    )


@views_bp.route('/notificaciones')
@login_required
def notificaciones():
    return render_template('notificaciones.html',
        meta_title='Notificaciones - Ventas Locales José Azueta',
        meta_description='Todas tus notificaciones de Ventas Locales José Azueta.'
    )


@views_bp.route('/buscar')
def buscar():
    return render_template('buscar.html',
        meta_title='Buscar - Ventas Locales José Azueta',
        meta_description='Encuentra publicaciones, usuarios y servicios en José Azueta.'
    )


@views_bp.route('/publicacion/<int:pub_id>')
def detalle_pub(pub_id):
    # Obtener datos de la publicación para meta tags
    meta_title = 'Publicación - Ventas Locales José Azueta'
    meta_description = 'Detalle de publicación en Ventas Locales José Azueta.'
    meta_image = None
    
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT p.contenido, u.nombre as autor, 
                   (SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = p.id LIMIT 1) as imagen
            FROM publicaciones p
            LEFT JOIN usuarios u ON u.telefono = p.telefono
            WHERE p.id = %s
        """, (pub_id,))
        row = cur.fetchone()
        cur.close()
        if row:
            contenido = row[0] or ''
            autor = row[1] or 'Usuario'
            meta_title = f"{autor} - {contenido[:60]}" if contenido else f"Publicación de {autor}"
            meta_description = contenido[:160] if contenido else f"Publicación de {autor} en Ventas Locales José Azueta."
            if row[2]:
                meta_image = row[2]
    except Exception as e:
        current_app.logger.error(f"Error obteniendo detalles de publicación para meta: {e}")
    
    return render_template('detalle_pub.html', pub_id=pub_id,
        meta_title=meta_title,
        meta_description=meta_description,
        meta_image=meta_image
    )


@views_bp.route('/usuario/<telefono>')
def perfil_usuario(telefono):
    # Obtener nombre del usuario para meta
    meta_title = f"Perfil de usuario - Ventas Locales José Azueta"
    meta_description = f"Perfil de {telefono} en Ventas Locales José Azueta."
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT nombre FROM usuarios WHERE telefono = %s", (telefono,))
        row = cur.fetchone()
        cur.close()
        if row and row[0]:
            meta_title = f"{row[0]} - Perfil en Ventas Locales José Azueta"
            meta_description = f"Perfil de {row[0]} en Ventas Locales José Azueta."
    except Exception:
        pass
    
    return render_template('perfil_usuario.html', telefono=telefono,
        meta_title=meta_title,
        meta_description=meta_description
    )


@views_bp.route('/admin')
@admin_required
def admin():
    return render_template('admin.html',
        meta_title='Panel de Administración - Ventas Locales José Azueta',
        meta_description='Administra usuarios, publicaciones y contenido de Ventas Locales José Azueta.'
    )


@views_bp.route('/admin/logo', methods=['POST'])
@admin_required
def subir_logo():
    archivo = request.files.get('logo')

    if not archivo or not archivo.filename:
        return jsonify({'error': 'Selecciona una imagen.'}), 400

    extension = (
        secure_filename(archivo.filename).rsplit('.', 1)[-1].lower()
        if '.' in archivo.filename else ''
    )
    extensiones_permitidas = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

    if extension not in extensiones_permitidas:
        return jsonify({
            'error': 'Formato no permitido. Usa PNG, JPG, JPEG, GIF, WEBP o SVG.'
        }), 400

    MAX_SIZE = 2 * 1024 * 1024
    archivo.seek(0, os.SEEK_END)
    size = archivo.tell()
    archivo.seek(0)
    if size > MAX_SIZE:
        return jsonify({'error': 'La imagen excede el tamaño máximo de 2 MB.'}), 400

    if extension != 'svg':
        try:
            img_bytes = archivo.read()
            Image.open(io.BytesIO(img_bytes)).verify()
            archivo.seek(0)
        except Exception:
            return jsonify({'error': 'El archivo no es una imagen válida.'}), 400
    else:
        archivo.seek(0)
        contenido = archivo.read(1024).decode('utf-8', errors='ignore')
        archivo.seek(0)
        if not contenido.lstrip().startswith('<svg'):
            return jsonify({'error': 'El archivo SVG no parece válido.'}), 400

    try:
        resultado = cloudinary.uploader.upload(
            archivo,
            folder='comercio/configuracion',
            public_id='logo',
            overwrite=True,
            invalidate=True,
            resource_type='image'
        )
        logo_url = resultado['secure_url']

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO configuracion (clave, valor)
            VALUES ('logo_url', %s)
            ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
        """, (logo_url,))
        db.commit()
        cur.close()

        return jsonify({'ok': True, 'logo_url': logo_url})
    except Exception as e:
        current_app.logger.error(f"Error subiendo logo: {e}")
        return jsonify({'error': 'No se pudo subir el logo. Intenta nuevamente.'}), 500


@views_bp.route('/servicios')
def servicios():
    return render_template('servicios.html',
        meta_title='Servicios en José Azueta - Plomeros, electricistas y más',
        meta_description='Encuentra los mejores servicios profesionales en José Azueta. Plomeros, electricistas, carpinteros, mecánicos y más.'
    )


@views_bp.route('/emergencias')
def emergencias():
    return render_template('emergencias.html',
        meta_title='Emergencias en José Azueta - Hospitales, farmacias y números de contacto',
        meta_description='Información esencial de emergencias en José Azueta: hospitales, farmacias, bomberos, policía y números de contacto.'
    )


@views_bp.route('/transmisiones')
def transmisiones():
    return render_template('transmisiones.html',
        meta_title='Transmisiones en vivo - José Azueta',
        meta_description='Mira transmisiones en vivo de eventos, noticias y actividades en José Azueta.'
    )


@views_bp.route('/api/estadisticas', methods=['GET'])
def estadisticas():
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM usuarios")
        total_usuarios = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM publicaciones WHERE fecha >= NOW() - INTERVAL '24 hours'")
        pubs_hoy = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(total), 0) FROM visitas")
        visitas = int(cur.fetchone()[0] or 0)

    except Exception as e:
        current_app.logger.error(f"Error en estadísticas: {e}")
        return jsonify({'error': 'Error interno'}), 500
    finally:
        cur.close()

    return jsonify({
        'total_usuarios': total_usuarios,
        'pubs_hoy': pubs_hoy,
        'visitas_totales': visitas
    })


@views_bp.route('/offline')
def offline():
    return render_template('offline.html')


# ============================================================
# SITEMAP Y ROBOTS.TXT (SEO)
# ============================================================

@views_bp.route('/sitemap.xml')
def sitemap():
    db = get_db()
    cur = db.cursor()
    
    # URLs estáticas
    urls = [
        {'loc': '/', 'priority': '1.0'},
        {'loc': '/servicios', 'priority': '0.9'},
        {'loc': '/emergencias', 'priority': '0.9'},
        {'loc': '/transmisiones', 'priority': '0.8'},
        {'loc': '/buscar', 'priority': '0.6'},
        {'loc': '/login', 'priority': '0.5'},
    ]
    
    # Publicaciones (más recientes)
    cur.execute("SELECT id, fecha FROM publicaciones ORDER BY fecha DESC LIMIT 1000")
    for row in cur.fetchall():
        urls.append({'loc': f'/publicacion/{row[0]}', 'priority': '0.7'})
    
    # Servicios / Directorio (activos)
    cur.execute("SELECT id FROM directorio WHERE activo = true")
    for row in cur.fetchall():
        urls.append({'loc': f'/servicio/{row[0]}', 'priority': '0.6'})
    
    cur.close()
    
    now = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('sitemap.xml', urls=urls, now=now), 200, {'Content-Type': 'application/xml'}


@views_bp.route('/robots.txt')
def robots():
    domain = request.host_url.rstrip('/')
    return f"""User-agent: *
Allow: /
Disallow: /admin
Disallow: /perfil
Disallow: /mensajes
Disallow: /notificaciones
Sitemap: {domain}/sitemap.xml
""", 200, {'Content-Type': 'text/plain'}


# ============================================================
# NOTIFICACIONES PUSH (WEB PUSH API)
# ============================================================

@views_bp.route('/api/push/vapid_public_key', methods=['GET'])
def vapid_public_key():
    return jsonify({'public_key': VAPID_PUBLIC_KEY})


@views_bp.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    auth_key = data.get('keys', {}).get('auth')
    p256dh_key = data.get('keys', {}).get('p256dh')
    user_agent = request.headers.get('User-Agent', '')

    if not endpoint or not auth_key or not p256dh_key:
        return jsonify({'error': 'Datos incompletos'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO push_subscriptions (endpoint, auth_key, p256dh_key, user_agent)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (endpoint) DO UPDATE SET
            auth_key = EXCLUDED.auth_key,
            p256dh_key = EXCLUDED.p256dh_key,
            user_agent = EXCLUDED.user_agent
    """, (endpoint, auth_key, p256dh_key, user_agent))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Suscripción guardada'})


@views_bp.route('/api/push/unsubscribe', methods=['POST'])
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({'error': 'Endpoint requerido'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Suscripción eliminada'})


@views_bp.route('/api/push/send', methods=['POST'])
@admin_required
def push_send():
    data = request.get_json(silent=True) or {}
    title = data.get('title', 'Nueva transmisión en vivo')
    body = data.get('body', '¡Estamos en vivo!')
    url = data.get('url', '/transmisiones')
    icon = data.get('icon', '/static/img/icon-192.png')

    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return jsonify({'error': 'Claves VAPID no configuradas'}), 500

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT endpoint, auth_key, p256dh_key FROM push_subscriptions")
    subscriptions = cur.fetchall()
    cur.close()

    if not subscriptions:
        return jsonify({'mensaje': 'No hay suscriptores'}), 200

    payload = json.dumps({
        'title': title,
        'body': body,
        'icon': icon,
        'url': url
    })

    success_count = 0
    for endpoint, auth, p256dh in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': endpoint,
                    'keys': {'auth': auth, 'p256dh': p256dh}
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            success_count += 1
        except WebPushException as e:
            if e.response and e.response.status_code in [410, 404]:
                cur = db.cursor()
                cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
                db.commit()
                cur.close()
            else:
                current_app.logger.error(f"Error enviando notificación: {e}")

    return jsonify({'mensaje': f'Notificaciones enviadas a {success_count} suscriptores'})


# ============================================================
# ADMIN: ESTADÍSTICAS (gráficas)
# ============================================================

@views_bp.route('/api/admin/estadisticas')
@admin_required
def admin_estadisticas():
    """Devuelve datos estadísticos para el panel de admin (totales y series diarias)."""
    db = get_db()
    cur = db.cursor()
    
    # Totales
    cur.execute("SELECT COUNT(*) FROM usuarios")
    total_usuarios = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM publicaciones")
    total_publicaciones = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(total), 0) FROM visitas")
    total_visitas = int(cur.fetchone()[0] or 0)
    
    # Últimos 30 días: visitas diarias
    cur.execute("""
        SELECT fecha, total FROM visitas 
        WHERE fecha >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY fecha
    """)
    visitas_diarias = [{'fecha': str(row[0]), 'total': row[1]} for row in cur.fetchall()]
    
    # Publicaciones por día (últimos 30 días)
    cur.execute("""
        SELECT DATE(fecha) as dia, COUNT(*) as total
        FROM publicaciones
        WHERE fecha >= NOW() - INTERVAL '30 days'
        GROUP BY dia
        ORDER BY dia
    """)
    pubs_diarias = [{'fecha': str(row[0]), 'total': row[1]} for row in cur.fetchall()]
    
    # Nuevos usuarios por día (últimos 30 días)
    cur.execute("""
        SELECT DATE(fecha_creacion) as dia, COUNT(*) as total
        FROM usuarios
        WHERE fecha_creacion >= NOW() - INTERVAL '30 days'
        GROUP BY dia
        ORDER BY dia
    """)
    usuarios_diarios = [{'fecha': str(row[0]), 'total': row[1]} for row in cur.fetchall()]
    
    cur.close()
    
    return jsonify({
        'totales': {
            'usuarios': total_usuarios,
            'publicaciones': total_publicaciones,
            'visitas': total_visitas
        },
        'visitas_diarias': visitas_diarias,
        'pubs_diarias': pubs_diarias,
        'usuarios_diarios': usuarios_diarios
    })


# ============================================================
# CONFIGURACIÓN DE BOTONES PERSONALIZADOS
# ============================================================

def get_config_value(clave, default=None):
    """Obtiene un valor de configuración de la base de datos."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (clave,))
        row = cur.fetchone()
        return row[0] if row else default
    except Exception:
        return default
    finally:
        cur.close()

def get_boton_config(prefix):
    """Obtiene la configuración completa de un botón."""
    return {
        'titulo': get_config_value(f'btn_{prefix}_titulo', ''),
        'sub': get_config_value(f'btn_{prefix}_sub', ''),
        'icono': get_config_value(f'btn_{prefix}_icono', '📍'),
        'enlace': get_config_value(f'btn_{prefix}_enlace', '#'),
        'activo': get_config_value(f'btn_{prefix}_activo', '1') == '1'
    }

@views_bp.route('/api/admin/botones', methods=['GET'])
@admin_required
def admin_botones():
    """Devuelve la configuración de los botones personalizados."""
    return jsonify({
        'entretenimiento': get_boton_config('entretenimiento'),
        'educacion': get_boton_config('educacion')
    })

@views_bp.route('/api/admin/botones', methods=['POST'])
@admin_required
def admin_guardar_botones():
    """Guarda la configuración de los botones personalizados."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor()
    
    for key, value in data.items():
        # Solo guardar claves que empiecen con btn_
        if key.startswith('btn_'):
            cur.execute("""
                INSERT INTO configuracion (clave, valor)
                VALUES (%s, %s)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
            """, (key, value))
    
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Configuración guardada'})