from flask import Blueprint, request, jsonify, current_app
from db import get_db
from security import require_api_admin, get_current_user
import html
import cloudinary.uploader
import os

dir_bp = Blueprint('directorio', __name__, url_prefix='/api/directorio')


def subir_imagen(archivo):
    """Sube una imagen a Cloudinary y devuelve la URL."""
    if not archivo:
        return None
    try:
        resultado = cloudinary.uploader.upload(
            archivo,
            folder='comercio/directorio',
            resource_type='image'
        )
        return resultado['secure_url']
    except Exception as e:
        current_app.logger.error(f"Error subiendo imagen directorio: {e}")
        return None


def obtener_categoria_segun_tipo(tipo, categoria_manual=None):
    """
    Asigna categoría automáticamente según el tipo.
    Si se proporciona una categoría manual y no está vacía, la usa.
    """
    if categoria_manual and categoria_manual.strip():
        return categoria_manual.strip()
    
    if tipo == 'servicios':
        return 'Servicios'
    elif tipo == 'emergencias':
        return 'Emergencias'
    else:
        return 'General'


@dir_bp.route('', methods=['GET'])
def listar():
    """Lista todos los registros activos agrupados por categoría, con calificaciones."""
    db = get_db()
    cur = db.cursor()

    tipo = request.args.get('tipo')

    if tipo:
        cur.execute("""
            SELECT d.id, d.categoria, d.nombre, d.telefono, d.horario, d.direccion, 
                   d.icono, d.tipo, d.foto, d.descripcion_corta,
                   COALESCE(AVG(c.calificacion), 0) AS promedio,
                   COUNT(c.id) AS total_calificaciones
            FROM directorio d
            LEFT JOIN calificaciones_directorio c ON c.directorio_id = d.id
            WHERE d.activo = true AND d.tipo = %s
            GROUP BY d.id
            ORDER BY d.categoria, d.orden, d.nombre
        """, (tipo,))
    else:
        cur.execute("""
            SELECT d.id, d.categoria, d.nombre, d.telefono, d.horario, d.direccion, 
                   d.icono, d.tipo, d.foto, d.descripcion_corta,
                   COALESCE(AVG(c.calificacion), 0) AS promedio,
                   COUNT(c.id) AS total_calificaciones
            FROM directorio d
            LEFT JOIN calificaciones_directorio c ON c.directorio_id = d.id
            WHERE d.activo = true
            GROUP BY d.id
            ORDER BY d.categoria, d.orden, d.nombre
        """)

    rows = cur.fetchall()
    cur.close()

    keys = ['id', 'categoria', 'nombre', 'telefono', 'horario', 'direccion', 
            'icono', 'tipo', 'foto', 'descripcion_corta', 'promedio', 'total_calificaciones']
    grupos = {}
    for row in rows:
        item = dict(zip(keys, row))
        item['promedio'] = float(item['promedio'])
        item['total_calificaciones'] = int(item['total_calificaciones'])
        cat = item['categoria']
        if cat not in grupos:
            grupos[cat] = []
        grupos[cat].append(item)

    return jsonify(grupos)


@dir_bp.route('/<int:item_id>/calificar', methods=['POST'])
def calificar(item_id):
    """Califica un servicio con 1-5 estrellas."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Debes iniciar sesión para calificar'}), 401

    data = request.get_json(silent=True) or {}
    calificacion = data.get('calificacion')
    if not calificacion or not isinstance(calificacion, int) or calificacion < 1 or calificacion > 5:
        return jsonify({'error': 'Calificación inválida (1-5)'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id FROM directorio WHERE id = %s AND activo = true", (item_id,))
    if not cur.fetchone():
        cur.close()
        return jsonify({'error': 'Servicio no encontrado'}), 404

    telefono = user['telefono']

    cur.execute("""
        INSERT INTO calificaciones_directorio (directorio_id, usuario_telefono, calificacion)
        VALUES (%s, %s, %s)
        ON CONFLICT (directorio_id, usuario_telefono) 
        DO UPDATE SET calificacion = EXCLUDED.calificacion, fecha = CURRENT_TIMESTAMP
        RETURNING calificacion
    """, (item_id, telefono, calificacion))
    nueva_calif = cur.fetchone()[0]
    db.commit()
    cur.close()

    # Calcular nuevo promedio
    db2 = get_db()
    cur2 = db2.cursor()
    cur2.execute("""
        SELECT COALESCE(AVG(calificacion), 0), COUNT(*)
        FROM calificaciones_directorio
        WHERE directorio_id = %s
    """, (item_id,))
    promedio, total = cur2.fetchone()
    cur2.close()

    return jsonify({
        'mensaje': 'Calificación guardada',
        'promedio': float(promedio),
        'total': int(total),
        'tu_calificacion': nueva_calif
    })


@dir_bp.route('/<int:item_id>/mi-calificacion', methods=['GET'])
def mi_calificacion(item_id):
    """Obtiene la calificación que el usuario actual dio a un servicio."""
    user = get_current_user()
    if not user:
        return jsonify({'calificacion': None})

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT calificacion FROM calificaciones_directorio
        WHERE directorio_id = %s AND usuario_telefono = %s
    """, (item_id, user['telefono']))
    row = cur.fetchone()
    cur.close()
    return jsonify({'calificacion': row[0] if row else None})


@dir_bp.route('', methods=['POST'])
def crear():
    """Admin: crear entrada en el directorio."""
    _, error = require_api_admin()
    if error:
        return error

    data = request.form
    foto_file = request.files.get('foto')

    tipo = data.get('tipo', 'general')
    categoria_manual = data.get('categoria', '').strip()
    categoria = obtener_categoria_segun_tipo(tipo, categoria_manual)

    # Subir foto si existe
    foto_url = None
    if foto_file and foto_file.filename:
        foto_url = subir_imagen(foto_file)
        if not foto_url:
            return jsonify({'error': 'Error al subir la imagen'}), 500

    campos = ['nombre', 'telefono', 'horario', 'direccion', 'icono', 'orden']
    valores = []
    for c in campos:
        val = data.get(c, '') or (0 if c == 'orden' else '')
        valores.append(val)
    
    # Agregar categoria, tipo, foto, descripcion_corta
    descripcion = data.get('descripcion_corta', '').strip()
    icono = data.get('icono', '📍') or '📍'
    orden = int(data.get('orden', 0))

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO directorio 
            (categoria, nombre, telefono, horario, direccion, icono, orden, tipo, foto, descripcion_corta)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (categoria, valores[0], valores[1], valores[2], valores[3], icono, orden, tipo, foto_url, descripcion))
    nuevo_id = cur.fetchone()[0]
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Creado', 'id': nuevo_id}), 201


@dir_bp.route('/<int:item_id>', methods=['PUT'])
def actualizar(item_id):
    """Admin: actualizar entrada en el directorio."""
    _, error = require_api_admin()
    if error:
        return error

    data = request.form
    foto_file = request.files.get('foto')

    # Obtener datos actuales
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT tipo, categoria FROM directorio WHERE id = %s", (item_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return jsonify({'error': 'No encontrado'}), 404
    tipo_actual, cat_actual = row

    # Determinar nueva categoría
    tipo = data.get('tipo', tipo_actual)
    categoria_manual = data.get('categoria', '').strip()
    categoria = obtener_categoria_segun_tipo(tipo, categoria_manual)

    # Subir nueva foto si se envió
    foto_url = None
    if foto_file and foto_file.filename:
        foto_url = subir_imagen(foto_file)
        if not foto_url:
            return jsonify({'error': 'Error al subir la imagen'}), 500

    # Construir updates
    updates = {}
    if categoria:
        updates['categoria'] = categoria
    if tipo:
        updates['tipo'] = tipo
    if foto_url:
        updates['foto'] = foto_url

    campos_texto = ['nombre', 'telefono', 'horario', 'direccion', 'icono', 'descripcion_corta']
    for c in campos_texto:
        if c in data:
            val = data[c].strip() if data[c] else ''
            if c == 'icono' and not val:
                val = '📍'
            updates[c] = val

    if 'orden' in data:
        try:
            updates['orden'] = int(data['orden'])
        except ValueError:
            pass

    if not updates:
        return jsonify({'error': 'Nada que actualizar'}), 400

    set_clause = ', '.join(f"{k} = %s" for k in updates)
    valores = list(updates.values()) + [item_id]

    cur = db.cursor()
    cur.execute(f"UPDATE directorio SET {set_clause} WHERE id = %s", valores)
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Actualizado'})


@dir_bp.route('/<int:item_id>', methods=['DELETE'])
def eliminar(item_id):
    """Admin: eliminar entrada."""
    _, error = require_api_admin()
    if error:
        return error
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM directorio WHERE id = %s", (item_id,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Eliminado'})


@dir_bp.route('/<int:item_id>/toggle', methods=['POST'])
def toggle(item_id):
    """Admin: activar/desactivar entrada."""
    _, error = require_api_admin()
    if error:
        return error
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE directorio SET activo = NOT activo WHERE id = %s", (item_id,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Actualizado'})