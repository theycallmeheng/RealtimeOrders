param([string]$Address='', [switch]$LocalOnly)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8='1'
if($LocalOnly){
    & $pythonPath (Join-Path $PSScriptRoot 'configure_lan.py') --local
}else{
    if(-not $Address){
        $candidates=@(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'} | ForEach-Object {$_.IPv4Address.IPAddress})
        if($candidates.Count -ne 1){throw 'Specify -Address with the server private IPv4 address when multiple routes are present.'}
        $Address=$candidates[0]
    }
    $assigned=@(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $Address -ErrorAction SilentlyContinue | Where-Object {$_.AddressState -eq 'Preferred'})
    if($assigned.Count -ne 1){throw 'The selected IPv4 address is not assigned to one active local interface.'}
    & $pythonPath (Join-Path $PSScriptRoot 'configure_lan.py') --address $Address
}
if($LASTEXITCODE -ne 0){throw 'Network configuration failed'}
Write-Host 'Restart project services to apply the profile. See docs\LAN.md.'
