from flask import current_app
from db import get_db
from pywebpush import webpush, WebPushException
import json
import os

VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_CLAIMS = {
    'sub': 'mailto:tu-email@example.com'  # CAMBIA ESTO POR TU EMAIL
}


def enviar_notificacion_a_todos(title, body, url='/transmisiones', icon='/static/img/icon-192.png'):
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        current_app.logger.warning("Claves VAPID no configuradas")
        return {'error': 'Claves VAPID no configuradas'}, 500

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT endpoint, auth_key, p256dh_key FROM push_subscriptions")
    subscriptions = cur.fetchall()
    cur.close()

    if not subscriptions:
        return {'mensaje': 'No hay suscriptores'}, 200

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

    return {'mensaje': f'Notificaciones enviadas a {success_count} suscriptores'}, 200