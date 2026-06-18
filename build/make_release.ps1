param(
    [switch]$SkipDoc
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$BuildDir = Join-Path $Root "build"
$PatchSourceDir = Join-Path $Root "物价补丁"
$SourceToolsDir = Join-Path $PatchSourceDir "tools"
$ReleaseDir = Join-Path $Root "发布版\物价补丁"
$ReleaseToolsDir = Join-Path $ReleaseDir "tools"
$PayloadDir = Join-Path $BuildDir "payload"
$PayloadZip = Join-Path $BuildDir "payload.zip"
$PayloadEnc = Join-Path $BuildDir "Poe2PatchLauncher\payload.enc"
$LauncherProject = Join-Path $BuildDir "Poe2PatchLauncher\Poe2PatchLauncher.csproj"
$PackerProject = Join-Path $BuildDir "PayloadPacker\PayloadPacker.csproj"
$PublishDir = Join-Path $BuildDir "publish-self"
$DocScript = Join-Path $BuildDir "create_release_doc.py"
$DownloadsDir = Join-Path $BuildDir "downloads"

Set-Location -LiteralPath $Root

function Assert-WithinRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $FullRoot = [System.IO.Path]::GetFullPath($RootPath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $RootPrefix = $FullRoot + [System.IO.Path]::DirectorySeparatorChar
    if ($FullPath -ne $FullRoot -and -not $FullPath.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label path is outside workspace: $FullPath"
    }
    return $FullPath
}

function Remove-TreeSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RootPath
    )

    $FullPath = Assert-WithinRoot -Path $Path -RootPath $RootPath -Label "Remove"
    if (Test-Path -LiteralPath $FullPath) {
        Remove-Item -LiteralPath $FullPath -Recurse -Force
    }
}

function New-DirectorySafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RootPath
    )

    $FullPath = Assert-WithinRoot -Path $Path -RootPath $RootPath -Label "Directory"
    New-Item -ItemType Directory -Force -Path $FullPath | Out-Null
    return $FullPath
}

function Assert-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing $Name`: $Path"
    }
}

function Assert-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Missing $Name`: $Path"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Write-Step {
    param([string]$Text)

    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Test-DotNet8Runtime {
    param([string]$DotnetPath)

    if (-not (Test-Path -LiteralPath $DotnetPath -PathType Leaf)) {
        return $false
    }

    $RuntimeLines = & $DotnetPath --list-runtimes 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return [bool]($RuntimeLines | Where-Object { $_ -match '^Microsoft\.NETCore\.App\s+8\.' } | Select-Object -First 1)
}

function Test-PortablePython {
    param([string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return $false
    }

    & $PythonPath -c "import requests, urllib3, certifi, idna, charset_normalizer, ssl" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 240
}

function Get-DotNet8RuntimeInfo {
    $RuntimeLines = & dotnet --list-runtimes
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet --list-runtimes failed."
    }

    $Runtimes = foreach ($Line in $RuntimeLines) {
        if ($Line -match '^Microsoft\.NETCore\.App\s+([0-9]+\.[0-9]+\.[0-9]+)\s+\[(.+)\]$') {
            [pscustomobject]@{
                Version = [version]$Matches[1]
                VersionText = $Matches[1]
                SharedRoot = $Matches[2]
            }
        }
    }

    $Runtime = $Runtimes |
        Where-Object { $_.Version.Major -eq 8 } |
        Sort-Object Version -Descending |
        Select-Object -First 1

    if ($null -eq $Runtime) {
        throw "No Microsoft.NETCore.App 8.x runtime found on build machine."
    }

    return $Runtime
}

function Prepare-DotNetRuntime {
    param([string]$TargetDir)

    Write-Step "Prepare bundled .NET runtime"
    $SourceRuntimeDir = Join-Path $SourceToolsDir "dotnet-runtime"
    $SourceDotnet = Join-Path $SourceRuntimeDir "dotnet.exe"

    Remove-TreeSafe -Path $TargetDir -RootPath $Root
    New-DirectorySafe -Path $TargetDir -RootPath $Root | Out-Null

    if (Test-DotNet8Runtime $SourceDotnet) {
        Copy-Item -Path (Join-Path $SourceRuntimeDir "*") -Destination $TargetDir -Recurse -Force
    }
    else {
        $DotnetCommand = (Get-Command dotnet -ErrorAction Stop).Source
        $DotnetRoot = Split-Path -Parent $DotnetCommand
        $Runtime = Get-DotNet8RuntimeInfo
        $RuntimeSourceDir = Join-Path $Runtime.SharedRoot $Runtime.VersionText
        $HostFxrRoot = Join-Path $DotnetRoot "host\fxr"
        $HostFxrDir = Get-ChildItem -LiteralPath $HostFxrRoot -Directory |
            Where-Object { $_.Name -match '^8\.' } |
            Sort-Object @{ Expression = { [version]$_.Name }; Descending = $true } |
            Select-Object -First 1

        if ($null -eq $HostFxrDir) {
            throw "No .NET 8 hostfxr folder found: $HostFxrRoot"
        }

        Assert-File -Path $DotnetCommand -Name "dotnet.exe"
        Assert-Directory -Path $RuntimeSourceDir -Name "Microsoft.NETCore.App runtime"

        Copy-Item -LiteralPath $DotnetCommand -Destination (Join-Path $TargetDir "dotnet.exe") -Force
        New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir "host\fxr") | Out-Null
        Copy-Item -LiteralPath $HostFxrDir.FullName -Destination (Join-Path $TargetDir "host\fxr") -Recurse -Force
        New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir "shared\Microsoft.NETCore.App") | Out-Null
        Copy-Item -LiteralPath $RuntimeSourceDir -Destination (Join-Path $TargetDir "shared\Microsoft.NETCore.App") -Recurse -Force

        foreach ($Notice in @("LICENSE.txt", "ThirdPartyNotices.txt")) {
            $NoticePath = Join-Path $DotnetRoot $Notice
            if (Test-Path -LiteralPath $NoticePath -PathType Leaf) {
                Copy-Item -LiteralPath $NoticePath -Destination (Join-Path $TargetDir $Notice) -Force
            }
        }
    }

    $TargetDotnet = Join-Path $TargetDir "dotnet.exe"
    if (-not (Test-DotNet8Runtime $TargetDotnet)) {
        throw "Bundled .NET runtime is not usable: $TargetDotnet"
    }
}

function Prepare-PythonRuntime {
    param([string]$TargetDir)

    Write-Step "Prepare bundled Python runtime"
    $SourcePythonDir = Join-Path $SourceToolsDir "python"
    $SourcePython = Join-Path $SourcePythonDir "python.exe"

    Remove-TreeSafe -Path $TargetDir -RootPath $Root
    New-DirectorySafe -Path $TargetDir -RootPath $Root | Out-Null

    if (Test-PortablePython $SourcePython) {
        Copy-Item -Path (Join-Path $SourcePythonDir "*") -Destination $TargetDir -Recurse -Force
        return
    }

    $PythonVersion = "3.10.6"
    $PythonZipName = "python-$PythonVersion-embed-amd64.zip"
    $PythonZip = Join-Path $DownloadsDir $PythonZipName
    $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"

    if (-not (Test-Path -LiteralPath $PythonZip -PathType Leaf)) {
        Write-Host "Download Python embeddable runtime: $PythonVersion"
        Invoke-Download -Url $PythonUrl -OutFile $PythonZip
    }

    Expand-Archive -LiteralPath $PythonZip -DestinationPath $TargetDir -Force

    $SitePackages = Join-Path $TargetDir "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null
    Set-Content -LiteralPath (Join-Path $TargetDir "python310._pth") -Encoding ASCII -Value @(
        "python310.zip",
        ".",
        "Lib\site-packages",
        "import site"
    )

    $SystemPython = (Get-Command python -ErrorAction Stop).Source
    Invoke-Checked -FilePath $SystemPython -ArgumentList @(
        "-m", "pip", "install",
        "--target", $SitePackages,
        "--upgrade",
        "--no-compile",
        "--disable-pip-version-check",
        "--no-warn-conflicts",
        "--only-binary=:all:",
        "requests==2.32.3",
        "urllib3==2.5.0",
        "certifi==2025.6.15",
        "idna==3.10",
        "charset-normalizer==3.4.2"
    )

    $TargetPython = Join-Path $TargetDir "python.exe"
    if (-not (Test-PortablePython $TargetPython)) {
        throw "Bundled Python runtime is not usable: $TargetPython"
    }
}

function Build-Docs {
    if ($SkipDoc) {
        return
    }

    Write-Step "Build release document"
    Assert-File -Path $DocScript -Name "release doc script"
    Invoke-Checked -FilePath "python" -ArgumentList @($DocScript)
}

function Build-Payload {
    Write-Step "Build encrypted launcher payload"
    Remove-TreeSafe -Path $PayloadDir -RootPath $Root
    New-DirectorySafe -Path $PayloadDir -RootPath $Root | Out-Null

    foreach ($FileName in @(
        "poe2_patch_common.ps1",
        "update_price_patch.ps1",
        "restore_price_patch.ps1",
        "poe2_name_price_patch.py",
        "build_poe2scout_price_patch.py"
    )) {
        $Source = Join-Path $SourceToolsDir $FileName
        Assert-File -Path $Source -Name $FileName
        Copy-Item -LiteralPath $Source -Destination (Join-Path $PayloadDir $FileName) -Force
    }

    if (Test-Path -LiteralPath $PayloadZip -PathType Leaf) {
        Remove-Item -LiteralPath $PayloadZip -Force
    }
    Compress-Archive -Path (Join-Path $PayloadDir "*") -DestinationPath $PayloadZip -Force

    Assert-File -Path $PackerProject -Name "PayloadPacker project"
    Invoke-Checked -FilePath "dotnet" -ArgumentList @(
        "run", "--project", $PackerProject, "--",
        $PayloadZip,
        $PayloadEnc
    )
}

function Publish-Launcher {
    Write-Step "Publish self-contained launcher"
    Remove-TreeSafe -Path $PublishDir -RootPath $Root
    Assert-File -Path $LauncherProject -Name "launcher project"

    Invoke-Checked -FilePath "dotnet" -ArgumentList @(
        "publish",
        $LauncherProject,
        "-c", "Release",
        "-r", "win-x64",
        "-p:SelfContained=true",
        "-p:PublishSingleFile=true",
        "-p:EnableCompressionInSingleFile=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-p:DebugType=None",
        "-p:DebugSymbols=false",
        "-o", $PublishDir
    )
}

function Build-ReleaseFolder {
    Write-Step "Assemble release folder"
    Remove-TreeSafe -Path $ReleaseDir -RootPath $Root
    New-DirectorySafe -Path $ReleaseDir -RootPath $Root | Out-Null
    New-DirectorySafe -Path $ReleaseToolsDir -RootPath $Root | Out-Null

    $LauncherExe = Join-Path $PublishDir "Poe2PatchLauncher.exe"
    Assert-File -Path $LauncherExe -Name "published launcher"
    Copy-Item -LiteralPath $LauncherExe -Destination (Join-Path $ReleaseDir "一键更新物价补丁.exe") -Force
    Copy-Item -LiteralPath $LauncherExe -Destination (Join-Path $ReleaseDir "一键还原物价补丁.exe") -Force

    foreach ($FileName in @("使用文档.docx", "请先看使用文档.txt", "物价补丁.zip", "还原物价补丁.zip")) {
        $Source = Join-Path $PatchSourceDir $FileName
        Assert-File -Path $Source -Name $FileName
        Copy-Item -LiteralPath $Source -Destination (Join-Path $ReleaseDir $FileName) -Force
    }

    $ExtractorDir = Join-Path $SourceToolsDir "GGPKExtractor"
    $SpecialToolDir = Join-Path $PatchSourceDir "一键安装特殊补丁工具"
    Assert-Directory -Path $ExtractorDir -Name "GGPKExtractor"
    Assert-Directory -Path $SpecialToolDir -Name "special patch tool"
    Copy-Item -LiteralPath $ExtractorDir -Destination $ReleaseToolsDir -Recurse -Force
    Copy-Item -LiteralPath $SpecialToolDir -Destination $ReleaseDir -Recurse -Force

    Copy-Item -LiteralPath (Join-Path $PatchSourceDir "物价补丁.zip") `
        -Destination (Join-Path $ReleaseDir "一键安装特殊补丁工具\物价补丁.zip") -Force

    Prepare-DotNetRuntime -TargetDir (Join-Path $ReleaseToolsDir "dotnet-runtime")
    Prepare-PythonRuntime -TargetDir (Join-Path $ReleaseToolsDir "python")
}

function Test-ReleaseFolder {
    Write-Step "Verify release folder"
    $ExpectedFiles = @(
        "一键更新物价补丁.exe",
        "一键还原物价补丁.exe",
        "使用文档.docx",
        "请先看使用文档.txt",
        "物价补丁.zip",
        "还原物价补丁.zip",
        "tools\dotnet-runtime\dotnet.exe",
        "tools\python\python.exe",
        "tools\GGPKExtractor\GGPKExtractor.dll",
        "一键安装特殊补丁工具\PatchBundledGGPK3.dll"
    )

    foreach ($Relative in $ExpectedFiles) {
        Assert-File -Path (Join-Path $ReleaseDir $Relative) -Name $Relative
    }

    Invoke-Checked -FilePath (Join-Path $ReleaseToolsDir "dotnet-runtime\dotnet.exe") -ArgumentList @("--list-runtimes")
    Invoke-Checked -FilePath (Join-Path $ReleaseToolsDir "python\python.exe") -ArgumentList @(
        "-c",
        "import requests, urllib3, certifi, idna, charset_normalizer, ssl; print('python ok')"
    )
}

Build-Docs
Build-Payload
Publish-Launcher
Build-ReleaseFolder
Test-ReleaseFolder

Write-Host ""
Write-Host "Release ready:" -ForegroundColor Green
Write-Host "  $ReleaseDir"
