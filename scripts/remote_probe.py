"""Read-only public HTTPS/WSS smoke test; credentials stay in ignored runtime."""
import asyncio
import json
import ssl
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]


async def synchronize(socket):
    await socket.send(json.dumps({'v': 1, 'type': 'HELLO', 'hasModel': False, 'lastSeq': {}}))
    for _ in range(1000):
        message = json.loads(await asyncio.wait_for(socket.recv(), 30))
        if message.get('type') == 'PING':
            await socket.send(json.dumps({'v': 1, 'type': 'PONG'}))
        if message.get('type') == 'ERROR':
            raise RuntimeError('WebSocket synchronization was rejected')
        if message.get('type') == 'SYNC_END':
            return
    raise RuntimeError('WebSocket synchronization did not finish')


async def run():
    network = json.loads((ROOT / 'runtime/network.local.json').read_text(encoding='utf-8-sig'))
    if network.get('mode') != 'remote':
        raise RuntimeError('Start-Remote.cmd must be running before this probe')
    origin = network['origin']
    if not origin.startswith('https://'):
        raise RuntimeError('Public HTTPS origin required')
    accounts = json.loads((ROOT / 'runtime/demo-accounts.local.json').read_text(encoding='utf-8-sig'))['accounts']
    tls = ssl.create_default_context()
    result = {'origin': origin, 'tlsVerified': True, 'accounts': [],
              'topology': 'Internet round trip from server PC; separate network not verified'}
    url = origin.replace('https:', 'wss:', 1) + '/ws'
    for account in accounts[:2]:
        async with httpx.AsyncClient(base_url=origin, verify=tls, trust_env=False, timeout=30) as client:
            response = await client.get('/api/health')
            if response.status_code != 200:
                raise RuntimeError('Public health check returned HTTP ' + str(response.status_code))
            response = await client.post('/api/v1/auth/login', headers={'Origin': origin},
                                         json={'identifier': account['phone'], 'password': account['password']})
            if response.status_code != 200:
                raise RuntimeError('Login returned HTTP ' + str(response.status_code))
            session = response.json()
            try:
                cookie_flags = response.headers.get('set-cookie', '').lower()
                assert 'secure' in cookie_flags and 'httponly' in cookie_flags
                assert (await client.get('/api/v1/auth/session')).status_code == 200
                rejected = await client.post('/api/v1/auth/logout', headers={'Origin': 'https://untrusted.invalid'})
                assert rejected.status_code == 403
                headers = {'Cookie': 'ro_session=' + client.cookies.get('ro_session')}
                for _ in range(2):
                    async with websockets.connect(url, ssl=tls, origin=origin, proxy=None,
                                                  additional_headers=headers) as socket:
                        await synchronize(socket)
                try:
                    async with websockets.connect(url, ssl=tls, origin='https://untrusted.invalid',
                                                  proxy=None, additional_headers=headers):
                        raise AssertionError('Wrong WebSocket Origin was accepted')
                except websockets.exceptions.InvalidStatus as exc:
                    assert exc.response.status_code == 403
                result['accounts'].append({'role': account['role'], 'login': 200,
                                           'websocket': 'synchronized', 'reconnect': 'passed',
                                           'httpAndWebsocketWrongOrigin': 403})
            finally:
                logout = await client.post('/api/v1/auth/logout',
                                           headers={'Origin': origin, 'X-CSRF-Token': session['csrfToken']})
                if logout.status_code != 200:
                    raise RuntimeError('Test session cleanup returned HTTP ' + str(logout.status_code))
    folder = ROOT / 'runtime/browser-test-results'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'remote-acceptance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as exc:
        # Never print server bodies, cookies, credentials or provider errors.
        print('Remote probe failed: ' + type(exc).__name__)
        raise SystemExit(1) from None
