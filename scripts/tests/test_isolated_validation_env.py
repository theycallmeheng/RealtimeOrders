import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isolated_validation import context_env


class IsolatedValidationEnvironmentTests(unittest.TestCase):
    def test_real_message_provider_credentials_are_removed(self):
        secrets = {
            "ZALO_ACCESS_TOKEN": "secret-zalo",
            "ZALO_OTP_TEMPLATE_ID": "real-template",
            "TWILIO_AUTH_TOKEN": "secret-twilio",
            "SMTP_PASSWORD": "secret-smtp",
            "VIETMAP_API_KEY": "live-map-key", "GOOGLE_MAPS_SERVER_KEY": "live-map-server", "GOOGLE_MAPS_BROWSER_KEY": "live-browser",
            "PAYOS_CLIENT_ID": "live-id", "PAYOS_API_KEY": "live-key", "PAYOS_CHECKSUM_KEY": "live-checksum",
        }
        context = {"databaseUrl": "mysql+asyncmy://audit", "uploadDir": "runtime/audit",
                   "evidence": "evidence/audit", "appSecret": "test-only-secret"}
        with patch.dict(os.environ, secrets, clear=False):
            env = context_env(context)
        for key in secrets:
            self.assertEqual(env[key], "")
        self.assertEqual(env["DEMO_MODE"], "true")
        self.assertEqual(env["MAP_PROVIDER"], "osm")
        self.assertEqual(env["SMS_PROVIDER"], "demo")
        self.assertEqual(env["EMAIL_PROVIDER"], "demo")


if __name__ == "__main__":
    unittest.main()
