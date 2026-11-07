"""Génère une paire de clés VAPID (P-256) au format attendu par pywebpush / navigateurs."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization as s
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
k = ec.generate_private_key(ec.SECP256R1())
priv = b(k.private_numbers().private_value.to_bytes(32, "big"))
pub = b(k.public_key().public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint))
print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
