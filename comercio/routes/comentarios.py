from flask import Blueprint, request, jsonify
from db import get_db
from security import get_current_user
import html

com_bp = Blueprint('comentarios', __name__, url_prefix='/api/comentarios')


@com_bp.route('/<int:pub_id>', methods=['GET'])
def listar(pub_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT c.id, c.telefono, c.comentario, c.fecha,
               u.nombre AS autor, u.foto AS autor_foto
        FROM comentarios c
        LEFT JOIN usuarios u ON u.telefono = c.telefono
        WHERE c.publicacion_id = %s
        ORDER BY c.fecha ASC
    """, (pub_id,))
    rows = cur.fetchall()
    cur.close()
    keys = ['id', 'telefono', 'comentario', 'fecha', 'autor', 'autor_foto']
    result = [dict(zip(keys, r)) for r in rows]
    for r in result:
        r['fecha'] = str(r['fecha'])
    return jsonify(result)


@com_bp.route('', methods=['POST'])
def crear():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    data = request.get_json(silent=True) or {}
    pub_id = data.get('publicacion_id')
    comentario = html.escape(str(data.get('comentario') or '').strip())[:2000]
    telefono = user['telefono']

    try:
        pub_id = int(pub_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'ID inválido'}), 400

    if not pub_id or not comentario:
        return jsonify({'error': 'Datos incompletos'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM publicaciones WHERE id = %s", (pub_id,))
    if not cur.fetchone():
        cur.close()
        return jsonify({'error': 'Publicación no encontrada'}), 404

    cur.execute(
        "INSERT INTO comentarios (telefono, publicacion_id, comentario) VALUES (%s, %s, %s) RETURNING id",
        (telefono, pub_id, comentario)
    )
    nuevo_id = cur.fetchone()[0]
    db.commit()

    cur.execute("SELECT telefono FROM publicaciones WHERE id = %s", (pub_id,))
    row = cur.fetchone()
    if row and row[0] != telefono:
        cur.execute(
    "INSERT INTO notificaciones (telefono_destino, mensaje) VALUES (%s, %s)",
    (row[0], f'💬 Comentaron en tu publicación #{pub_id}')
)
        db.commit()

    cur.close()
    return jsonify({'mensaje': 'Comentario añadido', 'id': nuevo_id}), 201


@com_bp.route('/<int:com_id>', methods=['DELETE'])
def eliminar(com_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT telefono FROM comentarios WHERE id = %s", (com_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        return jsonify({'error': 'No encontrado'}), 404
    if row[0] != user['telefono'] and user['rol'] != 'admin':
        cur.close()
        return jsonify({'error': 'Sin permiso'}), 403

    cur.execute("DELETE FROM comentarios WHERE id = %s", (com_id,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Comentario eliminado'})