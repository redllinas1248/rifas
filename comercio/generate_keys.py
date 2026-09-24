from py_vapid import Vapid
import base64
from cryptography.hazmat.primitives import serialization

# Generar claves VAPID
vapid = Vapid()
vapid.generate_keys()

# Obtener la clave pública en formato uncompressed point (65 bytes) y codificar a base64 URL-safe
public_key_bytes = vapid.public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)
public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')

# Obtener la clave privada en formato PKCS8 sin encriptar y codificar a base64 URL-safe
private_key_bytes = vapid.private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
# Eliminar encabezados PEM y espacios para obtener solo los datos base64
# La clave privada VAPID debe ser una cadena base64 de los bytes de la clave.
# Para simplificar, extraemos solo los bytes de la clave privada en formato raw (no PEM)
# La forma más segura: obtener los bytes de la clave en formato PKCS8 sin cifrar y codificarlos
private_bytes_raw = vapid.private_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
private_key_b64 = base64.urlsafe_b64encode(private_bytes_raw).decode('utf-8').rstrip('=')

print("=" * 50)
print("🔑 CLAVES VAPID PARA NOTIFICACIONES PUSH")
print("=" * 50)
print()
print("📌 VAPID_PUBLIC_KEY (pública):")
print(public_key_b64)
print()
print("🔒 VAPID_PRIVATE_KEY (privada - NO compartir):")
print(private_key_b64)
print()
print("=" * 50)
print("✅ Copia estas claves en las variables de entorno de Render:")
print("   - VAPID_PUBLIC_KEY")
print("   - VAPID_PRIVATE_KEY")
print("=" * 50)