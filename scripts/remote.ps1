param([ValidateSet('start','stop','status')][string]$Action='start')
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath=Join-Path $projectRoot 'runtime'
$statePath=Join-Path $runtimePath 'tunnel.local.json'
$binary=Join-Path $runtimePath 'tools\cloudflared.exe'
$networkPath=Join-Path $runtimePath 'network.local.json'
$env:PYTHONUTF8='1'
function Owned($entry){
    if(-not $entry){return $false}
    $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.pid)" -ErrorAction SilentlyContinue
    return $info -and $info.CreationDate.ToUniversalTime().Ticks.ToString() -eq $entry.created -and $info.ExecutablePath -eq $binary
}
$state=$null
if(Test-Path -LiteralPath $statePath){$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json}
if($Action -eq 'status'){
    if(Owned $state){Write-Host ('Tunnel running: '+$state.origin)}else{Write-Host 'Tunnel is stopped.'}
    exit
}
if($Action -eq 'stop'){
    if(Owned $state){Stop-Process -Id $state.pid}
    & (Join-Path $PSScriptRoot 'services.ps1') 'stop-app'
    if($state -and $state.previousProfile){
        $state.previousProfile | ConvertTo-Json | Set-Content -LiteralPath $networkPath -Encoding utf8
    }else{& node.exe (Join-Path $PSScriptRoot 'configure-remote.mjs') '--local';if($LASTEXITCODE -ne 0){throw 'Cannot restore local profile'}}
    if(Test-Path -LiteralPath $statePath){Remove-Item -LiteralPath $statePath}
    & (Join-Path $PSScriptRoot 'services.ps1') 'start'
    Write-Host 'Public tunnel stopped; previous network profile restored.'
    exit
}
if(Owned $state){
    Write-Host ('Tunnel already running: '+$state.origin)
    & (Join-Path $PSScriptRoot 'services.ps1') 'start'
    exit
}
if(-not(Test-Path -LiteralPath $binary)){throw 'Missing runtime\tools\cloudflared.exe. Run scripts\install-cloudflared.ps1 first.'}
if(Test-Path Env:REALTIMEORDERS_NETWORK_MODE){Remove-Item Env:REALTIMEORDERS_NETWORK_MODE}
$previousProfile=if(Test-Path -LiteralPath $networkPath){Get-Content -LiteralPath $networkPath -Raw | ConvertFrom-Json}else{@{mode='local';origin='https://localhost:3443'}}
if($previousProfile.mode -eq 'remote'){$previousProfile=@{mode='local';origin='https://localhost:3443'}}
& (Join-Path $PSScriptRoot 'services.ps1') 'stop-app'
$process=$null
try{
    $logPath=Join-Path $runtimePath 'tunnel-error.log'
    # TLS verification bypass is only for the self-signed loopback hop, never the public HTTPS connection.
    $process=Start-Process -FilePath $binary -ArgumentList @('--no-autoupdate','tunnel','--url','https://127.0.0.1:3443','--no-tls-verify','--protocol','http2') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'tunnel.log') -RedirectStandardError $logPath
    $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    if(-not $info){throw 'Tunnel process did not start'}
    $entry=@{pid=$process.Id;created=$info.CreationDate.ToUniversalTime().Ticks.ToString();previousProfile=$previousProfile;origin=''}
    $entry | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
    $origin=''
    for($i=0;$i -lt 60;$i++){
        if($process.HasExited){throw 'cloudflared exited; see runtime\tunnel-error.log'}
        if(Test-Path -LiteralPath $logPath){
            $logText=Get-Content -LiteralPath $logPath -Raw
            if($logText -match 'https://[a-z0-9-]+\.trycloudflare\.com'){$origin=$Matches[0];break}
        }
        Start-Sleep -Milliseconds 500
    }
    if(-not $origin){throw 'Tunnel hostname was not issued within 30 seconds'}
    & node.exe (Join-Path $PSScriptRoot 'configure-remote.mjs') '--origin' $origin
    if($LASTEXITCODE -ne 0){throw 'Remote profile configuration failed'}
    $entry.origin=$origin
    $entry | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
    & (Join-Path $PSScriptRoot 'services.ps1') 'start'
    Write-Host ('Public RealtimeOrders: '+$origin)
    Write-Host 'Keep this PC awake and online. Use scripts\remote.ps1 stop to close public access.'
}catch{
    if($process -and (Owned $entry)){Stop-Process -Id $process.Id -ErrorAction SilentlyContinue}
    & (Join-Path $PSScriptRoot 'services.ps1') 'stop-app'
    $previousProfile | ConvertTo-Json | Set-Content -LiteralPath $networkPath -Encoding utf8
    if(Test-Path -LiteralPath $statePath){Remove-Item -LiteralPath $statePath}
    & (Join-Path $PSScriptRoot 'services.ps1') 'start'
    throw
}
