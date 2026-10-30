"""Prepare a local LAN profile and a client bundle containing public material only."""
import argparse
import hashlib
import ipaddress
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]


def validate_address(value):
    address = ipaddress.IPv4Address(value)
    allowed = any(address in ipaddress.ip_network(network) for network in
                  ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if not allowed:
        raise ValueError('Use a private LAN IPv4 address assigned to this server')
    return address


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.pending')
    temp.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    os.replace(temp, path)


def private_bytes(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def ensure_authority(folder):
    key_path, cert_path = folder / 'ca-key.pem', folder / 'ca.pem'
    if key_path.exists() != cert_path.exists():
        raise ValueError('Incomplete LAN CA: preserve the existing files and repair the certificate pair')
    if key_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if (key.public_key().public_numbers() != cert.public_key().public_numbers()
                or not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                or cert.not_valid_after_utc <= datetime.now(timezone.utc) + timedelta(days=7)):
            raise ValueError('LAN CA is invalid or expiring; renew it and distribute the new public CA explicitly')
        return key, cert
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'RealtimeOrders LAN Demo CA')])
    instant = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(instant - timedelta(minutes=5)).not_valid_after(instant + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                           key_encipherment=False, data_encipherment=False, key_agreement=False,
                           key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    write_atomic(key_path, private_bytes(key))
    write_atomic(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def ensure_server_certificate(folder, address, ca_key, ca_cert):
    key_path, cert_path = folder / 'key.pem', folder / 'cert.pem'
    if key_path.exists() and cert_path.exists():
        try:
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
            addresses = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
            if (address in addresses and key.public_key().public_numbers() == cert.public_key().public_numbers()
                    and cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=7)):
                return cert
        except (ValueError, TypeError, x509.ExtensionNotFound, InvalidSignature):
            # A leaf may be replaced without changing the trusted root authority.
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    instant = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(address))]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(instant - timedelta(minutes=5))
            .not_valid_after(min(instant + timedelta(days=90), ca_cert.not_valid_after_utc))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
                x509.IPAddress(ipaddress.ip_address('::1')), x509.IPAddress(address)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                           key_encipherment=True, data_encipherment=False, key_agreement=False,
                           key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    write_atomic(key_path, private_bytes(key))
    write_atomic(cert_path, cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert


TRUST_SCRIPT = r"""param([switch]$Remove)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'connection.json') -Raw | ConvertFrom-Json
$file=Join-Path $PSScriptRoot 'RealtimeOrders-LAN-CA.cer'
if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $info.caSha256){throw 'Certificate fingerprint mismatch'}
$cert=New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($file)
$storePath='Cert:\CurrentUser\Root\' + $cert.Thumbprint
if($Remove){
    if(Test-Path -LiteralPath $storePath){Remove-Item -LiteralPath $storePath}
    Write-Host 'Removed the RealtimeOrders LAN CA for this Windows user.'
}else{
    Import-Certificate -FilePath $file -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Write-Host ('Trusted RealtimeOrders LAN CA. Open ' + $info.origin)
    Write-Host ('Certificate SHA256: ' + $info.caSha256)
}
"""


def configure(root, address=None, local=False):
    root = Path(root)
    config_path = root / 'runtime/network.local.json'
    if local:
        settings = {'mode': 'local', 'origin': 'https://localhost:3443'}
        write_atomic(config_path, json.dumps(settings, indent=2) + '\n')
        return settings
    address = validate_address(address)
    folder = root / 'runtime/tls-lan'
    ca_key, ca_cert = ensure_authority(folder)
    leaf = ensure_server_certificate(folder, address, ca_key, ca_cert)
    origin = 'https://' + str(address) + ':3443'
    settings = {'mode': 'lan', 'address': str(address), 'origin': origin, 'tlsDirectory': 'runtime/tls-lan'}
    bundle = root / 'runtime/lan-client'
    public_der = ca_cert.public_bytes(serialization.Encoding.DER)
    info = {'origin': origin, 'caSha256': hashlib.sha256(public_der).hexdigest().upper(),
            'certificateExpiresUtc': leaf.not_valid_after_utc.isoformat()}
    write_atomic(bundle / 'RealtimeOrders-LAN-CA.cer', public_der)
    write_atomic(bundle / 'connection.json', json.dumps(info, indent=2) + '\n')
    write_atomic(bundle / 'Trust-Server.ps1', TRUST_SCRIPT)
    write_atomic(bundle / 'Trust-Server.cmd',
                 '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Trust-Server.ps1"\r\npause\r\n')
    write_atomic(bundle / 'Open-RealtimeOrders.cmd', '@echo off\r\nstart "" "' + origin + '"\r\n')
    write_atomic(bundle / 'README.txt',
                 'RealtimeOrders - client LAN\n\n'
                 '1. Ket noi cung Wi-Fi/LAN voi may server.\n'
                 '2. Doi chieu SHA256 chung thu voi chu server:\n   ' + info['caSha256'] + '\n'
                 '3. Chay Trust-Server.cmd mot lan tren Windows (CurrentUser Root).\n'
                 '4. Chay Open-RealtimeOrders.cmd hoac mo ' + origin + '.\n'
                 '5. Dang nhap bang tai khoan do chu server cung cap rieng.\n\n'
                 'Khong can cai Python, MySQL hay clone source tren may client.\n'
                 'Go trust sau demo: powershell -ExecutionPolicy Bypass -File Trust-Server.ps1 -Remove\n'
                 'Thu muc nay chi chua chung thu cong khai va huong dan; khong co private key hay mat khau.\n')
    write_atomic(config_path, json.dumps(settings, indent=2) + '\n')
    return {**settings, 'clientBundle': str(bundle), 'caSha256': info['caSha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--address')
    choices.add_argument('--local', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(ROOT, args.address, args.local)))


if __name__ == '__main__':
    main()
