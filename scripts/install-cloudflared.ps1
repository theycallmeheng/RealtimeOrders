$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$folder=Join-Path $projectRoot 'runtime\tools'
$binary=Join-Path $folder 'cloudflared.exe'
# Pin the official release and verify its SHA-256 before execution.
$version='2026.10.7'
$expected='2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343'
if(Test-Path -LiteralPath $binary){
    if((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected){
        throw 'Existing cloudflared differs from the pinned release; review it before replacing.'
    }
    & $binary '--version'
    exit
}
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$download=Join-Path $folder 'cloudflared.download'
try{
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/cloudflare/cloudflared/releases/download/$version/cloudflared-windows-amd64.exe" -OutFile $download
    if((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected){throw 'cloudflared checksum mismatch'}
    Move-Item -LiteralPath $download -Destination $binary
    & $binary '--version'
}finally{
    if(Test-Path -LiteralPath $download){Remove-Item -LiteralPath $download}
}
