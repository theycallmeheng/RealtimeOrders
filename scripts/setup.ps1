param([string]$MySQLBinary='C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe',[string]$MySQLDataDirectory='')
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8='1';$env:NEXT_TELEMETRY_DISABLED='1'
if(-not(Test-Path -LiteralPath '.venv\Scripts\python.exe')){python -m venv .venv}
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
if($LASTEXITCODE -ne 0){throw 'Khong cai duoc backend dependencies'}
New-Item -ItemType Directory -Force -Path runtime | Out-Null
if(-not(Test-Path -LiteralPath '.env')){
    if(-not(Test-Path -LiteralPath $MySQLBinary)){throw 'Can MySQL 8.0.46+ hoac 8.4; truyen -MySQLBinary duong dan mysqld.exe'}
    $port=3307
    if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw 'Cong 3307 dang dung. Cau hinh .env cho database rieng, khong tu ghi vao DB dang co.'}
    $dataDir=if($MySQLDataDirectory){[IO.Path]::GetFullPath($MySQLDataDirectory)}else{Join-Path $projectRoot 'runtime\mysql-data'}
    if($dataDir -match '[^\x00-\x7F]'){
        $asciiParent=$projectRoot
        while($asciiParent -match '[^\x00-\x7F]'){$asciiParent=Split-Path $asciiParent -Parent}
        $dataDir=Join-Path $asciiParent 'RealtimeOrders-data\mysql-data'
        Write-Host "MySQL 8.0 Windows: dung thu muc du lieu ASCII $dataDir"
    }
    if(Test-Path -LiteralPath $dataDir){throw 'Data directory da ton tai. Khong khoi tao lai. Phuc hoi .env tu ban luu.'}
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    Push-Location -LiteralPath (Split-Path $MySQLBinary)
    try{& $MySQLBinary --no-defaults --initialize-insecure "--datadir=$dataDir" --console}finally{Pop-Location}
    if($LASTEXITCODE -ne 0){throw 'Khong khoi tao duoc MySQL'}
    @{binary=$MySQLBinary;dataDir=$dataDir;port=$port} | ConvertTo-Json | Set-Content -LiteralPath runtime\mysql.local.json -Encoding utf8
    Start-Process -FilePath $MySQLBinary -ArgumentList @('--no-defaults',"--datadir=`"$dataDir`"",'--bind-address=127.0.0.1','--port=3307','--mysqlx=OFF','--console') -WindowStyle Hidden -WorkingDirectory (Split-Path $MySQLBinary)
    Start-Sleep -Seconds 3
    & '.\.venv\Scripts\python.exe' scripts\bootstrap_db.py
    if($LASTEXITCODE -ne 0){throw 'Khong tao duoc database; kiem tra runtime va MySQL'}
}
Push-Location backend
try{& '..\.venv\Scripts\python.exe' -m alembic upgrade head;if($LASTEXITCODE -ne 0){throw 'Migration failed'};& '..\.venv\Scripts\python.exe' seed.py;if($LASTEXITCODE -ne 0){throw 'Seed failed'}}finally{Pop-Location}
& '.\.venv\Scripts\python.exe' scripts\create_cert.py
Push-Location frontend
try{npm ci;if($LASTEXITCODE -ne 0){throw 'npm ci failed'};npm run build;if($LASTEXITCODE -ne 0){throw 'Frontend build failed'}}finally{Pop-Location}
Write-Host 'Da cai xong. Chay: powershell -ExecutionPolicy Bypass -File scripts\services.ps1 start'
