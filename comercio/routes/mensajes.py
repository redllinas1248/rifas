from flask import Blueprint, request, jsonify
from db import get_db
import html
from security import get_current_user, valid_phone

msg_bp = Blueprint('mensajes', __name__, url_prefix='/api/mensajes')


@msg_bp.route('/conversaciones', methods=['GET'])
def conversaciones():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    telefono = user['telefono']
    db = get_db()
    cur = db.cursor()

    # Obtener todos los mensajes donde el usuario esté involucrado, ordenados por fecha descendente
    cur.execute("""
        SELECT emisor, receptor, mensaje, fecha
        FROM mensajes
        WHERE emisor = %s OR receptor = %s
        ORDER BY fecha DESC
    """, (telefono, telefono))

    rows = cur.fetchall()
    cur.close()

    # Diccionario para almacenar el último mensaje de cada contacto
    contacts = {}
    for emisor, receptor, mensaje, fecha in rows:
        # Determinar quién es el otro usuario (el contacto)
        contacto = receptor if emisor == telefono else emisor
        # Si aún no hemos guardado este contacto, guardar el primer mensaje (que es el más reciente)
        if contacto not in contacts:
            contacts[contacto] = {
                'contacto': contacto,
                'ultimo_mensaje': mensaje,
                'fecha': str(fecha)
            }

    # Convertir a lista y ordenar por fecha descendente (más reciente primero)
    result = list(contacts.values())
    result.sort(key=lambda x: x['fecha'], reverse=True)

    return jsonify(result)


@msg_bp.route('/<receptor>', methods=['GET'])
def hilo(receptor):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401
    if not valid_phone(receptor):
        return jsonify({'error': 'Contacto inválido'}), 400

    emisor = user['telefono']
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT id, emisor, receptor, mensaje, fecha
        FROM mensajes
        WHERE (emisor = %s AND receptor = %s)
           OR (emisor = %s AND receptor = %s)
        ORDER BY fecha ASC
    """, (emisor, receptor, receptor, emisor))

    rows = cur.fetchall()
    cur.close()

    keys = ['id', 'emisor', 'receptor', 'mensaje', 'fecha']
    result = [dict(zip(keys, r)) for r in rows]
    for r in result:
        r['fecha'] = str(r['fecha'])
    return jsonify(result)


@msg_bp.route('', methods=['POST'])
def enviar():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    data = request.get_json(silent=True) or {}
    receptor = str(data.get('receptor') or '').strip()
    mensaje = html.escape(str(data.get('mensaje') or '').strip())[:2000]
    emisor = user['telefono']

    if not valid_phone(receptor):
        return jsonify({'error': 'Receptor inválido'}), 400
    if receptor == emisor:
        return jsonify({'error': 'No puedes enviarte mensajes a ti mismo'}), 400
    if not mensaje:
        return jsonify({'error': 'Receptor y mensaje son obligatorios'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO mensajes (emisor, receptor, mensaje) VALUES (%s, %s, %s) RETURNING id",
        (emisor, receptor, mensaje)
    )
    nuevo_id = cur.fetchone()[0]
    db.commit()

    cur.execute("SELECT nombre FROM usuarios WHERE telefono = %s", (emisor,))
    row = cur.fetchone()
    nombre_emisor = row[0] if row and row[0] else emisor

    cur.execute("""
        SELECT id FROM notificaciones
        WHERE telefono_destino = %s AND mensaje LIKE %s
          AND leida = false AND fecha >= NOW() - INTERVAL '5 minutes'
    """, (receptor, f'%{emisor}%'))

    if not cur.fetchone():
        cur.execute(
            "INSERT INTO notificaciones (telefono_destino, mensaje) VALUES (%s, %s)",
            (receptor, f'Nuevo mensaje de {nombre_emisor}')
        )
        db.commit()

    cur.close()
    return jsonify({'mensaje': 'Enviado', 'id': nuevo_id}), 201


@msg_bp.route('/conversacion/<contacto>', methods=['DELETE'])
def eliminar_conversacion(contacto):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401
    if not valid_phone(contacto):
        return jsonify({'error': 'Contacto inválido'}), 400

    telefono = user['telefono']
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        DELETE FROM mensajes
        WHERE (emisor = %s AND receptor = %s)
           OR (emisor = %s AND receptor = %s)
    """, (telefono, contacto, contacto, telefono))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Conversación eliminada'})