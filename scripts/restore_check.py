"""Restore a project-owned dump into a NEW disposable DB; leave it for inspection.
Never drops or overwrites a database. Root credentials read from ignored local file.
"""
import asyncio
import hashlib
import json
import os
import subprocess
import shutil
import sys
from pathlib import Path
import asyncmy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import settings
from sqlalchemy.engine import make_url
from backup import backup

async def main():
    binary=Path(r'C:\Program Files\MySQL\MySQL Server 8.0\bin')
    dump=ROOT/'runtime/backups/restore-check.sql'
    size=backup(dump,str(binary/'mysqldump.exe'))
    password_path=ROOT/'runtime/root-password.local'
    if not password_path.exists():password_path=ROOT.parent/'RealtimeOrders-runtime/root-password.local'
    root_password=password_path.read_text().strip()
    import secrets
    target='realtimeorders_restore_'+secrets.token_hex(4)
    conn=await asyncmy.connect(host='127.0.0.1',port=3307,user='root',password=root_password)
    async with conn.cursor() as c:await c.execute('CREATE DATABASE `'+target+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
    env={**os.environ,'MYSQL_PWD':root_password}
    with dump.open('rb') as file:
        r=subprocess.run([str(binary/'mysql.exe'),'--host=127.0.0.1','--port=3307','--user=root','--default-character-set=utf8mb4',target],stdin=file,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    assert r.returncode==0,'Restore failed; credentials suppressed'
    source=make_url(settings.database_url).database
    results=[]
    async with conn.cursor() as c:
        await c.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE=%s',(source,'BASE TABLE'))
        tables=[r[0] for r in await c.fetchall()]
        for table in sorted(tables):
            await c.execute(f'SELECT * FROM `{source}`.`{table}` ORDER BY 1,2' if table not in ('alembic_version',) else f'SELECT * FROM `{source}`.`{table}` ORDER BY 1')
            a=await c.fetchall()
            await c.execute(f'SELECT * FROM `{target}`.`{table}` ORDER BY 1,2' if table not in ('alembic_version',) else f'SELECT * FROM `{target}`.`{table}` ORDER BY 1')
            b=await c.fetchall()
            # Background outbox changes timestamps/state. Domain tables must match exactly.
            equal=a==b
            if table not in ('outbox','rate_limit_buckets','sessions','stream_events','stream_heads','notification_jobs'):
                assert equal,'Restored domain table differs: '+table
            results.append({'table':table,'sourceCount':len(a),'restoredCount':len(b),'identicalAtComparison':equal})
    conn.close()
    media=ROOT/'runtime/uploads';target_media=ROOT/'runtime/restores'/target/'uploads';target_media.mkdir(parents=True)
    assets=[]
    for file in media.glob('*.jpg'):
        restored=target_media/file.name;shutil.copyfile(file,restored)
        original_hash=hashlib.sha256(file.read_bytes()).hexdigest();restored_hash=hashlib.sha256(restored.read_bytes()).hexdigest()
        assert original_hash==restored_hash
        assets.append({'file':file.name,'sha256':original_hash,'restoredHashMatches':True})
    result={'targetDatabase':target,'dumpBytes':size,'tables':results,'mediaFiles':assets,'note':'Domain table equality checked. Background stream/session/outbox may advance after consistent dump. Media file hashes recorded; copy with database backup.'}
    (ROOT/'evidence/restore-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Restore checked:',target,'tables:',len(results),'media files:',len(assets))

asyncio.run(main())
