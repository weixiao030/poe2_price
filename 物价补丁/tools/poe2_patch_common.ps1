function Get-Poe2PatchName {
    param([Parameter(Mandatory = $true)][string]$Name)

    switch ($Name) {
        "InstallerDir" {
            return [string]::Concat(
                [char]0x4E00, [char]0x952E, [char]0x5B89, [char]0x88C5,
                [char]0x7279, [char]0x6B8A, [char]0x8865, [char]0x4E01,
                [char]0x5DE5, [char]0x5177
            )
        }
        "InstallerExe" {
            return [string]::Concat((Get-Poe2PatchName "InstallerDir"), ".exe")
        }
        "LegacyPatchZip" {
            return [string]::Concat([char]0x8865, [char]0x4E01, ".zip")
        }
        "PricePatchZip" {
            return [string]::Concat([char]0x7269, [char]0x4EF7, [char]0x8865, [char]0x4E01, ".zip")
        }
        "RestorePatchZip" {
            return [string]::Concat(
                [char]0x8FD8, [char]0x539F, [char]0x7269, [char]0x4EF7,
                [char]0x8865, [char]0x4E01, ".zip"
            )
        }
        default {
            throw "Unknown patch name: $Name"
        }
    }
}

function Test-Poe2ReleaseMode {
    return ($env:POE2_PATCH_RELEASE -eq "1")
}

function Test-DotNet8Runtime {
    param([string]$DotnetPath)

    if ([string]::IsNullOrWhiteSpace($DotnetPath)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $DotnetPath -PathType Leaf)) {
        return $false
    }

    try {
        $RuntimeLines = & $DotnetPath --list-runtimes 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        return [bool]($RuntimeLines | Where-Object { $_ -match '^Microsoft\.NETCore\.App\s+8\.' } | Select-Object -First 1)
    }
    catch {
        return $false
    }
}

function Get-LocalDotNet8 {
    param([string]$RepoRoot)

    $LocalDotnet = Join-Path $RepoRoot "tools\dotnet-runtime\dotnet.exe"
    if (Test-DotNet8Runtime $LocalDotnet) {
        return $LocalDotnet
    }

    return $null
}

function Get-SystemDotNet8 {
    $Command = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -ne $Command -and (Test-DotNet8Runtime $Command.Source)) {
        return $Command.Source
    }

    return $null
}

function Get-UsableDotNet8 {
    param([string]$RepoRoot)

    $LocalDotnet = Get-LocalDotNet8 -RepoRoot $RepoRoot
    if (-not [string]::IsNullOrWhiteSpace($LocalDotnet)) {
        return $LocalDotnet
    }

    if (Test-Poe2ReleaseMode) {
        return $null
    }

    $SystemDotnet = Get-SystemDotNet8
    if (-not [string]::IsNullOrWhiteSpace($SystemDotnet)) {
        return $SystemDotnet
    }

    return $null
}

function Test-ZipHeader {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    $File = Get-Item -LiteralPath $Path
    if ($File.Length -lt 1048576) {
        return $false
    }

    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Bytes = New-Object byte[] 2
        [void]$Stream.Read($Bytes, 0, 2)
        return ($Bytes[0] -eq 0x50 -and $Bytes[1] -eq 0x4B)
    }
    finally {
        $Stream.Dispose()
    }
}

function Invoke-DownloadWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$Retries = 3
    )

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }

    for ($Attempt = 1; $Attempt -le $Retries; $Attempt++) {
        try {
            if (Test-Path -LiteralPath $OutFile -PathType Leaf) {
                Remove-Item -LiteralPath $OutFile -Force
            }
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 180
            if (-not (Test-ZipHeader $OutFile)) {
                throw "Downloaded file is not a valid runtime zip."
            }
            return
        }
        catch {
            if ($Attempt -ge $Retries) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Min(10, $Attempt * 2))
        }
    }
}

function Install-LocalDotNet8Runtime {
    param([string]$RepoRoot)

    $RuntimeVersion = "8.0.28"
    $RuntimeFile = "dotnet-runtime-$RuntimeVersion-win-x64.zip"
    $DownloadDir = Join-Path $RepoRoot "tools\downloads"
    $RuntimeDir = Join-Path $RepoRoot "tools\dotnet-runtime"
    $ZipPath = Join-Path $DownloadDir $RuntimeFile

    New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

    $Sources = @(
        @{
            Name = "Huawei Cloud mirror"
            Url = "https://mirrors.huaweicloud.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
        },
        @{
            Name = "Huawei Cloud repo mirror"
            Url = "https://repo.huaweicloud.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
        },
        @{
            Name = "Microsoft official fallback"
            Url = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
        }
    )

    foreach ($Source in $Sources) {
        try {
            Write-Host "Download .NET 8 runtime: $($Source.Name)"
            Invoke-DownloadWithRetry -Url $Source.Url -OutFile $ZipPath

            if (Test-Path -LiteralPath $RuntimeDir -PathType Container) {
                Remove-Item -LiteralPath $RuntimeDir -Recurse -Force
            }
            New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
            Expand-Archive -LiteralPath $ZipPath -DestinationPath $RuntimeDir -Force

            $LocalDotnet = Join-Path $RuntimeDir "dotnet.exe"
            if (Test-DotNet8Runtime $LocalDotnet) {
                Write-Host ".NET 8 runtime ready: $LocalDotnet" -ForegroundColor Green
                return $LocalDotnet
            }
            throw "Extracted runtime is not usable."
        }
        catch {
            Write-Warning "$($Source.Name) failed: $($_.Exception.Message)"
        }
    }

    throw "Unable to prepare .NET 8 runtime. Please check your network and run again."
}

function Ensure-DotNet8Runtime {
    param([string]$RepoRoot)

    $Dotnet = Get-UsableDotNet8 -RepoRoot $RepoRoot
    if (-not [string]::IsNullOrWhiteSpace($Dotnet)) {
        return $Dotnet
    }

    if (Test-Poe2ReleaseMode) {
        throw "发布包不完整：缺少可用的 tools\dotnet-runtime\dotnet.exe，请重新打包发布版。"
    }

    Write-Host ""
    Write-Host "==> Prepare .NET 8 runtime" -ForegroundColor Cyan
    return Install-LocalDotNet8Runtime -RepoRoot $RepoRoot
}

function Ensure-PythonRequests {
    param([string]$RepoRoot = "")

    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $LocalPython = Join-Path $RepoRoot "tools\python\python.exe"
        if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
            & $LocalPython -c "import requests, urllib3, ssl" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $LocalPython
            }
        }
    }

    if (Test-Poe2ReleaseMode) {
        throw "发布包不完整：缺少可用的 tools\python\python.exe 或内置 Python 依赖，请重新打包发布版。"
    }

    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        throw "Python is required but was not found in PATH. Please install Python 3 and run again."
    }

    $Python = $PythonCommand.Source
    & $Python -c "import requests, urllib3" 2>$null
    if ($LASTEXITCODE -eq 0) {
        return $Python
    }

    Write-Host ""
    Write-Host "==> Prepare Python requests package" -ForegroundColor Cyan
    & $Python -m pip install -U requests urllib3 -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Python packages requests and urllib3. Please check your network and run again."
    }

    & $Python -c "import requests, urllib3" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Python packages requests and urllib3 are still not usable after install."
    }

    return $Python
}
