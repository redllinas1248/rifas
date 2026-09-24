import os
import logging
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from db import get_db
from security import require_api_admin, get_current_user
import cloudinary.uploader
import cloudinary.api
import html

pub_bp = Blueprint('publicaciones', __name__, url_prefix='/api/publicaciones')
logger = logging.getLogger(__name__)

DIAS_PARA_ELIMINAR = 30  # Publicaciones más antiguas que esto se eliminarán


def subir_cloudinary(archivo, carpeta='posts'):
    import cloudinary.uploader
    resultado = cloudinary.uploader.upload(
        archivo,
        folder=f"comercio/{carpeta}",
        resource_type="auto"
    )
    return resultado['secure_url']


def eliminar_cloudinary_archivo(public_id, resource_type="image"):
    try:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception as e:
        current_app.logger.error(f"Error eliminando {public_id}: {e}")


def extraer_public_id(ruta):
    if '/comercio/' in ruta:
        partes = ruta.split('/comercio/')
        if len(partes) > 1:
            public_id = partes[1].split('.')[0]
            return f"comercio/{public_id}"
    return None


def eliminar_archivos_cloudinary(imagenes, videos):
    for ruta in imagenes:
        public_id = extraer_public_id(ruta)
        if public_id:
            eliminar_cloudinary_archivo(public_id, "image")
    for ruta in videos:
        public_id = extraer_public_id(ruta)
        if public_id:
            eliminar_cloudinary_archivo(public_id, "video")


def limpiar_publicaciones_antiguas():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT id, telefono
        FROM publicaciones
        WHERE fecha < NOW() - INTERVAL %s DAY
    """, (DIAS_PARA_ELIMINAR,))

    pubs = cur.fetchall()
    eliminadas = 0

    for pub_id, telefono in pubs:
        cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub_id,))
        imagenes = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub_id,))
        videos = [r[0] for r in cur.fetchall()]

        try:
            eliminar_archivos_cloudinary(imagenes, videos)
        except Exception as e:
            current_app.logger.error(f"Error eliminando archivos Cloudinary para pub {pub_id}: {e}")

        cur.execute("DELETE FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub_id,))
        cur.execute("DELETE FROM publicaciones_videos WHERE publicacion_id = %s", (pub_id,))
        cur.execute("DELETE FROM likes WHERE publicacion_id = %s", (pub_id,))
        cur.execute("DELETE FROM comentarios WHERE publicacion_id = %s", (pub_id,))
        cur.execute("DELETE FROM publicaciones WHERE id = %s", (pub_id,))

        eliminadas += 1

    db.commit()
    cur.close()
    return eliminadas


@pub_bp.route('/limpiar', methods=['POST'])
def limpiar_manual():
    _, error = require_api_admin()
    if error:
        return error

    try:
        eliminadas = limpiar_publicaciones_antiguas()
        return jsonify({
            'mensaje': f'Limpieza completada. {eliminadas} publicaciones eliminadas.',
            'eliminadas': eliminadas
        })
    except Exception as e:
        current_app.logger.error(f"Error en limpieza manual: {e}")
        return jsonify({'error': 'Error al ejecutar la limpieza'}), 500


@pub_bp.route('', methods=['GET'])
def listar():
    categoria_id = request.args.get('categoria_id')
    telefono_filtro = request.args.get('telefono')
    incluir_destacadas = request.args.get('incluir_destacadas', 'false').lower() == 'true'
    try:
        limite = max(1, min(int(request.args.get('limite', 20)), 50))
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        return jsonify({'error': 'Paginación inválida'}), 400

    db = get_db()
    cur = db.cursor()

    condiciones = ["p.destacada = false"]
    params = []
    if categoria_id:
        condiciones.append("p.categoria_id = %s")
        params.append(categoria_id)
    if telefono_filtro:
        condiciones.append("p.telefono = %s")
        params.append(telefono_filtro)

    if incluir_destacadas:
        condiciones = [c for c in condiciones if c != "p.destacada = false"]

    where = "WHERE " + " AND ".join(condiciones) if condiciones else ""

    query = f"""
        SELECT p.id, p.telefono, p.contenido, p.fecha, p.categoria_id,
               c.nombre AS categoria,
               u.nombre AS autor, u.foto AS autor_foto, u.telefono AS tel_autor, u.localidad AS comunidad,
               p.precio, p.destacada,
               (SELECT COUNT(*) FROM likes l WHERE l.publicacion_id = p.id) AS total_likes,
               (SELECT COUNT(*) FROM comentarios co WHERE co.publicacion_id = p.id) AS total_comentarios
        FROM publicaciones p
        LEFT JOIN categorias c ON c.id = p.categoria_id
        LEFT JOIN usuarios u ON u.telefono = p.telefono
        {where}
        ORDER BY p.fecha DESC
        LIMIT %s OFFSET %s
    """
    cur.execute(query, params + [limite, offset])
    rows = cur.fetchall()
    keys = ['id', 'telefono', 'contenido', 'fecha', 'categoria_id', 'categoria',
            'autor', 'autor_foto', 'tel_autor', 'comunidad', 'precio', 'destacada',
            'total_likes', 'total_comentarios']

    publicaciones = []
    for row in rows:
        pub = dict(zip(keys, row))
        pub['fecha'] = str(pub['fecha'])
        pub['precio'] = str(pub['precio']) if pub['precio'] else None
        cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub['id'],))
        pub['imagenes'] = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub['id'],))
        pub['videos'] = [r[0] for r in cur.fetchall()]
        publicaciones.append(pub)

    cur.close()
    return jsonify(publicaciones)


@pub_bp.route('/<int:pub_id>', methods=['GET'])
def detalle(pub_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.telefono, p.contenido, p.fecha, p.categoria_id,
               c.nombre AS categoria, u.nombre AS autor, u.foto AS autor_foto,
               u.telefono AS tel_autor, p.precio, u.localidad AS comunidad
        FROM publicaciones p
        LEFT JOIN categorias c ON c.id = p.categoria_id
        LEFT JOIN usuarios u ON u.telefono = p.telefono
        WHERE p.id = %s
    """, (pub_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        return jsonify({'error': 'No encontrada'}), 404

    keys = ['id', 'telefono', 'contenido', 'fecha', 'categoria_id', 'categoria',
            'autor', 'autor_foto', 'tel_autor', 'precio', 'comunidad']
    pub = dict(zip(keys, row))
    pub['fecha'] = str(pub['fecha'])
    pub['precio'] = str(pub['precio']) if pub['precio'] else None

    cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub_id,))
    pub['imagenes'] = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub_id,))
    pub['videos'] = [r[0] for r in cur.fetchall()]
    cur.close()
    return jsonify(pub)


@pub_bp.route('', methods=['POST'])
def crear():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    # Log de la publicación (IP y User-Agent)
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Desconocido')
    logger.warning(f"Publicación creada por {user['telefono']} desde IP {ip} con navegador {user_agent}")

    contenido = html.escape(request.form.get('contenido', '').strip())[:5000]
    categoria_id = request.form.get('categoria_id')
    precio = request.form.get('precio', '').strip() or None
    telefono = user['telefono']

    if not contenido:
        return jsonify({'error': 'El contenido es obligatorio'}), 400

    try:
        categoria_id = int(categoria_id) if categoria_id not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Categoría inválida'}), 400

    if precio is not None:
        try:
            from decimal import Decimal, InvalidOperation
            valor = Decimal(precio)
            if valor < 0 or valor > Decimal('999999999.99') or valor.as_tuple().exponent < -2:
                raise InvalidOperation
            precio = f"{valor:.2f}"
        except (InvalidOperation, ValueError):
            return jsonify({'error': 'Precio inválido'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM publicaciones WHERE telefono = %s AND fecha >= NOW() - INTERVAL '24 hours'",
        (telefono,)
    )
    count_hoy = cur.fetchone()[0]
    if count_hoy >= 2:
        cur.close()
        return jsonify({'error': '⏳ Llegaste al límite de 2 publicaciones por día. Intenta mañana.'}), 429

    cur.execute(
        "INSERT INTO publicaciones (telefono, contenido, categoria_id, precio) VALUES (%s, %s, %s, %s) RETURNING id",
        (telefono, contenido, categoria_id, precio)
    )
    pub_id = cur.fetchone()[0]
    db.commit()

    # Sistema de puntos
    cur.execute("SELECT COUNT(*) FROM publicaciones WHERE telefono = %s", (telefono,))
    total_pubs = cur.fetchone()[0]
    if total_pubs % 2 == 0:
        cur.execute("UPDATE usuarios SET puntos = puntos + 1 WHERE telefono = %s", (telefono,))
        cur.execute(
            "INSERT INTO puntos_historial (telefono, motivo, cantidad) VALUES (%s, %s, 1)",
            (telefono, "2 publicaciones completadas (" + str(total_pubs) + " total)")
        )
        db.commit()

    # Subir imágenes
    MAX_VIDEO_SIZE = 20 * 1024 * 1024
    for img in request.files.getlist('imagenes'):
        if img and img.filename:
            ext = img.filename.rsplit('.', 1)[-1].lower()
            if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
                try:
                    url = subir_cloudinary(img, 'imagenes')
                    cur.execute(
                        "INSERT INTO publicaciones_imagenes (publicacion_id, ruta) VALUES (%s, %s)",
                        (pub_id, url)
                    )
                    db.commit()
                except Exception as e:
                    current_app.logger.error(f"Error subiendo imagen: {e}")

    for vid in request.files.getlist('videos'):
        if vid and vid.filename:
            vid.seek(0, os.SEEK_END)
            size = vid.tell()
            vid.seek(0)
            if size > MAX_VIDEO_SIZE:
                continue
            ext = vid.filename.rsplit('.', 1)[-1].lower()
            if ext in {'mp4', 'mov', 'webm', 'avi'}:
                try:
                    url = subir_cloudinary(vid, 'videos')
                    cur.execute(
                        "INSERT INTO publicaciones_videos (publicacion_id, ruta) VALUES (%s, %s)",
                        (pub_id, url)
                    )
                    db.commit()
                except Exception as e:
                    current_app.logger.error(f"Error subiendo video: {e}")

    cur.close()
    return jsonify({'mensaje': 'Publicación creada', 'id': pub_id}), 201


@pub_bp.route('/<int:pub_id>', methods=['DELETE'])
def eliminar(pub_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'No autenticado'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT telefono FROM publicaciones WHERE id = %s", (pub_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        return jsonify({'error': 'No encontrada'}), 404
    if row[0] != user['telefono'] and user['rol'] != 'admin':
        cur.close()
        return jsonify({'error': 'Sin permiso'}), 403

    cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub_id,))
    imagenes = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub_id,))
    videos = [r[0] for r in cur.fetchall()]

    try:
        eliminar_archivos_cloudinary(imagenes, videos)
    except Exception as e:
        current_app.logger.error(f"Error eliminando archivos de Cloudinary: {e}")

    cur.execute("DELETE FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub_id,))
    cur.execute("DELETE FROM publicaciones_videos WHERE publicacion_id = %s", (pub_id,))
    cur.execute("DELETE FROM publicaciones WHERE id = %s", (pub_id,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Publicación eliminada'})


@pub_bp.route('/categorias', methods=['GET'])
def categorias():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, nombre FROM categorias")
    rows = cur.fetchall()
    cur.close()
    return jsonify([{'id': r[0], 'nombre': r[1]} for r in rows])


@pub_bp.route('/<int:pub_id>/destacar', methods=['POST'])
def destacar(pub_id):
    _, error = require_api_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    activar = data.get('destacada', True)

    db = get_db()
    cur = db.cursor()
    if activar:
        cur.execute("UPDATE publicaciones SET destacada = false")
        cur.execute("UPDATE publicaciones SET destacada = true WHERE id = %s", (pub_id,))
    else:
        cur.execute("UPDATE publicaciones SET destacada = false WHERE id = %s", (pub_id,))
    db.commit()
    cur.close()
    return jsonify({'mensaje': 'Actualizado'})


@pub_bp.route('/buscar', methods=['GET'])
def buscar():
    q = request.args.get('q', '').strip()
    try:
        limite = max(1, min(int(request.args.get('limite', 20)), 50))
    except (TypeError, ValueError):
        return jsonify({'error': 'Límite inválido'}), 400
    if not q:
        return jsonify({'usuarios': [], 'publicaciones': []})

    like = f"%{q}%"
    db = get_db()
    cur = db.cursor()

    # BUSCAR USUARIOS
    cur.execute("""
        SELECT telefono, nombre, foto, localidad,
               (SELECT COUNT(*) FROM publicaciones WHERE telefono = u.telefono) AS total_pubs
        FROM usuarios u
        WHERE nombre ILIKE %s OR telefono LIKE %s
        LIMIT 5
    """, (like, like))
    usuarios = []
    for row in cur.fetchall():
        usuarios.append({
            'telefono': row[0],
            'nombre': row[1] or row[0],
            'foto': row[2],
            'localidad': row[3],
            'total_pubs': row[4]
        })

    # BUSCAR PUBLICACIONES
    cur.execute("""
        SELECT p.id, p.telefono, p.contenido, p.fecha,
               u.nombre AS autor, u.foto AS autor_foto, u.telefono AS tel_autor,
               p.precio, u.localidad AS comunidad, p.destacada,
               (SELECT COUNT(*) FROM likes l WHERE l.publicacion_id = p.id) AS total_likes,
               (SELECT COUNT(*) FROM comentarios co WHERE co.publicacion_id = p.id) AS total_comentarios
        FROM publicaciones p
        LEFT JOIN usuarios u ON u.telefono = p.telefono
        WHERE p.contenido ILIKE %s OR u.nombre ILIKE %s OR u.telefono LIKE %s
        ORDER BY p.fecha DESC LIMIT %s
    """, (like, like, like, limite))
    rows = cur.fetchall()
    keys = ['id', 'telefono', 'contenido', 'fecha', 'autor', 'autor_foto',
            'tel_autor', 'precio', 'comunidad', 'destacada', 'total_likes', 'total_comentarios']
    publicaciones = []
    for row in rows:
        pub = dict(zip(keys, row))
        pub['fecha'] = str(pub['fecha'])
        pub['precio'] = str(pub['precio']) if pub['precio'] else None
        cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub['id'],))
        pub['imagenes'] = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub['id'],))
        pub['videos'] = [r[0] for r in cur.fetchall()]
        publicaciones.append(pub)

    cur.close()
    return jsonify({'usuarios': usuarios, 'publicaciones': publicaciones})


@pub_bp.route('/admin/lista', methods=['GET'])
def admin_lista():
    _, error = require_api_admin()
    if error:
        return error
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.telefono, p.contenido, p.fecha,
               u.nombre AS autor,
               (SELECT COUNT(*) FROM likes l WHERE l.publicacion_id = p.id) AS likes,
               (SELECT COUNT(*) FROM comentarios c WHERE c.publicacion_id = p.id) AS comentarios
        FROM publicaciones p
        LEFT JOIN usuarios u ON u.telefono = p.telefono
        ORDER BY p.fecha DESC LIMIT 100
    """)
    rows = cur.fetchall()
    keys = ['id', 'telefono', 'contenido', 'fecha', 'autor', 'likes', 'comentarios']
    result = [dict(zip(keys, r)) for r in rows]
    for r in result:
        r['fecha'] = str(r['fecha'])
    cur.close()
    return jsonify(result)


@pub_bp.route('/destacadas', methods=['GET'])
def destacadas():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.telefono, p.contenido, p.fecha, p.precio,
               u.nombre AS autor, u.foto AS autor_foto, u.telefono AS tel_autor, u.localidad AS comunidad,
               (SELECT COUNT(*) FROM likes l WHERE l.publicacion_id = p.id) AS total_likes,
               (SELECT COUNT(*) FROM comentarios co WHERE co.publicacion_id = p.id) AS total_comentarios
        FROM publicaciones p
        LEFT JOIN usuarios u ON u.telefono = p.telefono
        WHERE p.destacada = true
        ORDER BY p.fecha DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    keys = ['id', 'telefono', 'contenido', 'fecha', 'precio', 'autor', 'autor_foto',
            'tel_autor', 'comunidad', 'total_likes', 'total_comentarios']
    publicaciones = []
    for row in rows:
        pub = dict(zip(keys, row))
        pub['fecha'] = str(pub['fecha'])
        pub['precio'] = str(pub['precio']) if pub['precio'] else None
        cur.execute("SELECT ruta FROM publicaciones_imagenes WHERE publicacion_id = %s", (pub['id'],))
        pub['imagenes'] = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ruta FROM publicaciones_videos WHERE publicacion_id = %s", (pub['id'],))
        pub['videos'] = [r[0] for r in cur.fetchall()]
        publicaciones.append(pub)
    cur.close()
    return jsonify(publicaciones)