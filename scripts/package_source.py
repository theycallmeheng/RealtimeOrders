"""Build a reproducible, secret-free source archive. Runtime stays on this PC."""
import hashlib
import json
import os
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALLOWED_DIRS={'backend','frontend','db','docs','scripts','evidence'}
ALLOWED_ROOT={'README.md','AGENTS.md','DESIGN.md','.gitignore','.env.example','Start.cmd','Stop.cmd'}
EXCLUDED={'node_modules','.next','__pycache__','.pytest_cache','runtime','.git','test-results','playwright-report'}

def source_files():
    for name in sorted(ALLOWED_ROOT):
        path=ROOT/name
        if path.is_file():yield path,Path(name)
    for directory in sorted(ALLOWED_DIRS):
        for parent,dirs,files in os.walk(ROOT/directory):
            dirs[:]=sorted(d for d in dirs if d not in EXCLUDED)
            for name in sorted(files):
                path=Path(parent)/name;rel=path.relative_to(ROOT)
                if path.name.endswith(('.pyc','.tsbuildinfo','.pem','.log','.zip')):continue
                if '.local' in path.name:continue
                if path.name.startswith('.env') and path.name!='.env.example':continue
                yield path,rel

def main():
    folder=ROOT/'dist';folder.mkdir(exist_ok=True)
    output=folder/'Nhom17_RealtimeOrders_Source.zip'
    manifest=[]
    files=list(source_files())
    from dotenv import dotenv_values
    secrets=[v.encode() for k,v in dotenv_values(ROOT/'.env').items() if v and len(v)>=12 and any(w in k for w in ('SECRET','TOKEN','PASSWORD','DATABASE_URL'))]
    credentials=ROOT/'runtime/demo-accounts.local.json'
    if credentials.exists():secrets.extend(a['password'].encode() for a in json.loads(credentials.read_text(encoding='utf-8'))['accounts'])
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path,rel in files:
            data=path.read_bytes()
            assert not any(value in data for value in secrets),'A local secret was found in '+rel.as_posix()
            archive.writestr('Nhom17_RealtimeOrders_Source/'+rel.as_posix(),data)
            manifest.append({'file':rel.as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        archive.writestr('Nhom17_RealtimeOrders_Source/SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert all('/runtime/' not in n and '/node_modules/' not in n and not n.endswith('/.env') for n in archive.namelist())
    result={'archive':output.name,'files':len(files),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'excluded':['runtime and database dumps','environment secrets and local credentials','TLS private keys','dependency/build caches']}
    (folder/'package-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
