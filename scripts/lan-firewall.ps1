param([switch]$MakePrivate,[switch]$Remove)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath=Join-Path $projectRoot 'runtime'
$resultPath=Join-Path $runtimePath 'lan-firewall.local.json'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run this script from PowerShell as Administrator.'}
$sha=[Security.Cryptography.SHA256]::Create()
try{$rootHash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))).Replace('-','').Substring(0,12)}finally{$sha.Dispose()}
$ruleName='RealtimeOrders-LAN-' + $rootHash + '-3443'
try{
    $existing=Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if($existing -and $existing.Group -ne 'RealtimeOrders LAN'){throw 'A firewall rule with this name belongs to another application.'}
    if($Remove){
        if($existing){Remove-NetFirewallRule -Name $ruleName}
        @{success=$true;removed=$true;ruleName=$ruleName} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
        exit
    }
    $config=Get-Content -LiteralPath (Join-Path $runtimePath 'network.local.json') -Raw | ConvertFrom-Json
    if($config.mode -ne 'lan' -or $config.origin -ne ('https://' + $config.address + ':3443')){throw 'Configure LAN first.'}
    $ip=[Net.IPAddress]::Parse($config.address)
    $bytes=$ip.GetAddressBytes()
    $private=$ip.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168))
    if(-not $private){throw 'Only private LAN IPv4 addresses are supported.'}
    $assigned=@(Get-NetIPAddress -IPAddress $config.address -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.AddressState -eq 'Preferred'})
    if($assigned.Count -ne 1){throw 'The configured LAN IPv4 is no longer assigned to this server.'}
    $profile=Get-NetConnectionProfile -InterfaceIndex $assigned[0].InterfaceIndex
    if($profile.NetworkCategory -ne 'Private'){
        if(-not $MakePrivate){throw 'Network profile is not Private. Review the network before using -MakePrivate.'}
        Set-NetConnectionProfile -InterfaceIndex $profile.InterfaceIndex -NetworkCategory Private
    }
    $nodePath=(Get-Command node.exe).Source
    if($existing){Remove-NetFirewallRule -Name $ruleName}
    New-NetFirewallRule -Name $ruleName -DisplayName 'RealtimeOrders LAN HTTPS 3443' -Group 'RealtimeOrders LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3443 -LocalAddress $config.address -RemoteAddress LocalSubnet -InterfaceAlias $assigned[0].InterfaceAlias -Profile Private -Program $nodePath -EdgeTraversalPolicy Block | Out-Null
    @{success=$true;ruleName=$ruleName;address=$config.address;port=3443;profile='Private';remoteAddress='LocalSubnet';interfaceIndex=$profile.InterfaceIndex} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    Write-Host ('LAN firewall ready: ' + $config.origin + ' (Private / LocalSubnet)')
}catch{
    @{success=$false;ruleName=$ruleName;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    throw
}
