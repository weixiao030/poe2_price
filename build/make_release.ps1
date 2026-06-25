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
$SpecialToolDir = Join-Path $PatchSourceDir "一键安装特殊补丁工具"
$ReleaseDir = Join-Path $Root "发布版\物价补丁"
$ReleaseToolsDir = Join-Path $ReleaseDir "tools"
$PayloadDir = Join-Path $BuildDir "payload"
$PayloadZip = Join-Path $BuildDir "payload.zip"
$PayloadEnc = Join-Path $BuildDir "Poe2PatchLauncher\payload.enc"
$LauncherProject = Join-Path $BuildDir "Poe2PatchLauncher\Poe2PatchLauncher.csproj"
$PackerProject = Join-Path $BuildDir "PayloadPacker\PayloadPacker.csproj"
$BundleExtractorProject = Join-Path $BuildDir "BundleExtractor\BundleExtractor.csproj"
$PublishDir = Join-Path $BuildDir "publish-self"
$BundleExtractorPublishDir = Join-Path $BuildDir "publish-bundle-extractor"
$DocScript = Join-Path $BuildDir "create_release_doc.py"
$DownloadsDir = Join-Path $BuildDir "downloads"
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $Root "..")).Path
$FinalReleaseDir = Join-Path $WorkspaceRoot "三服合一物价补丁构建版\物价补丁"
$RestoreSeedDir = Join-Path $Root "restore-seeds"
$ChinaRestoreSeedCandidates = @(
    (Join-Path $RestoreSeedDir "国服还原包.zip"),
    (Join-Path $WorkspaceRoot "国服还原包.zip")
)
$IntlRestoreSeedCandidates = @(
    (Join-Path $RestoreSeedDir "国际服还原补丁.zip"),
    (Join-Path $WorkspaceRoot "国际服还原补丁.zip")
)
$ChinaRestoreSeed = $null
$IntlRestoreSeed = $null
$RestoreBaseItemsCacheDir = Join-Path $BuildDir "restore_baseitems_cache"
$IntlBaseItemsRestoreSeedCandidates = @(
    (Join-Path $WorkspaceRoot "三服合一物价补丁构建版\物价补丁\国际服还原补丁.zip"),
    (Join-Path $WorkspaceRoot "三服合一物价补丁构建版\物价补丁\output\restore\国际服还原补丁.zip"),
    (Join-Path $WorkspaceRoot "poe2国际服物价补丁构建版\物价补丁\还原物价补丁.zip"),
    (Join-Path $WorkspaceRoot "备份\物价补丁\还原物价补丁.zip")
)

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

function Resolve-FirstExistingFile {
    param(
        [Parameter(Mandatory = $true)][string[]]$Candidates,
        [Parameter(Mandatory = $true)][string]$Name
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }

    $Message = "Missing $Name. Checked:`n  " + ($Candidates -join "`n  ")
    throw $Message
}

function Copy-IntlRestorePackage {
    param([Parameter(Mandatory = $true)][string]$Destination)

    $RestoreEntryNames = @(
        "data/balance/baseitemtypes.datc64",
        "data/balance/words.datc64",
        "data/balance/traditional chinese/baseitemtypes.datc64",
        "data/balance/traditional chinese/words.datc64",
        "data/balance/simplified chinese/baseitemtypes.datc64",
        "data/balance/simplified chinese/words.datc64",
        "data/balance/japanese/baseitemtypes.datc64",
        "data/balance/japanese/words.datc64",
        "data/balance/korean/baseitemtypes.datc64",
        "data/balance/korean/words.datc64",
        "data/balance/russian/baseitemtypes.datc64",
        "data/balance/russian/words.datc64",
        "data/balance/french/baseitemtypes.datc64",
        "data/balance/french/words.datc64",
        "data/balance/german/baseitemtypes.datc64",
        "data/balance/german/words.datc64",
        "data/balance/spanish/baseitemtypes.datc64",
        "data/balance/spanish/words.datc64",
        "data/balance/portuguese/baseitemtypes.datc64",
        "data/balance/portuguese/words.datc64",
        "data/balance/thai/baseitemtypes.datc64",
        "data/balance/thai/words.datc64"
    )
    Copy-Item -LiteralPath $IntlRestoreSeed -Destination $Destination -Force

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $TargetArchive = [System.IO.Compression.ZipFile]::Open($Destination, [System.IO.Compression.ZipArchiveMode]::Update)
    try {
        foreach ($RestoreEntryName in $RestoreEntryNames) {
            $CacheName = $RestoreEntryName.Replace("/", "_").Replace(" ", "-")
            $CacheDat = Join-Path $RestoreBaseItemsCacheDir $CacheName
            $MinLength = if ($RestoreEntryName.EndsWith("baseitemtypes.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
                1048576
            }
            else {
                1024
            }

            $SourceEntry = $null
            $SourceArchive = $null
            if (Test-Path -LiteralPath $CacheDat -PathType Leaf) {
                $OldEntry = $TargetArchive.GetEntry($RestoreEntryName)
                if ($null -ne $OldEntry) {
                    $OldEntry.Delete()
                }
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $TargetArchive,
                    $CacheDat,
                    $RestoreEntryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
                continue
            }

            foreach ($Candidate in $IntlBaseItemsRestoreSeedCandidates) {
                if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
                    continue
                }

                $Archive = [System.IO.Compression.ZipFile]::OpenRead($Candidate)
                $Entry = $Archive.GetEntry($RestoreEntryName)
                if ($null -ne $Entry -and $Entry.Length -gt $MinLength) {
                    $SourceArchive = $Archive
                    $SourceEntry = $Entry
                    break
                }

                $Archive.Dispose()
            }

            if ($null -eq $SourceEntry) {
                if (-not $RestoreEntryName.EndsWith("baseitemtypes.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
                    Write-Warning "Optional restore entry missing; it will be refreshed from clean game files on first update: $RestoreEntryName"
                    continue
                }
                throw "Missing clean restore entry: $RestoreEntryName"
            }

            try {
                $OldEntry = $TargetArchive.GetEntry($RestoreEntryName)
                if ($null -ne $OldEntry) {
                    $OldEntry.Delete()
                }

                $NewEntry = $TargetArchive.CreateEntry($RestoreEntryName, [System.IO.Compression.CompressionLevel]::Optimal)
                $Input = $SourceEntry.Open()
                $Output = $NewEntry.Open()
                try {
                    $Input.CopyTo($Output)
                }
                finally {
                    $Output.Dispose()
                    $Input.Dispose()
                }
            }
            finally {
                $SourceArchive.Dispose()
            }
        }
    }
    finally {
        $TargetArchive.Dispose()
    }
}

function Test-DotNet8Runtime {
    param([string]$DotnetPath)

    if (-not (Test-Path -LiteralPath $DotnetPath -PathType Leaf)) {
        return $false
    }

    function Test-DotNet8RuntimeDirectory {
        param([string]$RuntimeDir)

        if ([string]::IsNullOrWhiteSpace($RuntimeDir) -or -not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
            return $false
        }
        $RequiredFiles = @(
            "System.Private.CoreLib.dll",
            "System.Runtime.dll",
            "System.Collections.dll",
            "System.Console.dll",
            "System.IO.Compression.dll"
        )
        foreach ($FileName in $RequiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir $FileName) -PathType Leaf)) {
                return $false
            }
        }
        return $true
    }

    $RuntimeLines = & $DotnetPath --list-runtimes 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $DotnetRoot = Split-Path -Parent (Resolve-Path -LiteralPath $DotnetPath).Path
    $LocalRuntimeRoot = Join-Path $DotnetRoot "shared\Microsoft.NETCore.App"
    if (Test-Path -LiteralPath $LocalRuntimeRoot -PathType Container) {
        $LocalRuntime = Get-ChildItem -LiteralPath $LocalRuntimeRoot -Directory |
            Where-Object { $_.Name -match '^8\.' } |
            Sort-Object @{ Expression = { [version]$_.Name }; Descending = $true } |
            Select-Object -First 1
        if ($null -ne $LocalRuntime -and (Test-DotNet8RuntimeDirectory $LocalRuntime.FullName)) {
            return $true
        }
    }

    foreach ($Line in $RuntimeLines) {
        if ($Line -match '^Microsoft\.NETCore\.App\s+(8\.[0-9]+\.[0-9]+)\s+\[(.+)\]$') {
            $RuntimeDir = Join-Path $Matches[2] $Matches[1]
            if (Test-DotNet8RuntimeDirectory $RuntimeDir) {
                return $true
            }
        }
    }
    return $false
}

function Test-PortablePython {
    param([string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return $false
    }

    & $PythonPath -c "import csv, decimal, html, json, ssl, urllib.error, urllib.parse, urllib.request, zipfile" 2>$null
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
        "Lib\site-packages"
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

    # Fix #10: include Bundles2 extractor in the launcher payload fallback.
    $PayloadBundleExtractorDir = Join-Path $PayloadDir "BundleExtractor"
    New-DirectorySafe -Path $PayloadBundleExtractorDir -RootPath $Root | Out-Null
    foreach ($FileName in @("BundleExtractor.exe", "oo2core.dll")) {
        $Source = Join-Path $SourceToolsDir (Join-Path "BundleExtractor" $FileName)
        Assert-File -Path $Source -Name "BundleExtractor\$FileName"
        Copy-Item -LiteralPath $Source -Destination (Join-Path $PayloadBundleExtractorDir $FileName) -Force
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

function Prepare-ReleaseSeedFiles {
    Write-Step "Prepare release seed files"
    $script:ChinaRestoreSeed = Resolve-FirstExistingFile -Candidates $ChinaRestoreSeedCandidates -Name "国服还原包.zip"
    $script:IntlRestoreSeed = Resolve-FirstExistingFile -Candidates $IntlRestoreSeedCandidates -Name "国际服还原补丁.zip"
    $script:IntlBaseItemsRestoreSeedCandidates = @($script:IntlRestoreSeed) + $IntlBaseItemsRestoreSeedCandidates

    Set-Content -LiteralPath (Join-Path $PatchSourceDir "请先看使用文档.txt") -Encoding UTF8 -Value "请先打开使用文档.docx。把整个物价补丁文件夹放到 POE2 游戏根目录；关闭游戏后再运行一键更新或一键还原。程序会自动识别国服 WeGame、国际服官方 GGPK、国际服 Steam/Epic Bundles2。"

    foreach ($GeneratedZip in @(
        (Join-Path $PatchSourceDir "物价补丁.zip"),
        (Join-Path $PatchSourceDir "还原物价补丁.zip"),
        (Join-Path $PatchSourceDir "真实还原物价补丁.zip"),
        (Join-Path $PatchSourceDir "一键安装特殊补丁工具\物价补丁.zip"),
        (Join-Path $PatchSourceDir "一键安装特殊补丁工具\还原物价补丁.zip"),
        (Join-Path $PatchSourceDir "一键安装特殊补丁工具\真实还原物价补丁.zip")
    )) {
        if (Test-Path -LiteralPath $GeneratedZip -PathType Leaf) {
            Remove-Item -LiteralPath $GeneratedZip -Force
        }
    }

    Assert-File -Path $ChinaRestoreSeed -Name "国服还原包.zip"
    Assert-File -Path $IntlRestoreSeed -Name "国际服还原补丁.zip"
    Copy-Item -LiteralPath $ChinaRestoreSeed -Destination (Join-Path $PatchSourceDir "国服还原包.zip") -Force
    Copy-IntlRestorePackage -Destination (Join-Path $PatchSourceDir "国际服还原补丁.zip")
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

function Publish-BundleExtractor {
    Write-Step "Publish BundleExtractor from source"
    Remove-TreeSafe -Path $BundleExtractorPublishDir -RootPath $Root
    Assert-File -Path $BundleExtractorProject -Name "BundleExtractor project"

    Invoke-Checked -FilePath "dotnet" -ArgumentList @(
        "publish",
        $BundleExtractorProject,
        "-c", "Release",
        "-r", "win-x64",
        "-p:SelfContained=true",
        "-p:PublishSingleFile=true",
        "-p:EnableCompressionInSingleFile=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-p:DebugType=None",
        "-p:DebugSymbols=false",
        "-o", $BundleExtractorPublishDir
    )

    $BundleExtractorDir = Join-Path $SourceToolsDir "BundleExtractor"
    New-DirectorySafe -Path $BundleExtractorDir -RootPath $Root | Out-Null
    Assert-File -Path (Join-Path $BundleExtractorPublishDir "BundleExtractor.exe") -Name "published BundleExtractor"
    Copy-Item -LiteralPath (Join-Path $BundleExtractorPublishDir "BundleExtractor.exe") -Destination (Join-Path $BundleExtractorDir "BundleExtractor.exe") -Force
    Assert-File -Path (Join-Path $SpecialToolDir "oo2core.dll") -Name "oo2core.dll"
    Copy-Item -LiteralPath (Join-Path $SpecialToolDir "oo2core.dll") -Destination (Join-Path $BundleExtractorDir "oo2core.dll") -Force
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

    foreach ($FileName in @("使用文档.docx", "请先看使用文档.txt")) {
        $Source = Join-Path $PatchSourceDir $FileName
        Assert-File -Path $Source -Name $FileName
        Copy-Item -LiteralPath $Source -Destination (Join-Path $ReleaseDir $FileName) -Force
    }

    foreach ($FileName in @("国服还原包.zip", "国际服还原补丁.zip")) {
        $Source = Join-Path $PatchSourceDir $FileName
        Assert-File -Path $Source -Name $FileName
        Copy-Item -LiteralPath $Source -Destination (Join-Path $ReleaseDir $FileName) -Force
    }

    $ExtractorDir = Join-Path $SourceToolsDir "GGPKExtractor"
    $BundleExtractorDir = Join-Path $SourceToolsDir "BundleExtractor"
    Assert-Directory -Path $ExtractorDir -Name "GGPKExtractor"
    Assert-Directory -Path $BundleExtractorDir -Name "BundleExtractor"
    Assert-Directory -Path $SpecialToolDir -Name "special patch tool"
    Copy-Item -LiteralPath $ExtractorDir -Destination $ReleaseToolsDir -Recurse -Force
    Copy-Item -LiteralPath $BundleExtractorDir -Destination $ReleaseToolsDir -Recurse -Force
    Copy-Item -LiteralPath $SpecialToolDir -Destination $ReleaseDir -Recurse -Force

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
        "国服还原包.zip",
        "国际服还原补丁.zip",
        "tools\dotnet-runtime\dotnet.exe",
        "tools\python\python310.zip",
        "tools\python\_ssl.pyd",
        "tools\python\python.exe",
        "tools\GGPKExtractor\GGPKExtractor.dll",
        "tools\BundleExtractor\BundleExtractor.exe",
        "tools\BundleExtractor\oo2core.dll",
        "一键安装特殊补丁工具\PatchBundledGGPK3.dll",
        "一键安装特殊补丁工具\PatchBundle3.dll",
        "一键安装特殊补丁工具\PatchBundle3.runtimeconfig.json"
    )

    foreach ($Relative in $ExpectedFiles) {
        Assert-File -Path (Join-Path $ReleaseDir $Relative) -Name $Relative
    }

    Invoke-Checked -FilePath (Join-Path $ReleaseToolsDir "dotnet-runtime\dotnet.exe") -ArgumentList @("--list-runtimes")
    Invoke-Checked -FilePath (Join-Path $ReleaseToolsDir "python\python.exe") -ArgumentList @(
        "-c",
        "import csv, decimal, html, json, ssl, urllib.error, urllib.parse, urllib.request, zipfile; print('python ok')"
    )
    Invoke-Checked -FilePath (Join-Path $ReleaseToolsDir "dotnet-runtime\dotnet.exe") -ArgumentList @(
        (Join-Path $ReleaseDir "一键安装特殊补丁工具\PatchBundle3.dll")
    )
}

function Publish-FinalReleaseFolder {
    Write-Step "Copy release folder to workspace build output"
    Remove-TreeSafe -Path $FinalReleaseDir -RootPath $WorkspaceRoot
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FinalReleaseDir) | Out-Null
    Copy-Item -LiteralPath $ReleaseDir -Destination (Split-Path -Parent $FinalReleaseDir) -Recurse -Force
}

Build-Docs
Prepare-ReleaseSeedFiles
Publish-BundleExtractor
Build-Payload
Publish-Launcher
Build-ReleaseFolder
Test-ReleaseFolder
Publish-FinalReleaseFolder

Write-Host ""
Write-Host "Release ready:" -ForegroundColor Green
Write-Host "  $ReleaseDir"
Write-Host "  $FinalReleaseDir"
