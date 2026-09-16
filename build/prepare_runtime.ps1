param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + [IO.Path]::PathSeparator + $env:PSModulePath
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Cache = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Path $Cache -Force | Out-Null
function Install-Archive([string]$Name, [string]$Hash, [string[]]$Sources, [string]$Target) {
    $Archive = Join-Path $Cache $Name
    if (-not (Test-Path -LiteralPath $Archive) -or (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $Hash) {
        $Success = $false
        foreach ($Url in $Sources) {
            try {
                Invoke-WebRequest -Uri $Url -UseBasicParsing -OutFile ($Archive + '.tmp') -TimeoutSec 120
                if ((Get-FileHash -LiteralPath ($Archive + '.tmp') -Algorithm SHA256).Hash -ne $Hash) { throw 'Runtime SHA256 mismatch' }
                Move-Item -LiteralPath ($Archive + '.tmp') -Destination $Archive -Force
                $Success = $true
                break
            } catch { Write-Warning "Runtime source failed: $Url" }
        }
        if (-not $Success) { throw "No verified runtime available: $Name" }
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Target -Force
    Write-Output "VERIFIED_RUNTIME $Name $Hash"
}
$PythonName = 'python-3.13.14-embed-amd64.zip'
Install-Archive $PythonName '90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907' @(
    "https://mirrors.huaweicloud.com/python/3.13.14/$PythonName",
    "https://mirrors.aliyun.com/python-release/windows/$PythonName",
    "https://mirrors.nju.edu.cn/python/3.13.14/$PythonName",
    "https://www.python.org/ftp/python/3.13.14/$PythonName"
) (Join-Path $Destination 'python')
$PythonRoot = Join-Path $Destination 'python'
Copy-Item -LiteralPath (Join-Path $PythonRoot 'python.exe') -Destination (Join-Path $PythonRoot 'poe_python.exe') -Force
[IO.File]::WriteAllLines((Join-Path $PythonRoot 'python313._pth'), @('python313.zip','.','Lib/site-packages'), [Text.Encoding]::ASCII)
$DotnetName = 'dotnet-runtime-8.0.28-win-x64.zip'
Install-Archive $DotnetName 'd525978009270857c7a3ff0ce7f5d1244ae547dd34482e09738fea49814f76cf' @(
    "https://dotnetcli.azureedge.net/dotnet/Runtime/8.0.28/$DotnetName",
    "https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.28/$DotnetName"
) (Join-Path $Destination 'dotnet-runtime')
& (Join-Path $PythonRoot 'poe_python.exe') -c 'import sys,ssl,zipfile,json,urllib.request; print(sys.version)'
if ($LASTEXITCODE -ne 0) { throw 'Python runtime check failed' }
& (Join-Path $Destination 'dotnet-runtime/dotnet.exe') --list-runtimes
if ($LASTEXITCODE -ne 0) { throw '.NET runtime check failed' }
