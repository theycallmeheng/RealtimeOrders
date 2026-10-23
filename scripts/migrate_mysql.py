"""Copy the project to an existing local MySQL. Never drop/replace a schema.

The source stays as a backup. Credentials are read from an ignored local file;
subprocess passwords use the environment, never command arguments or output.
"""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import asyncmy
import httpx
from dotenv import dotenv_values, set_key
from sqlalchemy.engine import make_url

from bootstrap_db import create_project_database, database_url

ROOT = Path(__file__).resolve().parents[1]


def services(action):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(ROOT / 'scripts/services.ps1'), action], cwd=ROOT,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=60)
    if result.returncode:
        raise RuntimeError('Service action failed: ' + action)


async def connect(url):
    return await asyncmy.connect(host=url.host or '127.0.0.1', port=url.port or 3306,
                                 user=url.username, password=url.password or '', db=url.database,
                                 charset='utf8mb4', autocommit=True, connect_timeout=5)


def canonical(value):
    if isinstance(value, bytes):
        return {'binary': value.hex()}
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


async def fingerprint(connection):
    result = {}
    async with connection.cursor() as cursor:
        await cursor.execute("SET time_zone='+00:00'")
        await cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
        tables = [row[0] for row in await cursor.fetchall()]
        for table in sorted(tables):
            quoted = '`' + table.replace('`', '``') + '`'
            await cursor.execute('SELECT * FROM ' + quoted)
            rows = await cursor.fetchall()
            encoded = sorted(json.dumps(row, default=canonical, ensure_ascii=False, separators=(',', ':')).encode() for row in rows)
            checksum = hashlib.sha256()
            for row in encoded:
                checksum.update(len(row).to_bytes(8, 'big'))
                checksum.update(row)
            result[table] = {'rows': len(rows), 'sha256': checksum.hexdigest()}
    return result


async def main(args):
    source_config = (ROOT / '.env').read_bytes()
    source_url = make_url(dotenv_values(ROOT / '.env')['DATABASE_URL'])
    if source_url.host not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('Only local source migration is supported')
    if source_url.port == args.port:
        raise RuntimeError('The source already uses the target port; no migration performed')
    password_path = ROOT / args.admin_password_file
    admin_password = password_path.read_text(encoding='utf-8-sig').strip()
    destination = await asyncmy.connect(host='127.0.0.1', port=args.port, user=args.admin_user,
                                         password=admin_password, connect_timeout=5, autocommit=True)
    async with destination.cursor() as cursor:
        await cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA')
        schemas_before = {row[0] for row in await cursor.fetchall()}
        if source_url.database in schemas_before:
            await destination.ensure_closed()
            raise RuntimeError('Target database already exists; no data was changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir = ROOT / 'runtime/backups' / ('move-to-' + str(args.port) + '-' + stamp)
    backup_dir.mkdir(parents=True)
    (backup_dir / 'source-env.local').write_bytes(source_config)
    mysql_config = ROOT / 'runtime/mysql.local.json'
    old_mysql_config = mysql_config.read_bytes() if mysql_config.exists() else None
    if old_mysql_config is not None:
        (backup_dir / 'mysql-config.local.json').write_bytes(old_mysql_config)
    source = None
    copied = None
    paused = False
    switched = False
    completed = False
    try:
        print('Pausing application writers; the source MySQL stays available.', flush=True)
        services('stop-app')
        paused = True
        source = await connect(source_url)
        before = await fingerprint(source)
        dump = backup_dir / (source_url.database + '.sql')
        binary = Path(args.mysql_bin)
        env = {**os.environ, 'MYSQL_PWD': source_url.password or ''}
        command = [str(binary / 'mysqldump.exe'), '--host=' + source_url.host,
                   '--port=' + str(source_url.port or 3306), '--user=' + source_url.username,
                   '--single-transaction', '--hex-blob', '--no-tablespaces', '--set-gtid-purged=OFF',
                   '--column-statistics=0', source_url.database]
        with dump.open('wb') as output:
            dumped = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, env=env)
        if dumped.returncode:
            raise RuntimeError('Source backup failed')
        username, app_password = await create_project_database(destination, source_url.database)
        env = {**os.environ, 'MYSQL_PWD': admin_password}
        with dump.open('rb') as input_file:
            imported = subprocess.run([str(binary / 'mysql.exe'), '--host=127.0.0.1',
                    '--port=' + str(args.port), '--user=' + args.admin_user, '--default-character-set=utf8mb4',
                    source_url.database], stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if imported.returncode:
            raise RuntimeError('Target import failed; source/configuration retained')
        new_url = database_url('127.0.0.1', args.port, source_url.database, username, app_password)
        copied = await connect(make_url(new_url))
        after = await fingerprint(copied)
        if before != after or before != await fingerprint(source):
            raise RuntimeError('Table fingerprints differ; source/configuration retained')
        async with destination.cursor() as cursor:
            await cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA')
            schemas_after = {row[0] for row in await cursor.fetchall()}
        if schemas_after != schemas_before | {source_url.database}:
            raise RuntimeError('Unexpected schema list change')
        (backup_dir / 'transfer-validation.local.json').write_text(json.dumps(
            {'tables': before, 'allTableHashesMatch': True, 'sourcePort': source_url.port,
             'targetPort': args.port, 'originalSchemasPreserved': True}, indent=2), encoding='utf-8')
        await source.ensure_closed()
        source = None
        print(f'All {len(before)} tables match. Switching the application to port {args.port}.', flush=True)
        services('stop')
        switched = True
        set_key(str(ROOT / '.env'), 'DATABASE_URL', new_url, quote_mode='never')
        mysql_config.write_text(json.dumps({'managed': False, 'host': '127.0.0.1', 'port': args.port,
                             'database': source_url.database, 'serviceName': 'MySQL80'}, indent=2), encoding='utf-8')
        services('start')
        ready = False
        with httpx.Client(verify=False, trust_env=False, timeout=3) as client:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                try:
                    ready = client.get('https://localhost:3443/api/health').status_code == 200 and client.get('https://localhost:3443').status_code == 200
                except httpx.HTTPError:
                    ready = False
                if ready:
                    break
                await asyncio.sleep(0.5)
        if not ready:
            raise RuntimeError('Application health check failed')
        evidence = {'timestampUtc': datetime.now(timezone.utc).isoformat(), 'database': source_url.database,
                    'sourcePort': source_url.port or 3306, 'targetPort': args.port, 'tableCount': len(before),
                    'tables': before, 'allTableHashesMatch': True, 'originalSchemasPreserved': True,
                    'applicationHealth': 200, 'frontendHealth': 200, 'targetMySQLManagedByProject': False,
                    'sourceBackupRetained': True}
        (ROOT / 'evidence/mysql-port-migration.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        completed = True
        print(json.dumps({k: evidence[k] for k in ('database', 'sourcePort', 'targetPort', 'tableCount', 'allTableHashesMatch', 'applicationHealth', 'frontendHealth')}), flush=True)
    finally:
        await destination.ensure_closed()
        if source is not None:
            await source.ensure_closed()
        if copied is not None:
            await copied.ensure_closed()
        if paused and not completed:
            if switched:
                services('stop')
                (ROOT / '.env').write_bytes(source_config)
                if old_mysql_config is not None:
                    mysql_config.write_bytes(old_mysql_config)
                elif mysql_config.exists():
                    mysql_config.unlink()
            services('start')
            print('Migration not completed; source application configuration restored.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--admin-user', default='root')
    parser.add_argument('--admin-password-file', default='runtime/mysql-3306-admin-password.local')
    parser.add_argument('--mysql-bin', default=r'C:\Program Files\MySQL\MySQL Server 8.0\bin')
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        code = error.args[0] if isinstance(error, asyncmy.errors.MySQLError) and error.args else type(error).__name__
        print(f'Migration stopped (error {code}). Existing databases are not dropped. Credentials suppressed.')
        if type(error) is RuntimeError:
            print(str(error))
        sys.exit(1)
