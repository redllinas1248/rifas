import os
import logging
from flask import Flask, request, jsonify, g
from apscheduler.schedulers.background import BackgroundScheduler
from security import validate_csrf
from config import Config, init_cloudinary
from db import init_db, get_db

app = Flask(__name__)
app.config.from_object(Config)

# Configurar logging
if not app.debug:
    app.logger.setLevel(logging.ERROR)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
    app.logger.addHandler(handler)

# Manejador de errores global
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Error no controlado: {e}", exc_info=True)
    return jsonify({'error': 'Error interno del servidor'}), 500

# Manejador para favicon
@app.errorhandler(404)
def not_found(e):
    if request.path == '/favicon.ico':
        return '', 204
    return jsonify({'error': 'No encontrado'}), 404

# Cerrar conexión a la base de datos
@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Verificar variables de entorno
_REQUIRED_SECRETS = (
    'SECRET_KEY',
    'DATABASE_URL',
    'CLOUDINARY_CLOUD_NAME',
    'CLOUDINARY_API_KEY',
    'CLOUDINARY_API_SECRET',
)
_missing = [name for name in _REQUIRED_SECRETS if not app.config.get(name)]
if _missing:
    raise RuntimeError('Faltan variables de entorno obligatorias: ' + ', '.join(_missing))


@app.before_request
def protect_api_with_csrf():
    if not request.path.startswith('/api/'):
        return None
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if not validate_csrf():
        return jsonify({'error': 'Token CSRF inválido o ausente'}), 403
    return None


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    
    # CSP muy permisiva para permitir cualquier recurso de Adsterra
    # Permitimos cualquier origen para scripts, frames, imágenes, etc.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
        "frame-src *; "
        "img-src * data: blob:; "
        "style-src * 'unsafe-inline'; "
        "font-src * data:; "
        "connect-src *; "
        "media-src *; "
        "frame-ancestors 'self';"
    )
    
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response

init_db(app)
init_cloudinary(app)

# Registrar Blueprints
from routes.auth import auth_bp
from routes.publicaciones import pub_bp
from routes.comentarios import com_bp
from routes.likes import likes_bp
from routes.mensajes import msg_bp
from routes.notificaciones import notif_bp
from routes.directorio import dir_bp
from routes.views import views_bp
from routes.transmisiones import transmisiones_bp

app.register_blueprint(auth_bp)
app.register_blueprint(pub_bp)
app.register_blueprint(com_bp)
app.register_blueprint(likes_bp)
app.register_blueprint(msg_bp)
app.register_blueprint(notif_bp)
app.register_blueprint(dir_bp)
app.register_blueprint(views_bp)
app.register_blueprint(transmisiones_bp)

# Scheduler limpieza automática
def limpieza_programada():
    with app.app_context():
        try:
            from routes.publicaciones import limpiar_publicaciones_antiguas
            eliminadas = limpiar_publicaciones_antiguas()
            app.logger.info(f"Limpieza programada: {eliminadas} publicaciones eliminadas")
        except Exception as e:
            app.logger.error(f"Error en limpieza programada: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(
    limpieza_programada,
    'cron',
    hour=3,
    minute=0,
    id='limpieza_publicaciones',
    replace_existing=True
)
scheduler.start()

import atexit
atexit.register(lambda: scheduler.shutdown())
# ============================================================
# EXPONER LA APP COMO SUB-APLICACIÓN (para DispatcherMiddleware)
#
# Desactivamos el scheduler si estamos dentro del dispatcher
# (rifas se encarga de correrlo o no, para evitar duplicación).
# ============================================================

# No es necesario hacer nada más: la app ya está lista para ser importada.
# El dispatcher se encargará de servirla bajo /comercio.
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)