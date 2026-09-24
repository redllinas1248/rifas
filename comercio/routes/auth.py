from flask import Blueprint, request, jsonify, session
from db import get_db
import bcrypt
import re
import time
from threading import Lock
from security import require_api_admin, get_current_user, csrf_token, valid_phone

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

_LOGIN_ATTEMPTS = {}
_LOGIN_LOCK = Lock()
LOGIN_WINDOW = 15 * 60
LOGIN_MAX = 8
_REGISTER_ATTEMPTS = {}
REGISTER_WINDOW = 60 * 60
REGISTER_MAX = 5


def _rate_key():
    return f"{request.remote_addr or 'unknown'}:{request.get_json(silent=True).get('telefono', '').strip() if request.is_json else ''}"


def _login_limited(key):
    now = time.time()
    with _LOGIN_LOCK:
        attempts = [ts for ts in _LOGIN_ATTEMPTS.get(key, []) if now - ts < LOGIN_WINDOW]
        if len(attempts) >= LOGIN_MAX:
            _LOGIN_ATTEMPTS[key] = attempts
            return True
        attempts.append(now)
        _LOGIN_ATTEMPTS[key] = attempts
        return False


def _register_limited():
    now = time.time()
    ip = request.remote_addr or 'unknown'
    with _LOGIN_LOCK:
        attempts = [ts for ts in _REGISTER_ATTEMPTS.get(ip, []) if now - ts < REGISTER_WINDOW]
        if len(attempts) >= REGISTER_MAX:
            _REGISTER_ATTEMPTS[ip] = attempts
            return True
        attempts.append(now)
        _REGISTER_ATTEMPTS[ip] = attempts
        return False


def _clear_login_attempts(key):
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


@auth_bp.route('/csrf', methods=['GET'])
def csrf():
    return jsonify({'token': csrf_token()})


@auth_bp.route('/registro', methods=['POST'])
def registro():
    data = request.get_json(silent=True) or {}
    if _register_limited():
        return jsonify({'error': 'Demasiados registros desde esta conexión. Intenta más tarde.'}), 429
    telefono = str(data.get('telefono') or '').strip()
    pin = data.get('pin', '').strip()
    usuario = data.get('usuario', '').strip() or telefono
    nombre = data.get('nombre', '').strip()

    if not telefono or not pin:
        return jsonify({'error': 'Teléfono y PIN son obligatorios'}), 400
    if not valid_phone(telefono):
        return jsonify({'error': 'El teléfono debe contener exactamente 10 dígitos'}), 400
    if len(pin) != 4 or not pin.isdigit():
        return jsonify({'error': 'El PIN debe ser de 4 dígitos'}), 400
    if len(usuario) > 50 or len(nombre) > 100:
        return jsonify({'error': 'Datos demasiado largos'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
    if cur.fetchone():
        cur.close()
        return jsonify({'error': 'Este teléfono ya está registrado'}), 409

    pin_hash = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
    localidad = data.get('localidad', '').strip() or None

    cur.execute(
        "INSERT INTO usuarios (telefono, usuario, nombre, pin, localidad) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (telefono, usuario, nombre or None, pin_hash, localidad)
    )
    nuevo_id = cur.fetchone()[0]
    db.commit()
    cur.close()

    session.permanent = True
    session['usuario_id'] = nuevo_id
    return jsonify({'mensaje': 'Registro exitoso', 'id': nuevo_id}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    telefono = data.get('telefono', '').strip()
    pin = data.get('pin', '').strip()

    if not telefono or not pin:
        return jsonify({'error': 'Teléfono y PIN son obligatorios'}), 400
    if not valid_phone(telefono) or len(pin) != 4 or not pin.isdigit():
        return jsonify({'error': 'Credenciales inválidas'}), 400

    rate_key = _rate_key()
    if _login_limited(rate_key):
        return jsonify({'error': 'Demasiados intentos. Intenta de nuevo en unos minutos.'}), 429

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, pin, nombre, foto, rol, baneado FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario = cur.fetchone()
    cur.close()

    if not usuario:
        return jsonify({'error': 'Credenciales inválidas'}), 401

    _id, pin_hash, nombre, foto, rol, baneado = usuario

    if baneado:
        return jsonify({'error': 'Cuenta bloqueada'}), 403

    if not bcrypt.checkpw(pin.encode(), pin_hash.encode()):
        return jsonify({'error': 'Credenciales inválidas'}), 401

    _clear_login_attempts(rate_key)

    session.permanent = True
    session['usuario_id'] = _id

    return jsonify({
        'mensaje': 'Login exitoso',
        'usuario': {'id': _id, 'nombre': nombre, 'foto': foto, 'rol': rol}
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'mensaje': 'Sesión cerrada'})


@auth_bp.route('/perfil', methods=['PUT'])
def actualizar_perfil():
    data = request.get_json(silent=True) or {}
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401
    telefono = user['telefono']
    campos = ['nombre', 'apellido', 'localidad', 'correo', 'tipo', 'mostrar_telefono', 'mostrar_correo']
    updates = {k: data[k] for k in campos if k in data}

    if not updates:
        return jsonify({'error': 'Nada que actualizar'}), 400

    set_clause = ', '.join(f"{k} = %s" for k in updates)
    valores = list(updates.values()) + [telefono]

    db = get_db()
    cur = db.cursor()
    cur.execute(f"UPDATE usuarios SET {set_clause} WHERE telefono = %s", valores)
    db.commit()
    cur.close()

    return jsonify({'mensaje': 'Perfil actualizado'})


@auth_bp.route('/yo', methods=['GET'])
def yo():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute(
        """SELECT id, telefono, usuario, nombre, apellido, localidad,
                  foto, rol, correo, tipo, mostrar_telefono, mostrar_correo
           FROM usuarios WHERE id = %s""",
        (user['id'],)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    keys = ['id', 'telefono', 'usuario', 'nombre', 'apellido', 'localidad',
            'foto', 'rol', 'correo', 'tipo', 'mostrar_telefono', 'mostrar_correo']
    data = dict(zip(keys, row))
    return jsonify(data)


@auth_bp.route('/foto', methods=['POST'])
def subir_foto():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    if 'foto' not in request.files:
        return jsonify({'error': 'No se envió ninguna imagen'}), 400

    foto = request.files['foto']
    ext = foto.filename.rsplit('.', 1)[-1].lower()
    if ext not in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        return jsonify({'error': 'Formato no permitido'}), 400

    try:
        import cloudinary.uploader
        resultado = cloudinary.uploader.upload(
            foto,
            folder='comercio/perfiles',
            resource_type='image'
        )
        ruta = resultado['secure_url']
    except Exception as e:
        return jsonify({'error': 'No se pudo subir la imagen'}), 500

    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE usuarios SET foto = %s WHERE telefono = %s", (ruta, user['telefono']))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Foto actualizada', 'ruta': ruta})


@auth_bp.route('/usuario/<telefono>', methods=['GET'])
def perfil_publico(telefono):
    if not valid_phone(telefono):
        return jsonify({'error': 'Teléfono inválido'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT id, telefono, nombre, apellido, localidad, foto, tipo
        FROM usuarios WHERE telefono = %s
    """, (telefono,))
    row = cur.fetchone()
    if not row:
        cur.close()
        return jsonify({'error': 'Usuario no encontrado'}), 404
    keys = ['id', 'telefono', 'nombre', 'apellido', 'localidad', 'foto', 'tipo']
    u = dict(zip(keys, row))
    cur.execute("SELECT COUNT(*) FROM publicaciones WHERE telefono = %s", (telefono,))
    u['total_pubs'] = cur.fetchone()[0]
    cur.close()
    return jsonify(u)


@auth_bp.route('/admin/usuarios', methods=['GET'])
def admin_usuarios():
    _, error = require_api_admin()
    if error:
        return error
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT id, telefono, nombre, localidad, rol, foto,
               (SELECT COUNT(*) FROM publicaciones p WHERE p.telefono = u.telefono) AS total_pubs
        FROM usuarios u ORDER BY id DESC
    """)
    rows = cur.fetchall()
    keys = ['id', 'telefono', 'nombre', 'localidad', 'rol', 'foto', 'total_pubs']
    cur.close()
    return jsonify([dict(zip(keys, r)) for r in rows])


@auth_bp.route('/admin/rol', methods=['POST'])
def admin_cambiar_rol():
    _, error = require_api_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    telefono = str(data.get('telefono') or '').strip()
    nuevo_rol = data.get('rol')
    if not valid_phone(telefono):
        return jsonify({'error': 'Teléfono inválido'}), 400
    if nuevo_rol not in ('admin', 'usuario'):
        return jsonify({'error': 'Rol inválido'}), 400
    actor = get_current_user()
    if actor and actor['telefono'] == telefono and nuevo_rol != 'admin':
        return jsonify({'error': 'No puedes quitarte tus propios permisos de administrador'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE usuarios SET rol = %s WHERE telefono = %s", (nuevo_rol, telefono))
    db.commit()
    cur.close()
    return jsonify({'mensaje': f'Rol actualizado a {nuevo_rol}'})


@auth_bp.route('/admin/banear', methods=['POST'])
def admin_banear():
    _, error = require_api_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    telefono = str(data.get('telefono') or '').strip()
    baneado = bool(data.get('baneado', True))
    if not valid_phone(telefono):
        return jsonify({'error': 'Teléfono inválido'}), 400
    actor = get_current_user()
    if actor and actor['telefono'] == telefono and baneado:
        return jsonify({'error': 'No puedes banear tu propia cuenta'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE usuarios SET baneado = %s WHERE telefono = %s", (baneado, telefono))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Usuario ' + ('baneado' if baneado else 'desbaneado')})


@auth_bp.route('/puntos', methods=['GET'])
def mis_puntos():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    telefono = user['telefono']
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT puntos FROM usuarios WHERE telefono = %s", (telefono,))
    row = cur.fetchone()
    puntos = row[0] if row else 0

    cur.execute("""
        SELECT motivo, cantidad, fecha
        FROM puntos_historial
        WHERE telefono = %s
        ORDER BY fecha DESC
        LIMIT 20
    """, (telefono,))
    historial = [{'motivo': r[0], 'cantidad': r[1], 'fecha': str(r[2])}
                 for r in cur.fetchall()]

    cur.execute(
        "SELECT COUNT(*) FROM publicaciones WHERE telefono = %s AND fecha >= NOW() - INTERVAL '24 hours'",
        (telefono,)
    )
    pubs_hoy = cur.fetchone()[0]

    cur.close()
    return jsonify({'puntos': puntos, 'pubs_hoy': pubs_hoy, 'historial': historial})