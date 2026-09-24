from flask import Blueprint, request, jsonify
from db import get_db
from security import get_current_user

likes_bp = Blueprint('likes', __name__, url_prefix='/api/likes')

REACCIONES_VALIDAS = {'like', 'love', 'angry', 'wow', 'sad'}


@likes_bp.route('/<int:pub_id>', methods=['GET'])
def listar(pub_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT reaccion, COUNT(*) as total
        FROM likes WHERE publicacion_id = %s
        GROUP BY reaccion
    """, (pub_id,))
    rows = cur.fetchall()
    cur.close()
    return jsonify([{'reaccion': r[0], 'total': r[1]} for r in rows])


@likes_bp.route('', methods=['POST'])
def reaccionar():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    data = request.get_json(silent=True) or {}
    try:
        pub_id = int(data.get('publicacion_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Publicación inválida'}), 400
    reaccion = data.get('reaccion', 'like')
    telefono = user['telefono']

    if reaccion not in REACCIONES_VALIDAS:
        return jsonify({'error': 'Reacción no válida'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT id, reaccion FROM likes WHERE telefono = %s AND publicacion_id = %s",
        (telefono, pub_id)
    )
    existente = cur.fetchone()

    if existente:
        if existente[1] == reaccion:
            cur.execute("DELETE FROM likes WHERE id = %s", (existente[0],))
            db.commit()
            cur.close()
            return jsonify({'accion': 'quitado', 'reaccion': reaccion})
        else:
            cur.execute("UPDATE likes SET reaccion = %s WHERE id = %s", (reaccion, existente[0]))
            db.commit()
            cur.close()
            return jsonify({'accion': 'cambiado', 'reaccion': reaccion})
    else:
        cur.execute(
            "INSERT INTO likes (telefono, publicacion_id, reaccion) VALUES (%s, %s, %s)",
            (telefono, pub_id, reaccion)
        )
        db.commit()

        cur.execute("SELECT telefono FROM publicaciones WHERE id = %s", (pub_id,))
        row = cur.fetchone()
        if row and row[0] != telefono:
            emojis = {'like': '👍', 'love': '❤️', 'angry': '😠', 'wow': '😮', 'sad': '😢'}
            cur.execute(
    "INSERT INTO notificaciones (telefono_destino, mensaje) VALUES (%s, %s)",
    (row[0], f"{emojis.get(reaccion, '👍')} Le dieron {reaccion} a tu publicación #{pub_id}")
)
            db.commit()

        cur.close()
        return jsonify({'accion': 'agregado', 'reaccion': reaccion}), 201