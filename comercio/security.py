import secrets
import re
from functools import wraps
from flask import session, jsonify, request
from db import get_db

def get_current_user():
    user_id = session.get('usuario_id')
    if not user_id:
        return None

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """SELECT id, telefono, rol, baneado
               FROM usuarios WHERE id = %s""",
            (user_id,)
        )
        row = cur.fetchone()
    finally:
        cur.close()

    if not row:
        session.clear()
        return None

    user = {
        'id': row[0],
        'telefono': row[1],
        'rol': row[2] or 'usuario',
        'baneado': bool(row[3])
    }

    if user['baneado']:
        session.clear()
        return None

    return user


def is_admin():
    user = get_current_user()
    return bool(user and user['rol'] == 'admin')


def require_api_login():
    user = get_current_user()
    if not user:
        return None, (jsonify({'error': 'No autenticado'}), 401)
    return user, None


def require_api_admin():
    user = get_current_user()
    if not user:
        return None, (jsonify({'error': 'No autenticado'}), 401)
    if user['rol'] != 'admin':
        return None, (jsonify({'error': 'Sin permiso'}), 403)
    return user, None


def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def validate_csrf():
    expected = session.get('_csrf_token')
    supplied = request.headers.get('X-CSRF-Token')
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def valid_phone(value):
    return bool(re.fullmatch(r'\d{10}', str(value or '')))