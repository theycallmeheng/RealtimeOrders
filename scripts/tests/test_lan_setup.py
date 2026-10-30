import ipaddress
import json
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_lan import configure, validate_address


class LanSetupTests(unittest.TestCase):
    def setUp(self):
        temp_base = Path(__file__).resolve().parents[2] / 'runtime/lan-unit-tests'
        temp_base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=temp_base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_only_private_ipv4_addresses_are_supported(self):
        for value in ('8.8.8.8', '127.0.0.1', '0.0.0.0', '169.254.1.2', '::1', 'hostname.invalid'):
            with self.subTest(address=value), self.assertRaises(ValueError):
                validate_address(value)
        for value in ('10.0.0.2', '172.20.10.2', '192.168.1.25'):
            self.assertEqual(str(validate_address(value)), value)

    def test_leaf_is_signed_by_ca_and_covers_lan_and_loopback(self):
        configure(self.root, '172.20.10.2')
        folder = self.root / 'runtime/tls-lan'
        root = x509.load_pem_x509_certificate((folder / 'ca.pem').read_bytes())
        leaf = x509.load_pem_x509_certificate((folder / 'cert.pem').read_bytes())
        key = serialization.load_pem_private_key((folder / 'key.pem').read_bytes(), password=None)
        root.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes, padding.PKCS1v15(), leaf.signature_hash_algorithm)
        self.assertEqual(key.public_key().public_numbers(), leaf.public_key().public_numbers())
        self.assertTrue(root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertFalse(leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertIn('localhost', names.get_values_for_type(x509.DNSName))
        for value in ('172.20.10.2', '127.0.0.1', '::1'):
            self.assertIn(ipaddress.ip_address(value), names.get_values_for_type(x509.IPAddress))

    def test_reconfigure_preserves_ca_and_refreshes_leaf_only_when_needed(self):
        configure(self.root, '172.20.10.2')
        folder = self.root / 'runtime/tls-lan'
        first_ca, first_leaf = (folder / 'ca.pem').read_bytes(), (folder / 'cert.pem').read_bytes()
        configure(self.root, '172.20.10.2')
        self.assertEqual(first_leaf, (folder / 'cert.pem').read_bytes())
        configure(self.root, '192.168.1.25')
        self.assertEqual(first_ca, (folder / 'ca.pem').read_bytes())
        self.assertNotEqual(first_leaf, (folder / 'cert.pem').read_bytes())
        self.assertEqual(json.loads((self.root / 'runtime/lan-client/connection.json').read_text())['origin'],
                         'https://192.168.1.25:3443')

    def test_client_bundle_has_no_private_keys_or_credentials(self):
        configure(self.root, '172.20.10.2')
        bundle = self.root / 'runtime/lan-client'
        self.assertEqual({p.name for p in bundle.iterdir()}, {
            'RealtimeOrders-LAN-CA.cer', 'connection.json', 'Trust-Server.ps1',
            'Trust-Server.cmd', 'Open-RealtimeOrders.cmd', 'README.txt'})
        for filename in bundle.iterdir():
            self.assertNotIn(b'PRIVATE KEY', filename.read_bytes())
        script = (bundle / 'Trust-Server.ps1').read_text()
        self.assertIn('Cert:\\CurrentUser\\Root', script)
        self.assertIn('Get-FileHash', script)
        self.assertNotIn('LocalMachine', script)

    def test_local_mode_preserves_lan_certificates_and_other_configuration(self):
        env = self.root / '.env'
        env.write_text('SENTINEL=unchanged\n')
        configure(self.root, '172.20.10.2')
        root_before = (self.root / 'runtime/tls-lan/ca.pem').read_bytes()
        result = configure(self.root, local=True)
        self.assertEqual(result['origin'], 'https://localhost:3443')
        self.assertEqual(root_before, (self.root / 'runtime/tls-lan/ca.pem').read_bytes())
        self.assertEqual(env.read_text(), 'SENTINEL=unchanged\n')


if __name__ == '__main__':
    unittest.main()
