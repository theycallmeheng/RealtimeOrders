"""Consistent MySQL dump, credentials via subprocess environment, never command args."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import settings

def backup(target,binary):
    url=make_url(settings.database_url)
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'MYSQL_PWD':url.password or ''}
    command=[binary,'--host='+url.host,'--port='+str(url.port or 3306),'--user='+url.username,
             '--single-transaction','--hex-blob','--no-tablespaces','--set-gtid-purged=OFF','--column-statistics=0',url.database]
    with target.open('wb') as file:
        result=subprocess.run(command,stdout=file,stderr=subprocess.PIPE,env=env)
    if result.returncode:raise RuntimeError('Backup failed; check MySQL grants and selected database. No credentials logged.')
    return target.stat().st_size

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'runtime/backups/realtimeorders.sql'))
    parser.add_argument('--mysqldump',default=r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe')
    args=parser.parse_args();print('Backup bytes:',backup(args.output,args.mysqldump))
