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
$DotNetRepairVersion = "8.0.28"
$DotNetRepairArchiveName = "dotnet-runtime-$DotNetRepairVersion-win-x64.zip"
$DotNetRepairArchive = Join-Path $DownloadsDir $DotNetRepairArchiveName
$DotNetRepairSha256 = "d525978009270857c7a3ff0ce7f5d1244ae547dd34482e09738fea49814f76cf"
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

function Install-FileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $Destination = [System.IO.Path]::GetFullPath($Destination)
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        [System.IO.File]::Move($Source, $Destination)
        return
    }
    $Backup = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $Destination), ".backup-", [Guid]::NewGuid().ToString("N")))
    try {
        [System.IO.File]::Replace($Source, $Destination, $Backup, $true)
    }
    finally {
        if (Test-Path -LiteralPath $Backup -PathType Leaf) {
            Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-CleanRestoreDat {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$EntryName
    )

    $Info = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($EntryName.EndsWith("baseitemtypes.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 1048576) {
            throw "BaseItemTypes restore entry is too small: $EntryName"
        }
        $Csv = Join-Path $env:TEMP ([Guid]::NewGuid().ToString("N") + ".csv")
        try {
            & python (Join-Path $SourceToolsDir "poe2_name_price_patch.py") export --source $Path --output $Csv
            if ($LASTEXITCODE -ne 0) {
                throw "BaseItemTypes restore validation failed: $EntryName"
            }
            $Marker = Import-Csv -LiteralPath $Csv -Encoding UTF8 | Where-Object {
                $Name = [string]$_.name
                $Name -match '=(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                $Name -match '^(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                ($Name.Length -le 12 -and $Name -match '(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$')
            } | Select-Object -First 1
            if ($null -ne $Marker) {
                throw "BaseItemTypes restore entry contains a price marker: $EntryName"
            }
        }
        finally {
            Remove-Item -LiteralPath $Csv -Force -ErrorAction SilentlyContinue
        }
        return
    }
    if ($EntryName.EndsWith("words.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 1024) {
            throw "Words restore entry is too small: $EntryName"
        }
        $Text = & python (Join-Path $SourceToolsDir "build_poe2scout_price_patch.py") --check-words $Path
        if ($LASTEXITCODE -ne 0) {
            throw "Words restore validation failed: $EntryName"
        }
        $Inspection = $Text | ConvertFrom-Json
        if ([int]$Inspection.patched_count -ne 0) {
            throw "Words restore entry contains active price markers: $EntryName"
        }
        return
    }
    if ($EntryName.EndsWith("endgamemaps.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 4096) {
            throw "EndgameMaps restore entry is too small: $EntryName"
        }
        $Text = & python (Join-Path $SourceToolsDir "poe2_island_rumour_patch.py") check --source $Path --game-path $EntryName
        if ($LASTEXITCODE -ne 0) {
            throw "EndgameMaps restore validation failed: $EntryName"
        }
        $Inspection = $Text | ConvertFrom-Json
        if ([int]$Inspection.patched_count -ne 0) {
            throw "EndgameMaps restore entry contains island hints: $EntryName"
        }
    }
}

function Copy-IntlRestorePackage {
    param([Parameter(Mandatory = $true)][string]$Destination)

    $RestoreEntryNames = @(
        "data/balance/baseitemtypes.datc64",
        "data/balance/words.datc64",
        "data/balance/endgamemaps.datc64",
        "data/balance/traditional chinese/baseitemtypes.datc64",
        "data/balance/traditional chinese/words.datc64",
        "data/balance/traditional chinese/endgamemaps.datc64",
        "data/balance/simplified chinese/baseitemtypes.datc64",
        "data/balance/simplified chinese/words.datc64",
        "data/balance/simplified chinese/endgamemaps.datc64",
        "data/balance/japanese/baseitemtypes.datc64",
        "data/balance/japanese/words.datc64",
        "data/balance/japanese/endgamemaps.datc64",
        "data/balance/korean/baseitemtypes.datc64",
        "data/balance/korean/words.datc64",
        "data/balance/korean/endgamemaps.datc64",
        "data/balance/russian/baseitemtypes.datc64",
        "data/balance/russian/words.datc64",
        "data/balance/russian/endgamemaps.datc64",
        "data/balance/french/baseitemtypes.datc64",
        "data/balance/french/words.datc64",
        "data/balance/french/endgamemaps.datc64",
        "data/balance/german/baseitemtypes.datc64",
        "data/balance/german/words.datc64",
        "data/balance/german/endgamemaps.datc64",
        "data/balance/spanish/baseitemtypes.datc64",
        "data/balance/spanish/words.datc64",
        "data/balance/spanish/endgamemaps.datc64",
        "data/balance/portuguese/baseitemtypes.datc64",
        "data/balance/portuguese/words.datc64",
        "data/balance/portuguese/endgamemaps.datc64",
        "data/balance/thai/baseitemtypes.datc64",
        "data/balance/thai/words.datc64",
        "data/balance/thai/endgamemaps.datc64"
    )
    $Destination = [System.IO.Path]::GetFullPath($Destination)
    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    $WorkingDestination = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $Destination), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    Copy-Item -LiteralPath $IntlRestoreSeed -Destination $WorkingDestination -Force

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    try {
        $TargetArchive = [System.IO.Compression.ZipFile]::Open($WorkingDestination, [System.IO.Compression.ZipArchiveMode]::Update)
        try {
            foreach ($RestoreEntryName in $RestoreEntryNames) {
            $CacheName = $RestoreEntryName.Replace("/", "_").Replace(" ", "-")
            $CacheDat = Join-Path $RestoreBaseItemsCacheDir $CacheName
            $MinLength = if ($RestoreEntryName.EndsWith("baseitemtypes.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
                1048576
            }
            elseif ($RestoreEntryName.EndsWith("endgamemaps.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
                4096
            }
            else {
                1024
            }

            $SourceEntry = $null
            $SourceArchive = $null
            if (Test-Path -LiteralPath $CacheDat -PathType Leaf) {
                Assert-CleanRestoreDat -Path $CacheDat -EntryName $RestoreEntryName
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

            $TempEntry = ""
            try {
                $TempEntry = Join-Path $env:TEMP ([Guid]::NewGuid().ToString("N") + ".datc64")
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($SourceEntry, $TempEntry, $true)
                Assert-CleanRestoreDat -Path $TempEntry -EntryName $RestoreEntryName
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
                if (-not [string]::IsNullOrWhiteSpace($TempEntry)) {
                    Remove-Item -LiteralPath $TempEntry -Force -ErrorAction SilentlyContinue
                }
                $SourceArchive.Dispose()
            }
            }
        }
        finally {
            $TargetArchive.Dispose()
        }
        # Reopen after all writes so central-directory/CRC corruption is caught
        # before the previous known-good package is replaced.
        $CheckArchive = [System.IO.Compression.ZipFile]::OpenRead($WorkingDestination)
        try {
            foreach ($Entry in @($CheckArchive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })) {
                $Stream = $Entry.Open()
                try {
                    $Buffer = New-Object byte[] 1048576
                    while ($Stream.Read($Buffer, 0, $Buffer.Length) -gt 0) { }
                }
                finally {
                    $Stream.Dispose()
                }
            }
        }
        finally {
            $CheckArchive.Dispose()
        }
        Install-FileAtomically -Source $WorkingDestination -Destination $Destination
    }
    finally {
        if (Test-Path -LiteralPath $WorkingDestination -PathType Leaf) {
            Remove-Item -LiteralPath $WorkingDestination -Force -ErrorAction SilentlyContinue
        }
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

    $VersionText = & $PythonPath -c "import csv, decimal, html, json, ssl, sys, urllib.error, urllib.parse, urllib.request, zipfile; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    try {
        return ([version]([string]$VersionText).Trim() -ge [version]"3.13.0")
    }
    catch {
        return $false
    }
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [int]$TimeoutSeconds = 120
    )

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null
    $TempFile = [string]::Concat($OutFile, ".download-", [Guid]::NewGuid().ToString("N"), ".tmp")
    try {
        Invoke-WebRequest -Uri $Url -OutFile $TempFile -UseBasicParsing -TimeoutSec ([Math]::Max(30, $TimeoutSeconds))
        $ActualSha256 = (Get-FileHash -LiteralPath $TempFile -Algorithm SHA256).Hash
        if (-not $ActualSha256.Equals($ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Downloaded file SHA256 mismatch: $Url"
        }
        Install-FileAtomically -Source $TempFile -Destination $OutFile
    }
    finally {
        if (Test-Path -LiteralPath $TempFile -PathType Leaf) {
            Remove-Item -LiteralPath $TempFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-DownloadFromSources {
    param(
        [Parameter(Mandatory = $true)][object[]]$Sources,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )

    $Errors = New-Object System.Collections.Generic.List[string]
    foreach ($Source in $Sources) {
        try {
            Write-Host "Download from $($Source.Name): $($Source.Url)"
            Invoke-Download `
                -Url $Source.Url `
                -OutFile $OutFile `
                -ExpectedSha256 $ExpectedSha256 `
                -TimeoutSeconds ([int]$Source.TimeoutSeconds)
            return
        }
        catch {
            $Errors.Add("$($Source.Name): $($_.Exception.Message)")
            Write-Warning "$($Source.Name) failed; trying the next source."
        }
    }
    throw "All download sources failed: $([string]::Join(' | ', $Errors))"
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
    Remove-TreeSafe -Path $TargetDir -RootPath $Root
    New-DirectorySafe -Path $TargetDir -RootPath $Root | Out-Null

    $DotNetArchiveValid = (Test-Path -LiteralPath $DotNetRepairArchive -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $DotNetRepairArchive -Algorithm SHA256).Hash.Equals($DotNetRepairSha256, [System.StringComparison]::OrdinalIgnoreCase))
    if (-not $DotNetArchiveValid) {
        $DotNetSources = @(
            [pscustomobject]@{
                Name = "Microsoft CDN"
                Url = "https://dotnetcli.azureedge.net/dotnet/Runtime/$DotNetRepairVersion/$DotNetRepairArchiveName"
                TimeoutSeconds = 180
            },
            [pscustomobject]@{
                Name = "Microsoft 官方源"
                Url = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$DotNetRepairVersion/$DotNetRepairArchiveName"
                TimeoutSeconds = 180
            }
        )
        Invoke-DownloadFromSources -Sources $DotNetSources -OutFile $DotNetRepairArchive -ExpectedSha256 $DotNetRepairSha256
    }

    Expand-Archive -LiteralPath $DotNetRepairArchive -DestinationPath $TargetDir -Force

    $RepairCacheDir = Join-Path (Split-Path -Parent $TargetDir) "downloads"
    New-Item -ItemType Directory -Force -Path $RepairCacheDir | Out-Null
    Copy-Item -LiteralPath $DotNetRepairArchive -Destination (Join-Path $RepairCacheDir $DotNetRepairArchiveName) -Force

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

    $PythonVersion = "3.13.14"
    $PythonZipName = "python-$PythonVersion-embed-amd64.zip"
    $PythonZip = Join-Path $DownloadsDir $PythonZipName
    $PythonZipSha256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"
    $PythonSources = @(
        [pscustomobject]@{
            Name = "华为云镜像"
            Url = "https://mirrors.huaweicloud.com/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 90
        },
        [pscustomobject]@{
            Name = "阿里云镜像"
            Url = "https://mirrors.aliyun.com/python-release/windows/$PythonZipName"
            TimeoutSeconds = 90
        },
        [pscustomobject]@{
            Name = "南京大学镜像"
            Url = "https://mirrors.nju.edu.cn/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 90
        },
        [pscustomobject]@{
            Name = "Python 官方备用源"
            Url = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 180
        }
    )

    $PythonZipValid = (Test-Path -LiteralPath $PythonZip -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $PythonZip -Algorithm SHA256).Hash.Equals($PythonZipSha256, [System.StringComparison]::OrdinalIgnoreCase))
    if (-not $PythonZipValid) {
        Write-Host "Download Python embeddable runtime: $PythonVersion"
        Invoke-DownloadFromSources -Sources $PythonSources -OutFile $PythonZip -ExpectedSha256 $PythonZipSha256
    }

    Expand-Archive -LiteralPath $PythonZip -DestinationPath $TargetDir -Force

    $SitePackages = Join-Path $TargetDir "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null
    Set-Content -LiteralPath (Join-Path $TargetDir "python313._pth") -Encoding ASCII -Value @(
        "python313.zip",
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
        "poe2_island_rumour_patch.py",
        "build_poe2scout_price_patch.py"
    )) {
        $Source = Join-Path $SourceToolsDir $FileName
        Assert-File -Path $Source -Name $FileName
        Copy-Item -LiteralPath $Source -Destination (Join-Path $PayloadDir $FileName) -Force
    }

    # Price-source adapters are imported by build_poe2scout_price_patch.py at runtime.
    # Copy Python sources explicitly so local __pycache__ files never enter a release.
    $SourcePriceSourcesDir = Join-Path $SourceToolsDir "price_sources"
    Assert-Directory -Path $SourcePriceSourcesDir -Name "price_sources"
    foreach ($Source in @(Get-ChildItem -LiteralPath $SourcePriceSourcesDir -Recurse -File -Filter "*.py")) {
        $Relative = $Source.FullName.Substring($SourcePriceSourcesDir.Length).TrimStart('\', '/')
        $Destination = Join-Path $PayloadDir (Join-Path "price_sources" $Relative)
        New-DirectorySafe -Path (Split-Path -Parent $Destination) -RootPath $Root | Out-Null
        Copy-Item -LiteralPath $Source.FullName -Destination $Destination -Force
    }

    # Fix #10: include Bundles2 extractor in the launcher payload fallback.
    $PayloadBundleExtractorDir = Join-Path $PayloadDir "BundleExtractor"
    New-DirectorySafe -Path $PayloadBundleExtractorDir -RootPath $Root | Out-Null
    foreach ($FileName in @("BundleExtractor.exe", "oo2core.dll", "vcruntime140.dll")) {
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
        "run", "-c", "Release", "--project", $PackerProject, "--",
        $PayloadZip,
        $PayloadEnc
    )
}

function Prepare-ReleaseSeedFiles {
    Write-Step "Prepare release seed files"
    $script:ChinaRestoreSeed = Resolve-FirstExistingFile -Candidates $ChinaRestoreSeedCandidates -Name "国服还原包.zip"
    $script:IntlRestoreSeed = Resolve-FirstExistingFile -Candidates $IntlRestoreSeedCandidates -Name "国际服还原补丁.zip"
    $script:IntlBaseItemsRestoreSeedCandidates = @($script:IntlRestoreSeed) + $IntlBaseItemsRestoreSeedCandidates

    Set-Content -LiteralPath (Join-Path $PatchSourceDir "请先看使用文档.txt") -Encoding UTF8 -Value "请先打开使用文档.docx。物价补丁文件夹可以放在任意位置；关闭游戏后运行一键更新或一键还原，并在窗口中确认自动识别的客户端，或改用手动选择。支持国服 WeGame（流放之路：降临）、国际服官方 GGPK、国际服 Steam/Epic Bundles2；发现多个客户端时必须手动选择。"

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

    $LauncherExe = Join-Path $PublishDir "Poe2PatchLauncher.exe"
    Assert-File -Path $LauncherExe -Name "published launcher"
    # Keep the executables committed under the source distribution in sync with
    # the encrypted payload and file-version metadata produced by this build.
    Copy-Item -LiteralPath $LauncherExe -Destination (Join-Path $PatchSourceDir "一键更新物价补丁.exe") -Force
    Copy-Item -LiteralPath $LauncherExe -Destination (Join-Path $PatchSourceDir "一键还原物价补丁.exe") -Force
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
    Assert-File -Path (Join-Path $SpecialToolDir "vcruntime140.dll") -Name "vcruntime140.dll"
    Copy-Item -LiteralPath (Join-Path $SpecialToolDir "vcruntime140.dll") -Destination (Join-Path $BundleExtractorDir "vcruntime140.dll") -Force
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
        "tools\downloads\dotnet-runtime-8.0.28-win-x64.zip",
        "tools\python\python313.zip",
        "tools\python\_ssl.pyd",
        "tools\python\python.exe",
        "tools\GGPKExtractor\GGPKExtractor.dll",
        "tools\GGPKExtractor\GGPKExtractor.deps.json",
        "tools\GGPKExtractor\GGPKExtractor.runtimeconfig.json",
        "tools\GGPKExtractor\LibBundle3.dll",
        "tools\GGPKExtractor\LibBundledGGPK3.dll",
        "tools\GGPKExtractor\LibGGPK3.dll",
        "tools\GGPKExtractor\SystemExtensions.dll",
        "tools\GGPKExtractor\oo2core.dll",
        "tools\GGPKExtractor\vcruntime140.dll",
        "tools\BundleExtractor\BundleExtractor.exe",
        "tools\BundleExtractor\oo2core.dll",
        "tools\BundleExtractor\vcruntime140.dll",
        "一键安装特殊补丁工具\PatchBundledGGPK3.dll",
        "一键安装特殊补丁工具\PatchBundledGGPK3.runtimeconfig.json",
        "一键安装特殊补丁工具\PatchBundle3.dll",
        "一键安装特殊补丁工具\PatchBundle3.runtimeconfig.json",
        "一键安装特殊补丁工具\LibBundle3.dll",
        "一键安装特殊补丁工具\LibBundledGGPK3.dll",
        "一键安装特殊补丁工具\LibGGPK3.dll",
        "一键安装特殊补丁工具\SystemExtensions.dll",
        "一键安装特殊补丁工具\oo2core.dll",
        "一键安装特殊补丁工具\vcruntime140.dll"
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
