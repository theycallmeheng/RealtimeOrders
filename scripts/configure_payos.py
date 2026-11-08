"""Verify and register the platform's public payOS webhook without moving money."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import settings
import httpx


async def configure():
    if not all((settings.payos_client_id, settings.payos_api_key, settings.payos_checksum_key)):
        raise RuntimeError('Missing PAYOS_CLIENT_ID, PAYOS_API_KEY or PAYOS_CHECKSUM_KEY in .env')
    network_path = ROOT / 'runtime/network.local.json'
    network = json.loads(network_path.read_text(encoding='utf-8-sig')) if network_path.exists() else {}
    origin = network.get('origin') or settings.app_origin
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1') or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise RuntimeError('Set the public HTTPS application origin before registering payOS')
    webhook = origin.rstrip('/') + '/api/v1/payments/payos/webhook'
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        response = await client.post('https://api-merchant.payos.vn/confirm-webhook',
            headers={'x-client-id': settings.payos_client_id, 'x-api-key': settings.payos_api_key},
            json={'webhookUrl': webhook})
    result = response.json()
    if response.status_code != 200 or result.get('code') != '00':
        # Provider responses are deliberately not dumped: they can contain account details.
        raise RuntimeError(f"payOS webhook not confirmed (HTTP {response.status_code}, code {result.get('code', 'unknown')}); check channel keys, checksum and public URL")
    (ROOT / 'runtime/payos-setup.local.json').write_text(json.dumps({
        'webhookUrl': webhook, 'confirmed': True,
    }, indent=2) + '\n', encoding='utf-8')
    print('payOS accepted the channel credentials and confirmed the webhook.')
    print('Webhook: ' + webhook)
    print('No payment was created or transferred.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-webhook', action='store_true', required=True,
                        help='Register the current public application URL with this payOS channel')
    parser.parse_args()
    try:
        asyncio.run(configure())
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
