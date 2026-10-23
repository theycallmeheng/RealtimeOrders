param([int]$MySQLPort=3306,[string]$MySQLHost='127.0.0.1',[string]$AdminUser='root',[string]$AdminPasswordFile='')
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8='1';$env:NEXT_TELEMETRY_DISABLED='1'
if(-not(Test-Path -LiteralPath '.venv\Scripts\python.exe')){python -m venv .venv}
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
if($LASTEXITCODE -ne 0){throw 'Khong cai duoc backend dependencies'}
New-Item -ItemType Directory -Force -Path runtime | Out-Null
if(-not(Test-Path -LiteralPath '.env')){
    $bootstrapArgs=@('scripts\bootstrap_db.py','--host',$MySQLHost,'--port',"$MySQLPort",'--admin-user',$AdminUser)
    if($AdminPasswordFile){$bootstrapArgs+=@('--admin-password-file',$AdminPasswordFile)}
    & '.\.venv\Scripts\python.exe' @bootstrapArgs
    if($LASTEXITCODE -ne 0){throw 'Khong tao duoc database tren MySQL co san. Kiem tra dich vu va tai khoan quan tri.'}
}
Push-Location backend
try{& '..\.venv\Scripts\python.exe' -m alembic upgrade head;if($LASTEXITCODE -ne 0){throw 'Migration failed'};& '..\.venv\Scripts\python.exe' seed.py;if($LASTEXITCODE -ne 0){throw 'Seed failed'}}finally{Pop-Location}
& '.\.venv\Scripts\python.exe' scripts\create_cert.py
Push-Location frontend
try{npm ci;if($LASTEXITCODE -ne 0){throw 'npm ci failed'};npm run build;if($LASTEXITCODE -ne 0){throw 'Frontend build failed'}}finally{Pop-Location}
Write-Host 'Da cai xong. Chay: powershell -ExecutionPolicy Bypass -File scripts\services.ps1 start'
