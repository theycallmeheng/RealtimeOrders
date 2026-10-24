param([ValidateSet('start','stop','stop-app','status')][string]$Action='start')
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath=Join-Path $projectRoot 'runtime'
$statePath=Join-Path $runtimePath 'services.local.json'
$pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8='1'
$env:NEXT_TELEMETRY_DISABLED='1'
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null

function Test-OwnedProcess($entry){
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.pid)" -ErrorAction SilentlyContinue
    return $process -and $process.CreationDate.ToUniversalTime().Ticks.ToString() -eq $entry.created -and $process.CommandLine -like "*$($entry.marker)*"
}

if($Action -in @('stop','stop-app')){
    $retained=@()
    if(Test-Path -LiteralPath $statePath){
        $entries=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $ordered=@($entries);[array]::Reverse($ordered)
        foreach($entry in $ordered){
            if($Action -eq 'stop-app' -and $entry.name -eq 'mysql'){
                if(Test-OwnedProcess $entry){$retained+= $entry}
                continue
            }
            if(Test-OwnedProcess $entry){
                if($entry.name -eq 'mysql'){
                    $db=Get-Content -LiteralPath (Join-Path $runtimePath 'mysql.local.json') -Raw | ConvertFrom-Json
                    $passwordPath=Join-Path $runtimePath 'root-password.local'
                    if(-not(Test-Path -LiteralPath $passwordPath)){Write-Host 'MySQL van chay: thieu file mat khau root cuc bo.';continue}
                    $env:MYSQL_PWD=(Get-Content -LiteralPath $passwordPath -Raw).Trim()
                    try{& (Join-Path (Split-Path $db.binary) 'mysqladmin.exe') '--host=127.0.0.1' "--port=$($db.port)" '--user=root' 'shutdown'}finally{Remove-Item Env:MYSQL_PWD}
                    continue
                }
                # Only descendants of a verified project-owned launcher are included.
                $children=Get-CimInstance Win32_Process -Filter "ParentProcessId=$($entry.pid)" -ErrorAction SilentlyContinue
                foreach($child in $children){Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue}
                Stop-Process -Id $entry.pid -ErrorAction SilentlyContinue
            }
        }
        if($retained.Count -gt 0){ConvertTo-Json -InputObject @($retained) | Set-Content -LiteralPath $statePath -Encoding utf8}
        else{Remove-Item -LiteralPath $statePath}
    }
    Write-Host 'Da dung cac dich vu do project khoi tao.'
    exit
}
if($Action -eq 'status'){
    if(Test-Path -LiteralPath $statePath){$parsed=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json;$result=foreach($entry in $parsed){[pscustomobject]@{Service=$entry.name;Running=(Test-OwnedProcess $entry);PID=$entry.pid}};$result | Format-Table -AutoSize | Out-Host}
    else{Write-Host 'Chua co dich vu duoc script quan ly.'}
    exit
}
$existingOwned=@()
if(Test-Path -LiteralPath $statePath){
    $oldEntries=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $existingOwned=@(foreach($entry in $oldEntries){if(Test-OwnedProcess $entry){$entry}})
    $appEntries=@($existingOwned | Where-Object { $_.name -ne 'mysql' })
    if($appEntries.Count -eq 3){Write-Host 'RealtimeOrders dang chay: https://localhost:3443';exit}
    if($appEntries.Count -gt 0){throw 'Mot so dich vu con chay. Chay services.ps1 stop truoc.'}
    if($existingOwned.Count -eq 0){Remove-Item -LiteralPath $statePath}
}
if(-not(Test-Path -LiteralPath $pythonPath)){throw 'Chay scripts\setup.ps1 truoc.'}
foreach($port in @(8000,3000,3443)){
    if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw "Cong $port dang duoc su dung. Kiem tra dich vu dang chay truoc khi start."}
}
$entries=[System.Collections.Generic.List[object]]::new()
foreach($entry in $existingOwned){$entries.Add($entry)}
function Start-Owned($name,$exe,$arguments,$directory,$marker){
    $process=Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath "$name.log") -RedirectStandardError (Join-Path $runtimePath "$name-error.log")
    Start-Sleep -Milliseconds 400
    $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    if(-not $info){throw "Dich vu $name khong khoi dong. Xem runtime\$name-error.log"}
    $entries.Add(@{name=$name;pid=$process.Id;created=$info.CreationDate.ToUniversalTime().Ticks.ToString();marker=$marker})
    $entries | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}
# MySQL may already be running from setup or Docker. Never stop a foreign service.
$mysqlConfig=Join-Path $runtimePath 'mysql.local.json'
if(Test-Path -LiteralPath $mysqlConfig){
    $db=Get-Content -LiteralPath $mysqlConfig -Raw | ConvertFrom-Json
    $listener=Get-NetTCPConnection -LocalPort $db.port -State Listen -ErrorAction SilentlyContinue
    if($db.managed -eq $false){
        if(-not $listener){throw "MySQL co san chua chay tai cong $($db.port). Khoi dong dich vu MySQL trong Windows."}
        Write-Host "Su dung MySQL co san tai 127.0.0.1:$($db.port); project khong dung dich vu nay."
    }
    elseif(-not $listener){Start-Owned 'mysql' $db.binary @('--no-defaults',"--datadir=`"$($db.dataDir)`"",'--bind-address=127.0.0.1',"--port=$($db.port)",'--mysqlx=OFF','--console') (Split-Path $db.binary) $db.dataDir;Start-Sleep -Seconds 2}
}
Start-Owned 'backend' $pythonPath @('-m','uvicorn','app.main:app','--loop','app.event_loop:new_event_loop','--host','127.0.0.1','--port','8000','--ws-max-size','65536','--ws-max-queue','16','--ws-per-message-deflate','false','--no-access-log','--log-level','warning') (Join-Path $projectRoot 'backend') 'uvicorn'
$nodePath=(Get-Command node.exe).Source
$nextCli=Join-Path $projectRoot 'frontend\node_modules\next\dist\bin\next'
Start-Owned 'frontend' $nodePath @("`"$nextCli`"",'start','--hostname','127.0.0.1','--port','3000') (Join-Path $projectRoot 'frontend') $nextCli
Start-Owned 'proxy' $nodePath @("`"$(Join-Path $projectRoot 'scripts\proxy.mjs')`"") $projectRoot 'proxy.mjs'
Write-Host 'RealtimeOrders: https://localhost:3443'
Write-Host 'Tai khoan demo: runtime\demo-accounts.local.json'
