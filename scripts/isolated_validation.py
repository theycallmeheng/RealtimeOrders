"""Run local validation against a verified MySQL copy, preserving the demo DB.

Requires the installed Windows demo and runtime/mysql-PORT-admin-password.local.
Stop the application before prepare. No database is dropped or overwritten.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from socket import create_connection

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/Scripts/python.exe'
CONTEXT = ROOT / 'runtime/isolated-validation.local.json'
MYSQL_BIN = Path(r'C:\Program Files\MySQL\MySQL Server 8.0\bin')
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]


def dump_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


async def fingerprints(connection, database):
    result = {}
    async with connection.cursor() as cursor:
        await cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE=%s ORDER BY TABLE_NAME', (database, 'BASE TABLE'))
        tables = [row[0] for row in await cursor.fetchall()]
        for table in tables:
            await cursor.execute(f'SELECT * FROM `{database}`.`{table}` ORDER BY 1')
            records = await cursor.fetchall()
            normalized = sorted(json.dumps(row, default=str, ensure_ascii=False, separators=(',', ':')) for row in records)
            result[table] = {'rows': len(records), 'sha256': hashlib.sha256('\n'.join(normalized).encode()).hexdigest()}
    return result


def network_values(mode='configured'):
    if mode == 'local':
        return {'networkMode': 'local', 'origin': 'https://localhost:3443'}
    config_path = ROOT / 'runtime/network.local.json'
    if not config_path.exists():
        return {'networkMode': 'configured', 'origin': 'https://localhost:3443'}
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('mode') == 'local':
        return {'networkMode': 'configured', 'origin': 'https://localhost:3443'}
    from configure_lan import validate_address
    address = str(validate_address(config.get('address')))
    require(config.get('mode') == 'lan' and config.get('origin') == 'https://' + address + ':3443',
            'Invalid configured LAN origin')
    return {'networkMode': 'configured', 'origin': config['origin']}


def context_env(context):
    return {**os.environ, 'PYTHONUTF8': '1', 'NEXT_TELEMETRY_DISABLED': '1',
            'DATABASE_URL': context['databaseUrl'], 'UPLOAD_DIR': context['uploadDir'],
            'AUDIT_EVIDENCE_DIR': context['evidence'], 'DEMO_MODE': 'true',
            'SMS_PROVIDER': 'demo', 'EMAIL_PROVIDER': 'demo',
            'ZALO_ACCESS_TOKEN': '', 'ZALO_OTP_TEMPLATE_ID': '',
            'TWILIO_ACCOUNT_SID': '', 'TWILIO_AUTH_TOKEN': '', 'TWILIO_FROM': '',
            'SMTP_HOST': '', 'SMTP_USER': '', 'SMTP_PASSWORD': '', 'SMTP_FROM': '',
            'APP_SECRET': context['appSecret'],
            'REALTIMEORDERS_NETWORK_MODE': context.get('networkMode', 'local'),
            'APP_ORIGIN': context.get('origin', 'https://localhost:3443')}


def save_running(context):
    context['state'] = 'RUNNING'
    context['services'] = json.loads((ROOT / 'runtime/services.local.json').read_text(encoding='utf-8-sig'))
    dump_json(CONTEXT, context)


def check_context(context, action):
    from sqlalchemy.engine import make_url
    require(re.fullmatch(r'realtimeorders_audit_[A-Za-z0-9_]+', context['database']), 'Invalid test database context')
    require(make_url(context['databaseUrl']).database == context['database'], 'Test database mismatch')
    require(context.get('state') in ('RUNNING', 'STOPPED'), 'Prepare a new isolated validation first')
    state = ROOT / 'runtime/services.local.json'
    if context['state'] == 'RUNNING':
        current = json.loads(state.read_text(encoding='utf-8-sig'))
        require(current == context['services'], 'Managed services changed; refusing to target another application instance')
    else:
        require(action in ('restart', 'finish'), 'Start the isolated services with restart before running commands')
        require(not state.exists(), 'Another application instance is present; stop it before continuing')


def services(action, context=None):
    env = context_env(context) if context else {**os.environ, 'PYTHONUTF8': '1'}
    with (ROOT / f'runtime/audit-services-{action}.log').open('w', encoding='utf-8') as output:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts/services.ps1'), action],
                                cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        print('Service action failed; inspect runtime logs.', flush=True)
        raise RuntimeError('Service action failed')
    print(f'Services {action} completed', flush=True)


def wait_ready(origin='https://localhost:3443'):
    import httpx
    deadline = time.monotonic() + 45
    with httpx.Client(verify=False, timeout=3, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                health = client.get(origin + '/api/health')
                page = client.get(origin)
                if health.status_code == page.status_code == 200:
                    return {'httpsHealth': 200, 'frontendHealth': 200, 'demoMode': health.json()['demo']}
            except httpx.HTTPError:
                pass
            time.sleep(.5)
    raise RuntimeError('Application did not become ready')


async def prepare(network_mode='local'):
    import asyncmy
    from sqlalchemy.engine import make_url
    from app.config import settings
    from backup import backup
    require(settings.demo_mode, 'Audit requires the local demo configuration')
    source = make_url(settings.database_url)
    require(source.host in ('127.0.0.1', 'localhost'), 'This helper supports the local demo MySQL server only')
    require(re.fullmatch(r'[A-Za-z0-9_]+', source.database), 'Unsupported source database identifier')
    for port in (8000, 3000, 3443):
        try:
            with create_connection(('127.0.0.1', port), timeout=.5):
                pass
        except OSError:
            continue
        raise RuntimeError(f'Port {port} is already in use. Stop the application before prepare.')
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(3)
    folder = ROOT / 'runtime/audit' / tag
    evidence = ROOT / ('evidence/validation-' + tag)
    folder.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=True)
    dump = folder / 'source.sql'
    size = backup(dump, str(MYSQL_BIN / 'mysqldump.exe'))
    admin_password = (ROOT / f'runtime/mysql-{source.port or 3306}-admin-password.local').read_text(encoding='utf-8').strip()
    connection = await asyncmy.connect(host=source.host, port=source.port or 3306, user='root', password=admin_password, autocommit=True)
    database = 'realtimeorders_audit_' + tag.replace('-', '_')
    username = 'ro_audit_' + tag[-6:]
    password = secrets.token_hex(24)
    try:
        baseline = await fingerprints(connection, source.database)
        async with connection.cursor() as cursor:
            await cursor.execute(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            await cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', (username, '127.0.0.1', password))
            await cursor.execute(f'GRANT ALL PRIVILEGES ON `{database}`.* TO %s@%s', (username, '127.0.0.1'))
        with dump.open('rb') as stream:
            result = subprocess.run([str(MYSQL_BIN / 'mysql.exe'), '--host=' + source.host, '--port=' + str(source.port or 3306), '--user=root', '--default-character-set=utf8mb4', database],
                                    stdin=stream, env={**os.environ, 'MYSQL_PWD': admin_password}, capture_output=True)
        require(result.returncode == 0, 'Isolated database restore failed; credentials suppressed')
        restored = await fingerprints(connection, database)
        require(baseline == restored, 'Source and restored table fingerprints differ')
        # Old rate windows belong to previous experiments; reset only in this new copy.
        async with connection.cursor() as cursor:
            await cursor.execute(f'DELETE FROM `{database}`.`rate_limit_buckets`')
        upload_dir = folder / 'uploads'
        if Path(settings.upload_dir).is_dir():
            shutil.copytree(settings.upload_dir, upload_dir)
        else:
            upload_dir.mkdir(parents=True)
        context = {'tag': tag, 'sourceDatabase': source.database, 'database': database,
                   'databaseUrl': source.set(username=username, password=password, database=database).render_as_string(hide_password=False),
                   'uploadDir': str(upload_dir), 'runtime': str(folder), 'evidence': str(evidence), 'baseline': baseline,
                   'appSecret': secrets.token_urlsafe(48), 'state': 'PREPARED',
                   **network_values(network_mode)}
        dump_json(CONTEXT, context)
        try:
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            revision = 'unversioned source'
        dump_json(evidence / 'environment.json', {'runId': tag, 'sourceDatabase': source.database, 'testDatabase': database,
                  'mysqlPort': source.port or 3306, 'python': sys.version.split()[0], 'platform': sys.platform,
                  'commit': revision,
                  'backupBytes': size, 'copiedTables': len(restored), 'allInitialTableHashesMatch': True,
                  'topology': 'Single Windows machine, loopback HTTPS/WSS and MySQL/InnoDB; no external SMS/email.'})
    finally:
        await connection.ensure_closed()
    services('start', context)
    ready = wait_ready(context['origin'])
    save_running(context)
    dump_json(evidence / 'startup.json', ready)
    print(json.dumps({'testDatabase': database, 'copiedTables': len(restored), **ready}), flush=True)


async def finish(context):
    import asyncmy
    from app.config import settings
    from sqlalchemy.engine import make_url
    services('stop-app')
    source = make_url(settings.database_url)
    password = (ROOT / f'runtime/mysql-{source.port or 3306}-admin-password.local').read_text(encoding='utf-8').strip()
    connection = await asyncmy.connect(host=source.host, port=source.port or 3306, user='root', password=password, autocommit=True)
    try:
        current = await fingerprints(connection, source.database)
        unchanged = current == context['baseline']
    finally:
        await connection.ensure_closed()
    services('start')
    result = {**wait_ready(network_values()['origin']), 'sourceDatabaseUnchanged': unchanged, 'testDatabaseRetained': context['database']}
    dump_json(Path(context['evidence']) / 'final-startup.json', result)
    context['state'] = 'FINISHED'
    dump_json(CONTEXT, context)
    print(json.dumps(result), flush=True)
    if not unchanged:
        raise RuntimeError('Source DB changed during validation; the normal demo has been restarted. Inspect the evidence.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--network-mode', choices=['local', 'configured'], default=None)
    parser.add_argument('action', choices=['prepare', 'backend', 'browser', 'run', 'restart', 'stop', 'finish'])
    parser.add_argument('--cwd', choices=['root', 'backend', 'frontend'], default='root')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'prepare':
        asyncio.run(prepare(args.network_mode or 'local'))
        return
    context = json.loads(CONTEXT.read_text(encoding='utf-8'))
    check_context(context, args.action)
    if args.action in ('run', 'backend', 'browser'):
        if args.action == 'backend':
            command = [str(PYTHON), '-m', 'pytest', '-q', '--junitxml=' + str(Path(context['evidence']) / 'integration.xml')]
            cwd = ROOT / 'backend'
        elif args.action == 'browser':
            command = ['npx.cmd', 'playwright', 'test']
            cwd = ROOT / 'frontend'
        else:
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            command = [str(PYTHON) if item == '{python}' else item for item in command]
            if not command:
                parser.error('run requires a command after --')
            cwd = ROOT if args.cwd == 'root' else ROOT / args.cwd
        result = subprocess.run(command, cwd=cwd, env=context_env(context))
        sys.exit(result.returncode)
    elif args.action == 'restart':
        if context['state'] == 'RUNNING':
            services('stop-app')
            context['state'] = 'STOPPED'
            dump_json(CONTEXT, context)
        if args.network_mode is not None:
            context.update(network_values(args.network_mode))
            dump_json(CONTEXT, context)
        services('start', context)
        save_running(context)
        print(json.dumps(wait_ready(context.get('origin', 'https://localhost:3443'))), flush=True)
    elif args.action == 'stop':
        services('stop-app')
        context['state'] = 'STOPPED'
        dump_json(CONTEXT, context)
    elif args.action == 'finish':
        asyncio.run(finish(context))


if __name__ == '__main__':
    main()
