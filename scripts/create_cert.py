"""Development certificate only; install/trust explicitly outside this script if needed."""
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

folder=Path(__file__).resolve().parents[1]/'runtime/tls'
folder.mkdir(parents=True,exist_ok=True)
if not (folder/'key.pem').exists():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'RealtimeOrders local development')])
    certificate=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())\
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))\
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=365))\
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)\
        .sign(key,hashes.SHA256())
    (folder/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (folder/'cert.pem').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
print('Local TLS certificate ready in runtime/tls; self-signed, not a public CA certificate.')
