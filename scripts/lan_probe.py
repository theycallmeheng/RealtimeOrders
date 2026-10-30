"""Exercise HTTPS/WSS through the configured LAN address on an audit database."""
import asyncio
import json
import os
import ssl
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import websockets
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import settings


async def receive(socket, heads):
    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
    if message.get('type') == 'PING':
        await socket.send(json.dumps({'v': 1, 'type': 'PONG'}))
    if message.get('type') == 'EVENT':
        heads[message['topic']] = message['seq']
    if message.get('type') == 'SYNC_END':
        heads.update(message['heads'])
    return message


async def sync(socket, heads, has_model=False, dataset_epoch=None):
    await socket.send(json.dumps({'v': 1, 'type': 'HELLO', 'hasModel': has_model, 'lastSeq': heads, 'datasetEpoch':dataset_epoch}))
    messages = []
    for _ in range(1000):
        message = await receive(socket, heads)
        messages.append(message)
        if message.get('type') == 'SYNC_END':
            return messages
    raise AssertionError('Sync did not finish within a bounded message count')


async def wait_for_chat(socket, heads, message_id):
    for _ in range(200):
        event = await receive(socket, heads)
        if event.get('eventType') == 'CHAT_MESSAGE' and event.get('payload', {}).get('id') == message_id:
            return
    raise AssertionError('Expected chat event was not received')


async def run():
    if not make_url(settings.database_url).database.startswith('realtimeorders_audit_'):
        raise RuntimeError('Run this probe only via isolated_validation.py on an audit database')
    network = json.loads((ROOT / 'runtime/network.local.json').read_text(encoding='utf-8'))
    origin = settings.app_origin
    if network.get('mode') != 'lan' or origin != network['origin']:
        raise RuntimeError('Restart isolated validation with --network-mode configured before this probe')
    tls = ssl.create_default_context(cafile=str(ROOT / 'runtime/tls-lan/ca.pem'))
    accounts = json.loads((ROOT / 'runtime/demo-accounts.local.json').read_text(encoding='utf-8'))['accounts']
    clients = []
    sessions = []
    sockets = []
    result = {'origin': origin, 'topology': 'one Windows host, clients connect through its LAN IPv4',
              'tlsCertificateVerified': False, 'twoPhysicalMachinesVerified': False}
    try:
        for account in (accounts[0], accounts[1]):
            client = httpx.AsyncClient(base_url=origin, verify=tls, trust_env=False, timeout=20)
            clients.append(client)
            health = await client.get('/api/health')
            health.raise_for_status()
            login = await client.post('/api/v1/auth/login', headers={'Origin': origin},
                                      json={'identifier': account['phone'], 'password': account['password']})
            login.raise_for_status()
            sessions.append(login.json())
            assert 'secure' in login.headers.get('set-cookie', '').lower()
            socket = await websockets.connect(origin.replace('https:', 'wss:') + '/ws', ssl=tls,
                                              origin=origin, proxy=None,
                                              additional_headers={'Cookie': 'ro_session=' + client.cookies.get('ro_session')})
            sockets.append(socket)
        result['tlsCertificateVerified'] = True
        heads = [{}, {}]
        epochs=[]
        for socket, cursor in zip(sockets, heads):
            messages=await sync(socket, cursor)
            epochs.append(messages[-1]['datasetEpoch'])
        result['synchronizedClients'] = len(sockets)

        customer, admin = clients[1], clients[0]
        customer_headers = {'Origin': origin, 'X-CSRF-Token': sessions[1]['csrfToken']}
        admin_headers = {'Origin': origin, 'X-CSRF-Token': sessions[0]['csrfToken']}
        conv = await customer.get('/api/v1/conversations/me')
        conv.raise_for_status()
        path = '/api/v1/conversations/' + conv.json()['id'] + '/messages'
        body = {'clientMessageId': str(uuid4()), 'text': 'LAN probe ' + str(uuid4()), 'assetIds': []}
        sent = await customer.post(path, json=body, headers=customer_headers)
        sent.raise_for_status()
        message_id = sent.json()['id']
        await asyncio.gather(*(wait_for_chat(socket, cursor, message_id) for socket, cursor in zip(sockets, heads)))
        result['customerToAdminLiveEvent'] = True
        duplicate = await customer.post(path, json=body, headers=customer_headers)
        duplicate.raise_for_status()
        assert duplicate.json()['id'] == message_id
        history = await customer.get(path)
        history.raise_for_status()
        assert sum(item['id'] == message_id for item in history.json()) == 1
        result['retryDidNotDuplicateMessage'] = True

        await sockets[1].close()
        cursor = dict(heads[1])
        missed = await admin.post(path, headers=admin_headers,
                                 json={'clientMessageId': str(uuid4()), 'text': 'LAN replay ' + str(uuid4()), 'assetIds': []})
        missed.raise_for_status()
        await wait_for_chat(sockets[0], heads[0], missed.json()['id'])
        recovered = await websockets.connect(origin.replace('https:', 'wss:') + '/ws', ssl=tls,
                                              origin=origin, proxy=None,
                                              additional_headers={'Cookie': 'ro_session=' + customer.cookies.get('ro_session')})
        sockets.append(recovered)
        replay = await sync(recovered, cursor, has_model=True, dataset_epoch=epochs[1])
        assert any(m.get('type') == 'SYNC_BEGIN' and m.get('mode') == 'REPLAY' for m in replay)
        assert any(m.get('eventType') == 'CHAT_MESSAGE' and m['payload'].get('id') == missed.json()['id'] for m in replay)
        result['reconnectReplay'] = True

        try:
            bad = await websockets.connect(origin.replace('https:', 'wss:') + '/ws', ssl=tls,
                                           origin='https://untrusted.invalid', proxy=None,
                                           additional_headers={'Cookie': 'ro_session=' + customer.cookies.get('ro_session')})
        except websockets.exceptions.InvalidStatus as exc:
            assert exc.response.status_code == 403
        else:
            await bad.close()
            raise AssertionError('Invalid WebSocket Origin was accepted')
        result['wrongOriginRejected'] = True
    finally:
        for socket in sockets:
            await socket.close()
        for client, session in zip(clients, sessions):
            await client.post('/api/v1/auth/logout', headers={'Origin': origin, 'X-CSRF-Token': session['csrfToken']})
        for client in clients:
            await client.aclose()
    evidence = Path(os.environ.get('AUDIT_EVIDENCE_DIR', str(ROOT / 'evidence/lan')))
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'lan-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    asyncio.run(run())
