"""Create a localhost-only TLS certificate for the isolated updater QA server."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import ipaddress
import sys
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Local POE updater test')])
now = datetime.now(timezone.utc)
certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
    .public_key(key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
    .sign(key, hashes.SHA256()))
(output / 'local-cert.pem').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
(output / 'local-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
