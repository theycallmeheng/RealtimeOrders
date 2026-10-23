"""Create only the project schema/user on an existing MySQL server."""
import argparse
import asyncio
import getpass
import json
import re
import secrets
from pathlib import Path

import asyncmy
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


async def create_project_database(connection, database):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', database):
        raise RuntimeError('Invalid database name')
    async with connection.cursor() as cursor:
        await cursor.execute('SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (database,))
        if (await cursor.fetchone())[0]:
            raise RuntimeError('Target database already exists; no existing data was changed')
        username = 'realtimeorders_' + secrets.token_hex(4)
        password = secrets.token_hex(24)
        await cursor.execute(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        await cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', (username, '127.0.0.1', password))
        await cursor.execute(f'GRANT ALL ON `{database}`.* TO %s@%s', (username, '127.0.0.1'))
    return username, password


def database_url(host, port, database, username, password):
    return URL.create('mysql+asyncmy', username=username, password=password, host=host,
                      port=port, database=database, query={'charset': 'utf8mb4'}).render_as_string(hide_password=False)


async def main(args):
    env = ROOT / '.env'
    if env.exists():
        print('Da co .env; khong ghi de. Dung migrate_mysql.py neu can chuyen database.')
        return
    password = (Path(args.admin_password_file).read_text(encoding='utf-8-sig').strip()
                if args.admin_password_file else getpass.getpass('MySQL administrator password: '))
    connection = await asyncmy.connect(host=args.host, port=args.port, user=args.admin_user,
                                       password=password, connect_timeout=5)
    try:
        username, app_password = await create_project_database(connection, args.database)
    finally:
        await connection.ensure_closed()
    url = database_url(args.host, args.port, args.database, username, app_password)
    env.write_text(f'DATABASE_URL={url}\nAPP_SECRET={secrets.token_hex(32)}\nAPP_ORIGIN=https://localhost:3443\n'
                   'COOKIE_SECURE=true\nDEMO_MODE=true\nSMS_PROVIDER=demo\nEMAIL_PROVIDER=demo\n', encoding='utf-8')
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    (runtime / 'mysql.local.json').write_text(json.dumps({'managed': False, 'host': args.host,
                'port': args.port, 'database': args.database}, indent=2), encoding='utf-8')
    print(f'Da tao {args.database} tren {args.host}:{args.port}. Mat khau quan tri MySQL khong thay doi.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--database', default='realtimeorders')
    parser.add_argument('--admin-user', default='root')
    parser.add_argument('--admin-password-file')
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        code = error.args[0] if isinstance(error, asyncmy.errors.MySQLError) and error.args else type(error).__name__
        print(f'Khong tao duoc database (error {code}); khong in thong tin dang nhap.')
        if type(error) is RuntimeError:
            print(str(error))
        raise SystemExit(1)
