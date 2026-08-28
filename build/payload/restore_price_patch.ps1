param(
    [string]$Poe2Dir = "",
    [string]$RestoreZip = "",
    [string]$PhysicalRestoreZip = "",
    [switch]$NoInstall,
    [switch]$SkipGameDirectoryMutex
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot "poe2_patch_common.ps1")

$CodeToolsRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:POE2_PATCH_ROOT)) {
    $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path -LiteralPath $env:POE2_PATCH_ROOT).Path
}
Set-Location -LiteralPath $RepoRoot
$script:PatchVersion = "v0.6.0"
$Poe2DirWasExplicit = -not [string]::IsNullOrWhiteSpace($Poe2Dir)
$PreferredPoe2Dir = Split-Path -Parent $RepoRoot

trap {
    Write-Host ""
    Write-Host "还原失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if ($Poe2DirWasExplicit) {
    $Poe2Dir = Resolve-Poe2GameDirectorySelection -Mode "manual" -ManualPath $Poe2Dir
    $GameDirectorySelectionMode = "manual"
}
else {
    $DirectorySelection = Show-Poe2GameDirectorySelectionDialog `
        -Title "POE2 物价补丁还原 $script:PatchVersion" `
        -PreferredRoot $PreferredPoe2Dir `
        -InitialPoe2Dir (Get-Poe2SavedGameDirectory) `
        -ActionText "请选择要还原物价补丁的 POE2 客户端。"
    $Poe2Dir = [string]$DirectorySelection.Poe2Dir
    $GameDirectorySelectionMode = [string]$DirectorySelection.PathMode
}
if (-not $SkipGameDirectoryMutex) {
    $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe2Dir
}
try {
    Save-Poe2GameDirectory -Poe2Dir $Poe2Dir | Out-Null
}
catch {
    Write-Warning "无法保存最近使用的游戏目录，本次还原仍会继续：$($_.Exception.Message)"
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Assert-File {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing $Name`: $Path"
    }
}

function Test-BaseItemsLookPatched {
    param([string]$SourceDat)

    $TempCsv = Join-Path $env:TEMP ([string]::Concat("poe2_price_restore_", [Guid]::NewGuid().ToString("N"), ".csv"))
    try {
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $ExportScript = Join-Path $CodeToolsRoot "poe2_name_price_patch.py"
        $ExportResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $ExportScript,
            "export",
            "--source", $SourceDat,
            "--output", $TempCsv
        ) -Quiet
        if ($ExportResult.ExitCode -ne 0) {
            $Detail = ([string]$ExportResult.Text).Trim()
            throw "无法判断 BaseItemTypes.datc64 是否包含物价补丁标记：检测工具退出码 $($ExportResult.ExitCode)。$Detail"
        }
        $Rows = Import-Csv -LiteralPath $TempCsv -Encoding UTF8
        return [bool]($Rows | Where-Object {
                $Name = [string]$_.name
                if ([string]::IsNullOrWhiteSpace($Name)) {
                    return $false
                }
                return (
                    $Name -match '=(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                    $Name -match '^(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                    ($Name.Length -le 12 -and $Name -match '(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$')
                )
            } | Select-Object -First 1)
    }
    finally {
        if (Test-Path -LiteralPath $TempCsv -PathType Leaf) {
            Remove-Item -LiteralPath $TempCsv -Force
        }
    }
}

function Test-WordsLookPatched {
    param([string]$SourceWords)

    if (-not (Test-Path -LiteralPath $SourceWords -PathType Leaf)) {
        return $false
    }

    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $CheckScript = Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"
    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
        $CheckScript,
        "--check-words", $SourceWords
    ) -Quiet
    if ($Result.ExitCode -ne 0) {
        $Detail = ([string]$Result.Text).Trim()
        throw "无法判断 Words.datc64 是否包含物价补丁标记：检测工具退出码 $($Result.ExitCode)。$Detail"
    }
    try {
        $Info = $Result.Text | ConvertFrom-Json
        return ([int]$Info.patched_count -gt 0)
    }
    catch {
        throw "无法判断 Words.datc64 是否包含物价补丁标记：检测结果无法解析。$($_.Exception.Message)"
    }
}

function Get-BaseItemsMetadataSignature {
    param([string]$SourceDat)

    Assert-File $SourceDat "BaseItemTypes.datc64"
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $SignatureScript = Join-Path $CodeToolsRoot "poe2_name_price_patch.py"
    $SignatureResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
        $SignatureScript,
        "signature",
        "--source", $SourceDat
    ) -Quiet
    if ($SignatureResult.ExitCode -ne 0) {
        throw "Failed to build BaseItemTypes structure signature. Exit code: $($SignatureResult.ExitCode)`n$($SignatureResult.Text)"
    }

    try {
        $Signature = $SignatureResult.Text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Failed to parse BaseItemTypes structure signature: $($_.Exception.Message)"
    }

    $RequiredFields = @(
        "signature_version",
        "row_count",
        "row_size",
        "metadata_paths_sha256",
        "fixed_rows_sha256",
        "compatibility_sha256"
    )
    foreach ($Field in $RequiredFields) {
        $Property = $Signature.PSObject.Properties[$Field]
        if ($null -eq $Property -or [string]::IsNullOrWhiteSpace([string]$Property.Value)) {
            throw "BaseItemTypes structure signature is missing or has an empty field: $Field"
        }
    }

    return $Signature
}

function Test-BaseItemsCompatible {
    param(
        [string]$LeftDat,
        [string]$RightDat
    )

    try {
        $Left = Get-BaseItemsMetadataSignature $LeftDat
        $Right = Get-BaseItemsMetadataSignature $RightDat
        return (
            [string]$Left.signature_version -ceq [string]$Right.signature_version -and
            [string]$Left.row_count -ceq [string]$Right.row_count -and
            [string]$Left.row_size -ceq [string]$Right.row_size -and
            [string]$Left.metadata_paths_sha256 -ceq [string]$Right.metadata_paths_sha256 -and
            [string]$Left.fixed_rows_sha256 -ceq [string]$Right.fixed_rows_sha256 -and
            [string]$Left.compatibility_sha256 -ceq [string]$Right.compatibility_sha256
        )
    }
    catch {
        Write-Warning "BaseItemTypes compatibility check failed: $($_.Exception.Message)"
        return $false
    }
}

function Get-ZipBaseItemsEntryAsTempFile {
    param(
        [string]$ZipPath,
        [string]$EntryName
    )

    $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_restore_entry_", [Guid]::NewGuid().ToString("N"), ".datc64"))
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $Entry = $Archive.GetEntry($EntryName)
        if ($null -eq $Entry) {
            throw "Restore zip does not contain $EntryName"
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
    }
    finally {
        $Archive.Dispose()
    }
    return $TempDat
}

function Test-ZipEntryExists {
    param(
        [string]$ZipPath,
        [string]$EntryName
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        return ($null -ne $Archive.GetEntry($EntryName))
    }
    finally {
        $Archive.Dispose()
    }
}

function Test-EndgameMapsLookPatched {
    param([string]$SourceEndgameMaps)

    if (-not (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf)) {
        return $false
    }

    try {
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $ScriptPath = Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $ScriptPath,
            "check",
            "--source", $SourceEndgameMaps,
            "--game-path", $InstallInfo.TcEndgameMapsPath
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            $Detail = ([string]$Result.Text).Trim()
            throw "无法判断 EndgameMaps.datc64 是否包含岛屿传言提示：检测工具退出码 $($Result.ExitCode)。$Detail"
        }
        $Info = $Result.Text | ConvertFrom-Json
        return ([int]$Info.patched_count -gt 0)
    }
    catch {
        throw "无法判断 EndgameMaps.datc64 是否包含岛屿传言提示：$($_.Exception.Message)"
    }
}

function Copy-ZipEntry {
    param(
        [Parameter(Mandatory = $true)]$SourceArchive,
        [Parameter(Mandatory = $true)]$TargetArchive,
        [Parameter(Mandatory = $true)][string]$EntryName,
        [switch]$Required
    )

    $Entry = $SourceArchive.GetEntry($EntryName)
    if ($null -eq $Entry) {
        if ($Required) {
            throw "Restore zip does not contain $EntryName"
        }
        return $false
    }

    $NewEntry = $TargetArchive.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
    $Input = $Entry.Open()
    $Output = $NewEntry.Open()
    try {
        $Input.CopyTo($Output)
    }
    finally {
        $Output.Dispose()
        $Input.Dispose()
    }
    return $true
}

function Update-ZipEntryFromFile {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$SourceFile,
        [Parameter(Mandatory = $true)][string]$EntryName
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $ZipPath = [System.IO.Path]::GetFullPath($ZipPath)
    $ZipDir = Split-Path -Parent $ZipPath
    $TempZip = Join-Path $ZipDir ([string]::Concat(".", (Split-Path -Leaf $ZipPath), ".update-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        [System.IO.File]::Copy($ZipPath, $TempZip, $false)
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Update)
        try {
            $OldEntry = $Archive.GetEntry($EntryName)
            if ($null -ne $OldEntry) {
                $OldEntry.Delete()
            }
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $Archive,
                $SourceFile,
                $EntryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
        finally {
            $Archive.Dispose()
        }
        Get-Poe2ZipEntryCrc32Map -Path $TempZip | Out-Null
        Move-Poe2FileAtomically -Source $TempZip -Destination $ZipPath | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-BaseItemRestoreZip {
    param(
        [string]$SourceDat,
        [string]$SourceWords = "",
        [string]$SourceEndgameMaps = "",
        [string]$OutputZip
    )

    Assert-File $SourceDat "clean BaseItemTypes.datc64"
    if (Test-BaseItemsLookPatched $SourceDat) {
        throw "Cached BaseItemTypes looks patched. Refusing to build a restore zip from it."
    }

    if (-not [string]::IsNullOrWhiteSpace($SourceWords) -and (Test-Path -LiteralPath $SourceWords -PathType Leaf) -and (Test-WordsLookPatched $SourceWords)) {
        throw "Cached Words looks patched. Refusing to build a restore zip from it."
    }
    if (-not [string]::IsNullOrWhiteSpace($SourceEndgameMaps) -and (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf) -and (Test-EndgameMapsLookPatched $SourceEndgameMaps)) {
        throw "Cached EndgameMaps looks patched. Refusing to build a restore zip from it."
    }

    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputZip), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $Archive,
                $SourceDat,
                $InstallInfo.TcBaseItemsPath,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
            if (-not [string]::IsNullOrWhiteSpace($SourceWords) -and (Test-Path -LiteralPath $SourceWords -PathType Leaf)) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceWords,
                    $TcWordsPath,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
            if (-not [string]::IsNullOrWhiteSpace($SourceEndgameMaps) -and (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf)) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceEndgameMaps,
                    $InstallInfo.TcEndgameMapsPath,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $Archive.Dispose()
        }
        Get-Poe2ZipEntryCrc32Map -Path $TempZip | Out-Null
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputZip | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-RestoreZip {
    param([string]$Path)

    Assert-File $Path "restore zip"
    Assert-Poe2LogicalRestoreManifest -ZipPath $Path -InstallInfo $InstallInfo `
        -AllowLegacyWithoutManifest:(Test-Poe2LegacyRestorePatchZipName -Path $Path) | Out-Null
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $Entry = $Archive.GetEntry($InstallInfo.TcBaseItemsPath)
        if ($null -eq $Entry) {
            throw "Restore zip does not contain $($InstallInfo.TcBaseItemsPath)"
        }
        if ($Entry.Length -le 1048576) {
            throw "Restore zip entry is too small to be a valid BaseItemTypes.datc64"
        }
        $WordsEntry = $Archive.GetEntry($TcWordsPath)
        if ($SupportsUniqueWords -and $null -eq $WordsEntry) {
            Write-Warning "还原包缺少 $TcWordsPath；将只还原 BaseItemTypes。请在游戏文件干净后运行一次一键更新，以刷新包含 Words 的新版还原包。"
        }
        elseif ($null -ne $WordsEntry -and $WordsEntry.Length -le 1024) {
            throw "Restore zip Words entry is too small to be valid: $TcWordsPath"
        }
        $EndgameMapsEntry = $Archive.GetEntry($InstallInfo.TcEndgameMapsPath)
        if ($null -eq $EndgameMapsEntry) {
            Write-Warning "还原包缺少 $($InstallInfo.TcEndgameMapsPath)；将只还原 BaseItemTypes/Words。请在游戏文件干净后运行一次一键更新，以刷新包含 EndgameMaps 的新版还原包。"
        }

        $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_restore_assert_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        $TempWords = Join-Path $env:TEMP ([string]::Concat("poe2_restore_words_assert_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        $TempEndgameMaps = Join-Path $env:TEMP ([string]::Concat("poe2_restore_endgamemaps_assert_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        try {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
            if (Test-BaseItemsLookPatched $TempDat) {
                throw "Restore zip BaseItemTypes looks patched. Refusing to restore from a polluted backup."
            }
            if ($null -ne $WordsEntry) {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($WordsEntry, $TempWords, $true)
                if (Test-WordsLookPatched $TempWords) {
                    throw "Restore zip Words contains active price markers. Refusing to restore from a polluted backup."
                }
            }
            if ($null -ne $EndgameMapsEntry) {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($EndgameMapsEntry, $TempEndgameMaps, $true)
                if (Test-EndgameMapsLookPatched $TempEndgameMaps) {
                    throw "Restore zip EndgameMaps looks patched. Refusing to restore from a polluted backup."
                }
            }
        }
        finally {
            if (Test-Path -LiteralPath $TempDat -PathType Leaf) {
                Remove-Item -LiteralPath $TempDat -Force
            }
            if (Test-Path -LiteralPath $TempWords -PathType Leaf) {
                Remove-Item -LiteralPath $TempWords -Force
            }
            if (Test-Path -LiteralPath $TempEndgameMaps -PathType Leaf) {
                Remove-Item -LiteralPath $TempEndgameMaps -Force
            }
        }
    }
    finally {
        $Archive.Dispose()
    }
}

function Add-Poe2RestoreManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [string]$BaselineKind = "validated-migration"
    )

    $TempDat = ""
    try {
        $TempDat = Get-ZipBaseItemsEntryAsTempFile -ZipPath $ZipPath -EntryName $InstallInfo.TcBaseItemsPath
        $Signature = Get-BaseItemsMetadataSignature $TempDat
        Set-Poe2LogicalRestoreManifest -ZipPath $ZipPath -InstallInfo $InstallInfo `
            -BaseItemsSignature $Signature -BaselineKind $BaselineKind | Out-Null
        Assert-Poe2LogicalRestoreManifest -ZipPath $ZipPath -InstallInfo $InstallInfo | Out-Null
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($TempDat) -and (Test-Path -LiteralPath $TempDat -PathType Leaf)) {
            Remove-Item -LiteralPath $TempDat -Force -ErrorAction SilentlyContinue
        }
    }
    return $ZipPath
}

function Publish-Poe2RestoreBaseline {
    param([Parameter(Mandatory = $true)][string]$Source)

    Copy-Poe2FileAtomically -Source $Source -Destination $RestoreOutZip | Out-Null
    if ($NoInstall) {
        return (Resolve-Path -LiteralPath $RestoreOutZip).Path
    }
    New-Item -ItemType Directory -Force -Path $PersistentRestoreDir | Out-Null
    Copy-Poe2FileAtomically -Source $RestoreOutZip -Destination $PersistentLogicalRestoreZip | Out-Null
    Assert-Poe2LogicalRestoreManifest -ZipPath $PersistentLogicalRestoreZip -InstallInfo $InstallInfo | Out-Null
    return (Resolve-Path -LiteralPath $PersistentLogicalRestoreZip).Path
}

function Test-RestoreZipUsable {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    try {
        Assert-RestoreZip $Path
        return $true
    }
    catch {
        return $false
    }
}

function New-CurrentTargetRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$SourceZip,
        [Parameter(Mandatory = $true)][string]$OutputZip
    )

    Assert-RestoreZip $SourceZip

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $SourceArchive = [System.IO.Compression.ZipFile]::OpenRead($SourceZip)
    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputZip), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $TargetArchive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Copy-ZipEntry -SourceArchive $SourceArchive -TargetArchive $TargetArchive -EntryName $InstallInfo.TcBaseItemsPath -Required | Out-Null
            if ($GameMode -ne "Bundles2") {
                if ($SupportsUniqueWords) {
                    Copy-ZipEntry -SourceArchive $SourceArchive -TargetArchive $TargetArchive -EntryName $TcWordsPath | Out-Null
                }
                Copy-ZipEntry -SourceArchive $SourceArchive -TargetArchive $TargetArchive -EntryName $InstallInfo.TcEndgameMapsPath | Out-Null
            }
        }
        finally {
            $TargetArchive.Dispose()
        }
        Get-Poe2ZipEntryCrc32Map -Path $TempZip | Out-Null
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputZip | Out-Null
    }
    finally {
        $SourceArchive.Dispose()
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }

    return (Resolve-Path -LiteralPath $OutputZip).Path
}

function Add-CleanCurrentWordsToRestoreZip {
    param([Parameter(Mandatory = $true)][string]$ZipPath)

    if ($GameMode -ne "Bundles2" -or -not $SupportsUniqueWords) {
        return $ZipPath
    }

    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_restore_words_", [Guid]::NewGuid().ToString("N")))
    $CurrentWords = Join-Path $TempDir "words.current.datc64"
    $CleanWords = Join-Path $TempDir "words.clean.datc64"
    $Log = Join-Path $TempDir "extract.log"
    try {
        New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $TcWordsPath $CurrentWords *> $Log
        if ($LASTEXITCODE -ne 0) {
            throw "无法读取当前 Words 以生成安全还原条目。退出码：$LASTEXITCODE；日志：$Log"
        }
        if (-not (Test-WordsLookPatched $CurrentWords)) {
            return $ZipPath
        }

        Write-Host "当前 Words 仍有旧价格标记，正在从当前版本生成清理条目..." -ForegroundColor Yellow
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
            "--clean-words", $CurrentWords,
            "--clean-words-output", $CleanWords
        )
        if ($Result.ExitCode -ne 0) {
            throw "清理当前 Words 失败。退出码：$($Result.ExitCode)"
        }
        if (-not (Test-Path -LiteralPath $CleanWords -PathType Leaf) -or (Test-WordsLookPatched $CleanWords)) {
            throw "清理后的 Words 校验失败，拒绝继续还原。"
        }
        Update-ZipEntryFromFile -ZipPath $ZipPath -SourceFile $CleanWords -EntryName $TcWordsPath
        return $ZipPath
    }
    finally {
        if (Test-Path -LiteralPath $TempDir -PathType Container) {
            Remove-Item -LiteralPath $TempDir -Recurse -Force
        }
    }
}

function Add-CleanCurrentEndgameMapsToRestoreZip {
    param([Parameter(Mandatory = $true)][string]$ZipPath)

    if ($GameMode -ne "Bundles2") {
        return $ZipPath
    }

    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_restore_endgamemaps_", [Guid]::NewGuid().ToString("N")))
    $CurrentEndgameMaps = Join-Path $TempDir "endgamemaps.current.datc64"
    $CleanEndgameMaps = Join-Path $TempDir "endgamemaps.clean.datc64"
    $Report = Join-Path $TempDir "endgamemaps-clean.report.json"
    $Log = Join-Path $TempDir "extract.log"
    try {
        New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.TcEndgameMapsPath $CurrentEndgameMaps *> $Log
        if ($LASTEXITCODE -ne 0) {
            throw "无法读取当前 EndgameMaps 以补全还原包。退出码：$LASTEXITCODE；日志：$Log"
        }
        if (-not (Test-EndgameMapsLookPatched $CurrentEndgameMaps)) {
            return $ZipPath
        }

        Write-Host "当前 EndgameMaps 仍有旧岛屿提示，正在生成清理条目补全还原包..." -ForegroundColor Yellow
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"),
            "clean",
            "--source", $CurrentEndgameMaps,
            "--output-zip", $ZipPath,
            "--patched-dat", $CleanEndgameMaps,
            "--game-path", $InstallInfo.TcEndgameMapsPath,
            "--report", $Report
        )
        if ($Result.ExitCode -ne 0) {
            throw "清理当前 EndgameMaps 失败。退出码：$($Result.ExitCode)"
        }
        if (-not (Test-Path -LiteralPath $CleanEndgameMaps -PathType Leaf) -or (Test-EndgameMapsLookPatched $CleanEndgameMaps)) {
            throw "清理后的 EndgameMaps 校验失败，拒绝继续还原。"
        }
        if (-not (Test-ZipEntryExists -ZipPath $ZipPath -EntryName $InstallInfo.TcEndgameMapsPath)) {
            throw "清理后的 EndgameMaps 没有写入还原安装包。"
        }
        return $ZipPath
    }
    finally {
        if (Test-Path -LiteralPath $TempDir -PathType Container) {
            Remove-Item -LiteralPath $TempDir -Recurse -Force
        }
    }
}

function Get-RestoreZipCandidates {
    $Paths = New-Object System.Collections.Generic.List[string]
    foreach ($Name in (Get-Poe2RestorePatchZipCandidateNames -InstallInfo $InstallInfo)) {
        $Paths.Add((Join-Path $PersistentRestoreDir $Name))
        $Paths.Add((Join-Path $RestoreOutDir $Name))
        $Paths.Add((Join-Path $RepoRoot $Name))
        $GamePatchRoot = Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)
        $Paths.Add((Join-Path $GamePatchRoot $Name))
        $Paths.Add((Join-Path $GamePatchRoot "output\restore\$Name"))
    }

    $Seen = @{}
    foreach ($Path in $Paths) {
        $FullPath = [System.IO.Path]::GetFullPath($Path)
        $Key = $FullPath.ToLowerInvariant()
        if (-not $Seen.ContainsKey($Key)) {
            $Seen[$Key] = $true
            $FullPath
        }
    }
}

function Get-PhysicalRestoreZipCandidates {
    $Names = @(Get-Poe2PhysicalRestorePatchZipCandidateNames -InstallInfo $InstallInfo)

    $SearchRoots = New-Object System.Collections.Generic.List[string]
    foreach ($Root in @(
        (Join-Path $Poe2Dir ".poe2-price-patch"),
        $RestoreOutDir,
        $RepoRoot,
        $Poe2Dir,
        (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)),
        (Join-Path (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)) "output\restore")
    )) {
        if (-not [string]::IsNullOrWhiteSpace($Root)) {
            $SearchRoots.Add($Root)
        }
    }

    if (Test-Path -LiteralPath $Poe2Dir -PathType Container) {
        foreach ($Directory in @(Get-ChildItem -LiteralPath $Poe2Dir -Directory -ErrorAction SilentlyContinue)) {
            $SearchRoots.Add($Directory.FullName)
            $SearchRoots.Add((Join-Path $Directory.FullName "output\restore"))
        }
    }

    $SeenPaths = @{}
    foreach ($Name in $Names) {
        foreach ($Root in $SearchRoots) {
            if ([string]::IsNullOrWhiteSpace($Root)) {
                continue
            }
            $Path = [System.IO.Path]::GetFullPath((Join-Path $Root $Name))
            $Key = $Path.ToLowerInvariant()
            if (-not $SeenPaths.ContainsKey($Key)) {
                $SeenPaths[$Key] = $true
                $Path
            }
        }
    }
}

function Assert-PhysicalRestoreZip {
    param([string]$Path)

    Assert-Poe2PhysicalRestoreZip -Path $Path -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo | Out-Null
}

function Restore-PhysicalBundles2 {
    param([string]$Path)

    $Manifest = Assert-Poe2PhysicalRestoreZip -Path $Path -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo
    $Bundles2Root = (Resolve-Path -LiteralPath $Bundles2Paths.Bundles2Dir).Path
    $GameRoot = (Resolve-Path -LiteralPath $Poe2Dir).Path
    Assert-Poe2PathInside -Path $Bundles2Root -Root $GameRoot -Message "Refusing to restore outside game folder" | Out-Null

    $TransactionId = [Guid]::NewGuid().ToString("N")
    $StageRoot = Join-Path $Bundles2Root (".poe2-physical-restore-stage-" + $TransactionId)
    $StageData = Join-Path $StageRoot "data"
    $RollbackRoot = Join-Path $Bundles2Root (".poe2-physical-restore-rollback-" + $TransactionId)
    $RollbackFiles = Join-Path $RollbackRoot "files"
    $RollbackLib = Join-Path $RollbackRoot "LibGGPK3"
    Assert-Poe2PathInside -Path $StageRoot -Root $Bundles2Root -Message "Refusing unsafe restore staging path" | Out-Null
    Assert-Poe2PathInside -Path $RollbackRoot -Root $Bundles2Root -Message "Refusing unsafe restore rollback path" | Out-Null

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $CrcByName = Get-Poe2ZipEntryCrc32Map -Path $Path
    $RestoreFileByPath = @{}
    if ([int]$Manifest.version -eq 2) {
        foreach ($Descriptor in @($Manifest.restore_files)) {
            $RestoreFileByPath[([string]$Descriptor.path).ToLowerInvariant()] = $Descriptor
        }
    }

    $Entries = @()
    $TopLevelEntries = @()
    $OriginalTopLevel = @{}
    $MutatedTopLevel = @{}
    $LibMovedToRollback = $false
    $StagedLibInstalled = $false
    $MutationStarted = $false
    $PreserveRollback = $false
    try {
        New-Item -ItemType Directory -Force -Path $StageData | Out-Null
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try {
            $Entries = @($Archive.Entries | Where-Object { $_.FullName -like "Bundles2/*" -and -not [string]::IsNullOrEmpty($_.Name) })
            $TopLevelEntries = @($Entries | Where-Object { $_.FullName -notlike "Bundles2/LibGGPK3/*" })
            foreach ($Entry in $Entries) {
                $Relative = $Entry.FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
                $StagedFile = [System.IO.Path]::GetFullPath((Join-Path $StageData $Relative))
                Assert-Poe2PathInside -Path $StagedFile -Root $StageData -Message "Refusing to stage path outside restore transaction" | Out-Null
                $StagedDir = Split-Path -Parent $StagedFile
                New-Item -ItemType Directory -Force -Path $StagedDir | Out-Null
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $StagedFile, $false)

                $StagedInfo = Get-Item -LiteralPath $StagedFile -ErrorAction Stop
                if ([long]$StagedInfo.Length -ne [long]$Entry.Length) {
                    throw "Physical restore staging length check failed: $($Entry.FullName)"
                }
                $ActualCrc = Get-Poe2FileCrc32Hex -Path $StagedFile
                $ExpectedCrc = [string]$CrcByName[[string]$Entry.FullName]
                if (-not $ActualCrc.Equals($ExpectedCrc, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Physical restore staging CRC check failed: $($Entry.FullName)"
                }
                if ([int]$Manifest.version -eq 2) {
                    $Descriptor = $RestoreFileByPath[([string]$Entry.FullName).ToLowerInvariant()]
                    $ActualSha = Get-Poe2Sha256Hex -Path $StagedFile
                    if ($null -eq $Descriptor -or -not $ActualSha.Equals([string]$Descriptor.sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
                        throw "Physical restore staging SHA256 check failed: $($Entry.FullName)"
                    }
                }
            }
        }
        finally {
            $Archive.Dispose()
        }

        # Snapshot every file that can be replaced before the first target mutation.
        New-Item -ItemType Directory -Force -Path $RollbackFiles | Out-Null
        foreach ($Entry in $TopLevelEntries) {
            $Relative = $Entry.FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            $Target = [System.IO.Path]::GetFullPath((Join-Path $Bundles2Root $Relative))
            Assert-Poe2PathInside -Path $Target -Root $Bundles2Root -Message "Refusing to back up path outside Bundles2" | Out-Null
            $Key = $Relative.ToLowerInvariant()
            $Existed = Test-Path -LiteralPath $Target -PathType Leaf
            $Backup = Join-Path $RollbackFiles $Relative
            $SnapshotLength = [long]0
            $SnapshotSha256 = ""
            if ($Existed) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
                [System.IO.File]::Copy($Target, $Backup, $false)
                $OriginalInfo = Get-Item -LiteralPath $Target
                $BackupInfo = Get-Item -LiteralPath $Backup
                $SnapshotLength = [long]$OriginalInfo.Length
                $SnapshotSha256 = Get-Poe2Sha256Hex -Path $Target
                if ($OriginalInfo.Length -ne $BackupInfo.Length -or $SnapshotSha256 -ne (Get-Poe2Sha256Hex -Path $Backup)) {
                    throw "Physical restore rollback backup verification failed: $Relative"
                }
            }
            $OriginalTopLevel[$Key] = [pscustomobject]@{
                EntryName = [string]$Entry.FullName
                Relative = $Relative
                Target = $Target
                Existed = $Existed
                Backup = $Backup
                SnapshotLength = $SnapshotLength
                SnapshotSha256 = $SnapshotSha256
            }
        }

        # Re-check after the potentially long staging/backup phase, before changing the game.
        Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Poe2Dir | Out-Null
        Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin

        if ($env:POE2_PATCH_TEST_MUTATE_TOP_LEVEL_BEFORE_WRITE -eq "1" -and $TopLevelEntries.Count -gt 0) {
            $TestRelative = $TopLevelEntries[0].FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            [System.IO.File]::WriteAllText((Join-Path $Bundles2Root $TestRelative), "EXTERNAL-TOP-LEVEL")
        }

        $LibDir = Join-Path $Bundles2Root "LibGGPK3"
        if (Test-Path -LiteralPath $LibDir -PathType Container) {
            $ResolvedLibDir = (Resolve-Path -LiteralPath $LibDir).Path
            Assert-Poe2PathInside -Path $ResolvedLibDir -Root $Bundles2Root -Message "Refusing to move unexpected LibGGPK3 path" | Out-Null
            New-Item -ItemType Directory -Force -Path $RollbackRoot | Out-Null
            [System.IO.Directory]::Move($ResolvedLibDir, $RollbackLib)
            $LibMovedToRollback = $true
        }
        $MutationStarted = $true

        if ($env:POE2_PATCH_TEST_RESTORE_FAILURE -eq "after-lib-backup") {
            throw "Injected physical restore failure after LibGGPK3 rollback backup."
        }

        if ($env:POE2_PATCH_TEST_CREATE_CONCURRENT_LIB -eq "1") {
            New-Item -ItemType Directory -Force -Path $LibDir | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $LibDir "external.bundle.bin"), "EXTERNAL-LIB")
        }

        $StagedLib = Join-Path $StageData "LibGGPK3"
        if (Test-Path -LiteralPath $StagedLib -PathType Container) {
            [System.IO.Directory]::Move($StagedLib, $LibDir)
            $StagedLibInstalled = $true
        }

        $ReplacedCount = 0
        foreach ($Entry in $TopLevelEntries) {
            $Relative = $Entry.FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            $StagedFile = Join-Path $StageData $Relative
            $Target = [System.IO.Path]::GetFullPath((Join-Path $Bundles2Root $Relative))
            Assert-Poe2PathInside -Path $Target -Root $Bundles2Root -Message "Refusing to restore path outside Bundles2" | Out-Null
            $Snapshot = $OriginalTopLevel[$Relative.ToLowerInvariant()]
            $TargetExistsNow = Test-Path -LiteralPath $Target -PathType Leaf
            if ([bool]$Snapshot.Existed) {
                if (-not $TargetExistsNow) {
                    throw "Physical restore target disappeared after its rollback snapshot was created: $Relative"
                }
                $CurrentInfo = Get-Item -LiteralPath $Target -ErrorAction Stop
                if ([long]$CurrentInfo.Length -ne [long]$Snapshot.SnapshotLength -or
                    (Get-Poe2Sha256Hex -Path $Target) -ne [string]$Snapshot.SnapshotSha256) {
                    throw "Physical restore target changed after its rollback snapshot was created: $Relative"
                }
            }
            elseif ($TargetExistsNow) {
                throw "Physical restore target appeared after its rollback snapshot was created: $Relative"
            }
            Move-Poe2FileAtomically -Source $StagedFile -Destination $Target | Out-Null
            $MutatedTopLevel[$Relative.ToLowerInvariant()] = $true
            $ReplacedCount += 1
            if ($ReplacedCount -eq 1 -and $env:POE2_PATCH_TEST_RESTORE_FAILURE -eq "after-first-file") {
                throw "Injected physical restore failure after the first file replacement."
            }
        }

        foreach ($Entry in $Entries) {
            $Relative = $Entry.FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            $Target = [System.IO.Path]::GetFullPath((Join-Path $Bundles2Root $Relative))
            Assert-Poe2PathInside -Path $Target -Root $Bundles2Root -Message "Refusing to verify path outside Bundles2" | Out-Null
            if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
                throw "Physical restore write verification found a missing file: $($Entry.FullName)"
            }
            $TargetInfo = Get-Item -LiteralPath $Target
            $ActualCrc = Get-Poe2FileCrc32Hex -Path $Target
            if ($TargetInfo.Length -ne $Entry.Length -or -not $ActualCrc.Equals([string]$CrcByName[[string]$Entry.FullName], [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Physical restore write CRC verification failed: $($Entry.FullName)"
            }
            if ([int]$Manifest.version -eq 2) {
                $Descriptor = $RestoreFileByPath[([string]$Entry.FullName).ToLowerInvariant()]
                if ((Get-Poe2Sha256Hex -Path $Target) -ne [string]$Descriptor.sha256) {
                    throw "Physical restore write SHA256 verification failed: $($Entry.FullName)"
                }
            }
        }

        if ($env:POE2_PATCH_TEST_CREATE_CONCURRENT_OPTIONAL_INDEX -eq "1") {
            [System.IO.File]::WriteAllText((Join-Path $Bundles2Root "_.index.high.bin"), "EXTERNAL-OPTIONAL-INDEX")
        }

        $KnownTopLevelNames = @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")
        $ExpectedTopLevelByName = @{}
        foreach ($Entry in $TopLevelEntries) {
            $ExpectedName = $Entry.FullName.Substring("Bundles2/".Length).Replace("\", "/").ToLowerInvariant()
            $ExpectedTopLevelByName[$ExpectedName] = $true
        }
        $ActualTopLevelNames = @($KnownTopLevelNames | Where-Object {
                Test-Path -LiteralPath (Join-Path $Bundles2Root $_) -PathType Leaf
            } | ForEach-Object { $_.ToLowerInvariant() })
        if ($ActualTopLevelNames.Count -ne $ExpectedTopLevelByName.Count) {
            throw "Physical restore top-level index file-set verification failed: expected $($ExpectedTopLevelByName.Count), actual $($ActualTopLevelNames.Count)"
        }
        foreach ($ActualName in $ActualTopLevelNames) {
            if (-not $ExpectedTopLevelByName.ContainsKey($ActualName)) {
                throw "Physical restore found an unexpected concurrent top-level index file: $ActualName"
            }
        }

        $ExpectedLibEntries = @($Entries | Where-Object { $_.FullName -like "Bundles2/LibGGPK3/*" })
        $ActualLibFiles = if (Test-Path -LiteralPath $LibDir -PathType Container) {
            @(Get-ChildItem -LiteralPath $LibDir -Recurse -File -ErrorAction Stop)
        }
        else {
            @()
        }
        if ($ActualLibFiles.Count -ne $ExpectedLibEntries.Count) {
            throw "Physical restore LibGGPK3 file-set verification failed: expected $($ExpectedLibEntries.Count), actual $($ActualLibFiles.Count)"
        }
        $ExpectedLibByRelative = @{}
        foreach ($Entry in $ExpectedLibEntries) {
            $Relative = $Entry.FullName.Substring("Bundles2/LibGGPK3/".Length).Replace("\", "/").ToLowerInvariant()
            $ExpectedLibByRelative[$Relative] = $Entry
        }
        if ($ActualLibFiles.Count -gt 0) {
            $LibPrefix = [System.IO.Path]::GetFullPath($LibDir).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            ) + [System.IO.Path]::DirectorySeparatorChar
            foreach ($File in $ActualLibFiles) {
                $Relative = $File.FullName.Substring($LibPrefix.Length).Replace("\", "/").ToLowerInvariant()
                if (-not $ExpectedLibByRelative.ContainsKey($Relative)) {
                    throw "Physical restore found an unexpected concurrent LibGGPK3 file: $Relative"
                }
            }
        }
    }
    catch {
        $OriginalError = $_
        if ($MutationStarted) {
            $RollbackErrors = New-Object System.Collections.Generic.List[string]
            foreach ($State in $OriginalTopLevel.Values) {
                if (-not $MutatedTopLevel.ContainsKey(([string]$State.Relative).ToLowerInvariant())) {
                    continue
                }
                try {
                    if (-not (Test-Path -LiteralPath ([string]$State.Target) -PathType Leaf)) {
                        if ([bool]$State.Existed) {
                            $RollbackErrors.Add("$($State.Relative): target disappeared after this transaction changed it; original is preserved at $($State.Backup)")
                        }
                        continue
                    }
                    $CurrentCrc = Get-Poe2FileCrc32Hex -Path ([string]$State.Target)
                    $AppliedCrc = [string]$CrcByName[[string]$State.EntryName]
                    if (-not $CurrentCrc.Equals($AppliedCrc, [System.StringComparison]::OrdinalIgnoreCase)) {
                        $RollbackErrors.Add("$($State.Relative): target changed concurrently; current file was left untouched and original is preserved at $($State.Backup)")
                        continue
                    }
                    if ([bool]$State.Existed) {
                        $RestoreTemp = Join-Path $Bundles2Root ([string]::Concat(".", (Split-Path -Leaf $State.Target), ".rollback-", [Guid]::NewGuid().ToString("N")))
                        [System.IO.File]::Copy([string]$State.Backup, $RestoreTemp, $false)
                        Move-Poe2FileAtomically -Source $RestoreTemp -Destination ([string]$State.Target) | Out-Null
                    }
                    elseif (Test-Path -LiteralPath ([string]$State.Target) -PathType Leaf) {
                        $FailedFilesDir = Join-Path $RollbackRoot "failed-files"
                        New-Item -ItemType Directory -Force -Path $FailedFilesDir | Out-Null
                        $FailedTarget = Join-Path $FailedFilesDir ([string]$State.Relative)
                        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FailedTarget) | Out-Null
                        [System.IO.File]::Move([string]$State.Target, $FailedTarget)
                    }
                }
                catch {
                    $RollbackErrors.Add("$($State.Relative): $($_.Exception.Message)")
                }
            }

            try {
                $InstalledLibOwnedByTransaction = $StagedLibInstalled
                if ($StagedLibInstalled -and (Test-Path -LiteralPath $LibDir -PathType Container)) {
                    $ExpectedLibEntries = @($Entries | Where-Object { $_.FullName -like "Bundles2/LibGGPK3/*" })
                    $CurrentLibFiles = @(Get-ChildItem -LiteralPath $LibDir -Recurse -File -ErrorAction Stop)
                    if ($CurrentLibFiles.Count -ne $ExpectedLibEntries.Count) {
                        $InstalledLibOwnedByTransaction = $false
                    }
                    if ($InstalledLibOwnedByTransaction) {
                        foreach ($ExpectedEntry in $ExpectedLibEntries) {
                            $LibRelative = $ExpectedEntry.FullName.Substring("Bundles2/LibGGPK3/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
                            $CurrentLibFile = [System.IO.Path]::GetFullPath((Join-Path $LibDir $LibRelative))
                            Assert-Poe2PathInside -Path $CurrentLibFile -Root $LibDir -Message "Refusing unsafe LibGGPK3 rollback verification path" | Out-Null
                            if (-not (Test-Path -LiteralPath $CurrentLibFile -PathType Leaf)) {
                                $InstalledLibOwnedByTransaction = $false
                                break
                            }
                            $CurrentLibCrc = Get-Poe2FileCrc32Hex -Path $CurrentLibFile
                            $ExpectedLibCrc = [string]$CrcByName[[string]$ExpectedEntry.FullName]
                            if (-not $CurrentLibCrc.Equals($ExpectedLibCrc, [System.StringComparison]::OrdinalIgnoreCase)) {
                                $InstalledLibOwnedByTransaction = $false
                                break
                            }
                        }
                    }
                    if (-not $InstalledLibOwnedByTransaction) {
                        $RollbackErrors.Add("LibGGPK3: directory changed concurrently; current data was left untouched and the original is preserved at $RollbackLib")
                    }
                }
                elseif ($StagedLibInstalled -and $LibMovedToRollback) {
                    $InstalledLibOwnedByTransaction = $false
                    $RollbackErrors.Add("LibGGPK3: installed directory disappeared concurrently; original is preserved at $RollbackLib")
                }

                if ($InstalledLibOwnedByTransaction -and (Test-Path -LiteralPath $LibDir -PathType Container)) {
                    $FailedLib = Join-Path $RollbackRoot "failed-LibGGPK3"
                    if (Test-Path -LiteralPath $FailedLib) {
                        Remove-Item -LiteralPath $FailedLib -Recurse -Force
                    }
                    [System.IO.Directory]::Move($LibDir, $FailedLib)
                }
                if ($LibMovedToRollback -and (Test-Path -LiteralPath $RollbackLib -PathType Container)) {
                    if (Test-Path -LiteralPath $LibDir -PathType Container) {
                        $RollbackErrors.Add("LibGGPK3: target appeared concurrently; original is preserved at $RollbackLib")
                    }
                    else {
                        [System.IO.Directory]::Move($RollbackLib, $LibDir)
                    }
                }
            }
            catch {
                $RollbackErrors.Add("LibGGPK3: $($_.Exception.Message)")
            }

            if ($RollbackErrors.Count -gt 0) {
                $PreserveRollback = $true
                throw "Physical restore failed and rollback was incomplete. Original error: $($OriginalError.Exception.Message). Rollback errors: $([string]::Join('; ', $RollbackErrors))"
            }
        }
        throw $OriginalError
    }
    finally {
        if (Test-Path -LiteralPath $StageRoot -PathType Container) {
            Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not $PreserveRollback -and (Test-Path -LiteralPath $RollbackRoot -PathType Container)) {
            Remove-Item -LiteralPath $RollbackRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-Bundles2RestoreApplied {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string[]]$EntryNames
    )

    Resolve-BundleExtractor
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $EntriesToVerify = New-Object System.Collections.Generic.List[string]
    $Seen = @{}
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($Name in $EntryNames) {
            if ([string]::IsNullOrWhiteSpace($Name)) {
                continue
            }
            $Normalized = $Name.Replace("\", "/")
            $Key = $Normalized.ToLowerInvariant()
            if (-not $Seen.ContainsKey($Key) -and $null -ne $Archive.GetEntry($Normalized)) {
                $Seen[$Key] = $true
                $EntriesToVerify.Add($Normalized)
            }
        }
    }
    finally {
        $Archive.Dispose()
    }
    if ($EntriesToVerify.Count -eq 0) {
        throw "Bundles2 restore verification found no target entries in $ZipPath"
    }

    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_verify_bundle_restore_", [Guid]::NewGuid().ToString("N")))
    $RequestListPath = Join-Path $TempDir "verify-files.txt"
    $ExtractDir = Join-Path $TempDir "extracted"
    $VerifyLog = Join-Path $TempDir "verify.log"
    try {
        New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
        [System.IO.File]::WriteAllLines(
            $RequestListPath,
            $EntriesToVerify.ToArray(),
            (New-Object System.Text.UTF8Encoding($false))
        )
        & $BundledBundleExtractorExe --extract-list $Bundles2Paths.IndexBin $RequestListPath $ExtractDir *> $VerifyLog
        if ($LASTEXITCODE -ne 0) {
            throw "Bundles2 restore read-back extraction failed. Exit code: $LASTEXITCODE. Log: $VerifyLog"
        }

        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            for ($Index = 0; $Index -lt $EntriesToVerify.Count; $Index++) {
                $EntryName = $EntriesToVerify[$Index]
                $ActualPath = Join-Path $ExtractDir ([string]::Format("{0:D6}.bin", $Index))
                Assert-File $ActualPath "restored $EntryName"
                $ZipEntry = $Archive.GetEntry($EntryName)
                $ExpectedIntegrity = Get-Poe2ZipEntryStreamIntegrity -Entry $ZipEntry
                $ActualInfo = Get-Item -LiteralPath $ActualPath
                if ([long]$ActualInfo.Length -ne [long]$ExpectedIntegrity.Length -or
                    (Get-Poe2Sha256Hex -Path $ActualPath) -ne [string]$ExpectedIntegrity.Sha256) {
                    throw "Bundles2 restore read-back content mismatch: $EntryName"
                }
            }
        }
        finally {
            $Archive.Dispose()
        }
        Write-Host "已读回校验 Bundles2 中的 $($EntriesToVerify.Count) 个还原文件。" -ForegroundColor Green
    }
    finally {
        if (Test-Path -LiteralPath $TempDir -PathType Container) {
            Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-BundleExtractor {
    if (-not (Test-Path -LiteralPath $BundledBundleExtractorExe -PathType Leaf)) {
        $script:BundledBundleExtractorExe = Join-Path $BundledInstallerDir "BundleExtractor\BundleExtractor.exe"
    }
    if (-not (Test-Path -LiteralPath $BundledBundleExtractorExe -PathType Leaf)) {
        $script:BundledBundleExtractorExe = Join-Path $CodeToolsRoot "BundleExtractor\BundleExtractor.exe"
    }
    if (-not (Test-Path -LiteralPath $BundledBundleExtractorExe -PathType Leaf)) {
        throw "Missing BundleExtractor.exe: $BundledBundleExtractorExe"
    }

    if (-not (Test-Path -LiteralPath $BundledOodleDll -PathType Leaf)) {
        $script:BundledOodleDll = Join-Path $BundledInstallerDir "BundleExtractor\oo2core.dll"
    }
    if (-not (Test-Path -LiteralPath $BundledOodleDll -PathType Leaf)) {
        $script:BundledOodleDll = Join-Path $CodeToolsRoot "BundleExtractor\oo2core.dll"
    }
    if (-not (Test-Path -LiteralPath $BundledOodleDll -PathType Leaf)) {
        throw "Missing oo2core.dll: $BundledOodleDll"
    }

    $ExtractorDir = Split-Path -Parent $BundledBundleExtractorExe
    $ExtractorOodle = Join-Path $ExtractorDir "oo2core.dll"
    if (-not (Test-Path -LiteralPath $ExtractorOodle -PathType Leaf) -and (Test-Path -LiteralPath $BundledOodleDll -PathType Leaf)) {
        Copy-Item -LiteralPath $BundledOodleDll -Destination $ExtractorOodle -Force
    }
}

function Extract-CurrentGgpkBaseItemsForRestoreCheck {
    $LocalExtractorDll = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.dll"
    $LocalExtractorExe = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.exe"
    $FallbackExtractor = Join-Path $Poe2Dir "tiaoshi\extractor_tool\GGPKExtractor\bin\Release\net8.0-windows\GGPKExtractor.exe"
    $ExtractorUsesDotnet = $false
    if (Test-Path -LiteralPath $LocalExtractorDll -PathType Leaf) {
        $Extractor = $LocalExtractorDll
        $ExtractorUsesDotnet = $true
    }
    elseif (Test-Path -LiteralPath $LocalExtractorExe -PathType Leaf) {
        $Extractor = $LocalExtractorExe
    }
    else {
        $Extractor = $FallbackExtractor
    }
    Assert-File $Extractor "GGPKExtractor"

    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_restore_check_", [Guid]::NewGuid().ToString("N")))
    $ExtractLog = Join-Path $TempDir "extract.log"
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
    if ($ExtractorUsesDotnet) {
        $ExtractorResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($Extractor, $ContentGgpk, $TempDir) -Quiet
        $ExtractorResult.Text | Out-File -LiteralPath $ExtractLog -Encoding UTF8
        $ExtractorExitCode = $ExtractorResult.ExitCode
        $ExtractorText = $ExtractorResult.Text
    }
    else {
        & $Extractor $ContentGgpk $TempDir *> $ExtractLog
        $ExtractorExitCode = $LASTEXITCODE
        $ExtractorText = if (Test-Path -LiteralPath $ExtractLog -PathType Leaf) {
            Get-Content -LiteralPath $ExtractLog -Raw -Encoding UTF8
        }
        else {
            ""
        }
    }
    if ($ExtractorExitCode -ne 0) {
        if (Test-GgpkExtractorMissingRuntimeDependency -Text $ExtractorText) {
            throw "GGPKExtractor missing VC runtime dependency. Exit code: $ExtractorExitCode. Log: $ExtractLog"
        }
        throw "Failed to extract current BaseItemTypes for compatibility check. Log: $ExtractLog"
    }

    $Extracted = Join-Path $TempDir ("data\" + $InstallInfo.LanguageFileSlug)
    Assert-File $Extracted "current BaseItemTypes"
    return [pscustomobject]@{
        Dir = $TempDir
        Dat = $Extracted
    }
}

function Assert-GgpkRestoreApplied {
    param([Parameter(Mandatory = $true)][string]$ZipPath)

    $Current = $null
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Current = Extract-CurrentGgpkBaseItemsForRestoreCheck
        $Targets = [ordered]@{
            $InstallInfo.TcBaseItemsPath = $InstallInfo.LanguageFileSlug
            $InstallInfo.TcWordsPath = $InstallInfo.WordsFileSlug
            $InstallInfo.TcEndgameMapsPath = $InstallInfo.EndgameMapsFileSlug
        }
        $Verified = 0
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            foreach ($EntryName in $Targets.Keys) {
                $Entry = $Archive.GetEntry(([string]$EntryName).Replace("\", "/"))
                if ($null -eq $Entry) {
                    continue
                }
                $ExpectedPath = Join-Path $Current.Dir ([string]::Concat("expected_", [Guid]::NewGuid().ToString("N"), ".datc64"))
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $ExpectedPath, $true)
                $ActualPath = Join-Path $Current.Dir ("data\" + [string]$Targets[$EntryName])
                Assert-File $ActualPath "GGPK read-back $EntryName"
                $ExpectedItem = Get-Item -LiteralPath $ExpectedPath
                $ActualItem = Get-Item -LiteralPath $ActualPath
                if ($ExpectedItem.Length -ne $ActualItem.Length) {
                    throw "GGPK 还原后读回长度不一致：$EntryName"
                }
                $ExpectedHash = (Get-FileHash -LiteralPath $ExpectedPath -Algorithm SHA256).Hash
                $ActualHash = (Get-FileHash -LiteralPath $ActualPath -Algorithm SHA256).Hash
                if ($ExpectedHash -ne $ActualHash) {
                    throw "GGPK 还原后读回内容不一致：$EntryName"
                }
                $Verified += 1
            }
        }
        finally {
            $Archive.Dispose()
        }
        if ($Verified -eq 0) {
            throw "GGPK 还原读回校验找不到任何目标 DAT 条目。"
        }
        Write-Host "已读回校验 GGPK 中的 $Verified 个还原文件。" -ForegroundColor Green
    }
    finally {
        if ($null -ne $Current -and (Test-Path -LiteralPath $Current.Dir -PathType Container)) {
            Remove-Item -LiteralPath $Current.Dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-GgpkRestorePatch {
    param([Parameter(Mandatory = $true)][string]$ZipPath)

    Push-Location -LiteralPath $BundledInstallerDir
    try {
        $InstallerResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledPatchDll, $ContentGgpk, $ZipPath) -InputText ""
        if ($InstallerResult.ExitCode -ne 0 -or $InstallerResult.Text -match 'Exception|Unhandled|錯誤|错误|失敗|失败') {
            if (Test-GgpkExtractorMissingRuntimeDependency -Text $InstallerResult.Text) {
                throw "GGPKExtractor missing VC runtime dependency. Exit code: $($InstallerResult.ExitCode). Log: restore-install"
            }
            throw "Restore installer failed. Exit code: $($InstallerResult.ExitCode)"
        }
    }
    finally {
        Pop-Location
    }
}

$PublicToolsRoot = Join-Path $RepoRoot "tools"
$InstallInfo = Get-Poe2InstallInfo -Poe2Dir $Poe2Dir
$GameMode = $InstallInfo.Mode
$ContentGgpk = Join-Path $Poe2Dir "Content.ggpk"
$Bundles2Paths = Get-Bundles2Paths -Poe2Dir $Poe2Dir
$BundledInstallerDir = Join-Path $RepoRoot (Get-Poe2PatchName "InstallerDir")
$BundledPatchDll = Join-Path $BundledInstallerDir "PatchBundledGGPK3.dll"
$BundledPatchRuntimeConfig = Join-Path $BundledInstallerDir "PatchBundledGGPK3.runtimeconfig.json"
$BundledBundlePatchExe = Join-Path $BundledInstallerDir "PatchBundle3.exe"
$BundledBundlePatchDll = Join-Path $BundledInstallerDir "PatchBundle3.dll"
$BundledBundleExtractorExe = Join-Path $PublicToolsRoot "BundleExtractor\BundleExtractor.exe"
$BundledOodleDll = Join-Path $PublicToolsRoot "BundleExtractor\oo2core.dll"
$RestoreZipName = Get-Poe2FixedRestorePatchZipName -InstallInfo $InstallInfo
$PhysicalRestoreZipName = Get-Poe2FixedPhysicalRestorePatchZipName -InstallInfo $InstallInfo
$RestoreOutputKey = Get-Poe2PatchOutputKey -Poe2Dir $Poe2Dir
$RestoreOutDir = Join-Path $RepoRoot ("output\restore\" + $RestoreOutputKey)
$RestoreOutZip = Join-Path $RestoreOutDir $RestoreZipName
$PhysicalRestoreOutZip = Join-Path $RestoreOutDir $PhysicalRestoreZipName
$PatchFolderRestoreZip = Join-Path $RepoRoot $RestoreZipName
$PatchFolderPhysicalRestoreZip = Join-Path $RepoRoot $PhysicalRestoreZipName
$PersistentRestoreDir = Join-Path $Poe2Dir ".poe2-price-patch"
$PersistentLogicalRestoreZip = Join-Path $PersistentRestoreDir $RestoreZipName
$PersistentPhysicalRestoreZip = Join-Path $PersistentRestoreDir $PhysicalRestoreZipName
$CleanDat = Join-Path $RepoRoot ("output\dat_files_latest\data\" + $InstallInfo.LanguageFileSlug)
$TcWordsPath = $InstallInfo.TcWordsPath
$SupportsUniqueWords = Test-Poe2UniqueWordsSupported -WordsPath $TcWordsPath

Write-Host "POE2 物价补丁还原器 $script:PatchVersion" -ForegroundColor Green
Write-Host "Game dir : $Poe2Dir"
Write-Host "目录选择：$(if ($GameDirectorySelectionMode -eq 'manual') { '手动选择' } else { '自动识别' })" -ForegroundColor Cyan
Write-Host "Patch dir: $RepoRoot"
Write-Host "Detected : $($InstallInfo.DisplayName)" -ForegroundColor Cyan
Write-Host "Mode     : $GameMode" -ForegroundColor Cyan
Write-Host "Language : $($InstallInfo.LanguageName) ($($InstallInfo.ConfigLanguage))" -ForegroundColor Cyan
Write-Host "Target   : $($InstallInfo.TcBaseItemsPath)" -ForegroundColor Cyan
Write-Host "EndgameMaps: $($InstallInfo.TcEndgameMapsPath)" -ForegroundColor Cyan
if ($InstallInfo.LanguageDefaulted) {
    Write-Warning $InstallInfo.LanguageDefaultReason
}

if ($GameMode -eq "GGPK") {
    Assert-File $ContentGgpk "Content.ggpk"
    Assert-File $BundledPatchDll "PatchBundledGGPK3.dll"
    Assert-File $BundledPatchRuntimeConfig "PatchBundledGGPK3.runtimeconfig.json"
}
else {
    Assert-File $Bundles2Paths.IndexBin "Bundles2 _.index.bin"
}

if ($GameMode -eq "Bundles2" -and -not $NoInstall) {
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin
}

if ($GameMode -eq "Bundles2") {
    $RequestedPhysicalRestoreZip = $PhysicalRestoreZip
    $PhysicalRestoreZip = ""
    $UsablePhysicalRestoreZips = New-Object System.Collections.Generic.List[string]
    $PhysicalCandidates = if ([string]::IsNullOrWhiteSpace($RequestedPhysicalRestoreZip)) {
        @(Get-PhysicalRestoreZipCandidates)
    }
    else {
        @($RequestedPhysicalRestoreZip)
    }
    foreach ($Candidate in $PhysicalCandidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            try {
                Assert-PhysicalRestoreZip $Candidate
                $UsablePhysicalRestoreZips.Add((Resolve-Path -LiteralPath $Candidate).Path)
            }
            catch {
                Write-Warning "Ignore invalid physical restore zip: $Candidate ($($_.Exception.Message))"
            }
        }
    }
    if ($UsablePhysicalRestoreZips.Count -gt 0) {
        $CandidatesByHash = @($UsablePhysicalRestoreZips | Group-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
        if ($CandidatesByHash.Count -gt 1) {
            $CandidateList = [string]::Join("；", $UsablePhysicalRestoreZips.ToArray())
            throw "找到多个内容不同、但都能通过校验的真实还原包，无法安全判断应还原哪一个：$CandidateList"
        }
        $PhysicalRestoreZip = @($UsablePhysicalRestoreZips | Sort-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } -Descending)[0]
    }
    elseif (-not [string]::IsNullOrWhiteSpace($RequestedPhysicalRestoreZip)) {
        throw "指定的真实还原包不可用，拒绝改用其它还原路径：$RequestedPhysicalRestoreZip"
    }

    if ([string]::IsNullOrWhiteSpace($PhysicalRestoreZip)) {
        Write-Warning "Missing physical restore zip: $PhysicalRestoreZipName"
        Write-Warning "Bundles2 restore will fall back to PatchBundle3. If it shows 'Failed to create mutex', verify or repair game files once, then run one-key update to create the physical restore package."
    }
    else {
        Write-Step "Restore physical Bundles2 files"
        Write-Host "Restore: $PhysicalRestoreZip"
        if ($NoInstall) {
            Write-Host "NoInstall enabled. Restore package verified; game files were not changed." -ForegroundColor Yellow
            return
        }
        Restore-PhysicalBundles2 -Path $PhysicalRestoreZip
        Write-Host "Physical Bundles2 restore complete." -ForegroundColor Green
        return
    }
}

# Physical Bundles2 restoration only needs file APIs.  Defer extractor and
# runtime checks until the logical fallback is actually selected.
if ($GameMode -eq "Bundles2") {
    Resolve-BundleExtractor
}
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot

function Ensure-CleanBaseItemForRestore {
    if ($GameMode -ne "Bundles2" -and (Test-Path -LiteralPath $CleanDat -PathType Leaf)) {
        if (-not (Test-BaseItemsLookPatched $CleanDat)) {
            return $CleanDat
        }
        Write-Host "Cached BaseItemTypes looks patched. Re-extracting from game files..." -ForegroundColor Yellow
    }

    if ($GameMode -eq "GGPK") {
        throw "No clean restore zip found. Run update once from a clean game state, or provide -RestoreZip."
    }

    Write-Step "Extract clean BaseItemTypes from Bundles2"
    $ExtractDir = Split-Path -Parent $CleanDat
    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null

    Write-Host "Extracting from: $($Bundles2Paths.IndexBin)"
    Write-Host "File: $($InstallInfo.TcBaseItemsPath)"
    Write-Host "Output: $CleanDat"

    $ExtractLog = Join-Path $ExtractDir ([string]::Concat("restore_extract_", [Guid]::NewGuid().ToString("N"), ".log"))
    & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.TcBaseItemsPath $CleanDat *> $ExtractLog
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract clean BaseItemTypes. Exit code: $LASTEXITCODE. Log: $ExtractLog"
    }

    if (Test-BaseItemsLookPatched $CleanDat) {
        Write-Host "Extracted BaseItemTypes contains price markers; compatibility will use the structure signature that ignores display-name pointers." -ForegroundColor Yellow
    }

    return $CleanDat
}

function New-Poe2RestoreBaselineFromCurrentGame {
    param([Parameter(Mandatory = $true)][string]$OutputZip)

    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe2_restore_self_heal_", [Guid]::NewGuid().ToString("N")))
    $CurrentGgpk = $null
    try {
        New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
        $CurrentBaseItems = Join-Path $TempRoot "baseitemtypes.current.datc64"
        $CurrentWords = Join-Path $TempRoot "words.current.datc64"
        $CurrentEndgameMaps = Join-Path $TempRoot "endgamemaps.current.datc64"
        if ($GameMode -eq "GGPK") {
            $CurrentGgpk = Extract-CurrentGgpkBaseItemsForRestoreCheck
            Copy-Item -LiteralPath $CurrentGgpk.Dat -Destination $CurrentBaseItems -Force
            $GgpkWords = Join-Path $CurrentGgpk.Dir ("data\" + $InstallInfo.WordsFileSlug)
            $GgpkEndgameMaps = Join-Path $CurrentGgpk.Dir ("data\" + $InstallInfo.EndgameMapsFileSlug)
            if (Test-Path -LiteralPath $GgpkWords -PathType Leaf) {
                Copy-Item -LiteralPath $GgpkWords -Destination $CurrentWords -Force
            }
            if (Test-Path -LiteralPath $GgpkEndgameMaps -PathType Leaf) {
                Copy-Item -LiteralPath $GgpkEndgameMaps -Destination $CurrentEndgameMaps -Force
            }
        }
        else {
            $ExtractLog = Join-Path $TempRoot "extract.log"
            foreach ($Target in @(
                    @([string]$InstallInfo.TcBaseItemsPath, $CurrentBaseItems, $true),
                    @([string]$TcWordsPath, $CurrentWords, $SupportsUniqueWords),
                    @([string]$InstallInfo.TcEndgameMapsPath, $CurrentEndgameMaps, $true)
                )) {
                if (-not [bool]$Target[2]) { continue }
                & $BundledBundleExtractorExe $Bundles2Paths.IndexBin ([string]$Target[0]) ([string]$Target[1]) *> $ExtractLog
                if ($LASTEXITCODE -ne 0) {
                    throw "无法从当前 Bundles2 提取 $($Target[0])；日志：$ExtractLog"
                }
            }
        }
        Assert-File $CurrentBaseItems "current BaseItemTypes"

        $CleanZip = Join-Path $TempRoot "clean-logical.zip"
        $CleanBaseItems = Join-Path $TempRoot "baseitemtypes.clean.datc64"
        $CleanWords = Join-Path $TempRoot "words.clean.datc64"
        $CleanEndgameMaps = Join-Path $TempRoot "endgamemaps.clean.datc64"
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Args = @(
            (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
            "--patch-scope", "none",
            "--fallback-price-sources", "none",
            "--en-baseitems", $CurrentBaseItems,
            "--tc-baseitems", $CurrentBaseItems,
            "--out-dir", $TempRoot,
            "--output-zip", $CleanZip,
            "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
            "--mode", "append",
            "--patched-dat", $CleanBaseItems,
            "--report", (Join-Path $TempRoot "cleanup.report.json"),
            "--game-path", $InstallInfo.TcBaseItemsPath,
            "--no-uniques",
            "--strict-feature-cleanup"
        )
        if (Test-Path -LiteralPath $CurrentWords -PathType Leaf) {
            $Args += @(
                "--tc-words", $CurrentWords,
                "--patched-words", $CleanWords,
                "--words-game-path", $TcWordsPath
            )
        }
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList $Args
        if ($Result.ExitCode -ne 0) {
            throw "自动清理当前 BaseItemTypes/Words 失败，退出码：$($Result.ExitCode)。$($Result.Text)"
        }
        Assert-File $CleanBaseItems "clean BaseItemTypes"
        if (Test-BaseItemsLookPatched $CleanBaseItems) {
            throw "清理后的 BaseItemTypes 仍包含价格标记。"
        }
        if (-not (Test-BaseItemsCompatible $CleanBaseItems $CurrentBaseItems)) {
            throw "清理后的 BaseItemTypes 结构发生了非预期变化。"
        }
        if ((Test-Path -LiteralPath $CleanWords -PathType Leaf) -and (Test-WordsLookPatched $CleanWords)) {
            throw "清理后的 Words 仍包含价格标记。"
        }

        if (Test-Path -LiteralPath $CurrentEndgameMaps -PathType Leaf) {
            if (Test-EndgameMapsLookPatched $CurrentEndgameMaps) {
                $EndgameResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
                    (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"),
                    "clean",
                    "--source", $CurrentEndgameMaps,
                    "--output-zip", $CleanZip,
                    "--patched-dat", $CleanEndgameMaps,
                    "--game-path", $InstallInfo.TcEndgameMapsPath,
                    "--report", (Join-Path $TempRoot "endgamemaps-cleanup.report.json")
                )
                if ($EndgameResult.ExitCode -ne 0) {
                    throw "自动清理当前 EndgameMaps 失败，退出码：$($EndgameResult.ExitCode)。"
                }
            }
            else {
                Update-ZipEntryFromFile -ZipPath $CleanZip -SourceFile $CurrentEndgameMaps -EntryName $InstallInfo.TcEndgameMapsPath
            }
        }
        Add-Poe2RestoreManifest -ZipPath $CleanZip -BaselineKind "semantic-clean-self-heal" | Out-Null
        Copy-Poe2FileAtomically -Source $CleanZip -Destination $OutputZip | Out-Null
        Assert-RestoreZip $OutputZip
        return (Resolve-Path -LiteralPath $OutputZip).Path
    }
    finally {
        if ($null -ne $CurrentGgpk -and (Test-Path -LiteralPath $CurrentGgpk.Dir -PathType Container)) {
            Remove-Item -LiteralPath $CurrentGgpk.Dir -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if ([string]::IsNullOrWhiteSpace($RestoreZip)) {
    foreach ($Candidate in (Get-RestoreZipCandidates)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            if (-not (Test-RestoreZipUsable $Candidate)) {
                Write-Warning "Ignore restore zip for a different or invalid language target: $Candidate"
                continue
            }
            $RestoreZip = (Resolve-Path -LiteralPath $Candidate).Path
            break
        }
    }

    if ([string]::IsNullOrWhiteSpace($RestoreZip)) {
        Write-Warning "没有找到可用的专属还原基线，正在从当前游戏状态安全重建。"
        try {
            $RestoreZip = New-Poe2RestoreBaselineFromCurrentGame -OutputZip $RestoreOutZip
            $RestoreZip = Publish-Poe2RestoreBaseline -Source $RestoreZip
        }
        catch {
            throw "专属基线缺失，自动清理迁移也无法通过严格校验：$($_.Exception.Message)。为避免损坏游戏，已拒绝写入；请通过游戏平台校验/修复后重试。"
        }
    }
}
else {
    $RestoreZip = (Resolve-Path -LiteralPath $RestoreZip).Path
}

Assert-RestoreZip $RestoreZip

$RestoreEntryTemp = ""
$CurrentCheck = $null
try {
    if ($GameMode -eq "GGPK") {
        Write-Step "Check restore patch compatibility"
        $CurrentCheck = Extract-CurrentGgpkBaseItemsForRestoreCheck
        $RestoreEntryTemp = Get-ZipBaseItemsEntryAsTempFile -ZipPath $RestoreZip -EntryName $InstallInfo.TcBaseItemsPath
        if (-not (Test-BaseItemsCompatible $RestoreEntryTemp $CurrentCheck.Dat)) {
            Write-Warning "现有还原包属于其它客户端或旧游戏版本，正在从当前 GGPK 自动重建专属基线。"
            Remove-Item -LiteralPath $RestoreEntryTemp -Force -ErrorAction SilentlyContinue
            $RestoreEntryTemp = ""
            $RestoreZip = New-Poe2RestoreBaselineFromCurrentGame -OutputZip $RestoreOutZip
            $RestoreZip = Publish-Poe2RestoreBaseline -Source $RestoreZip
            $RestoreEntryTemp = Get-ZipBaseItemsEntryAsTempFile -ZipPath $RestoreZip -EntryName $InstallInfo.TcBaseItemsPath
            if (-not (Test-BaseItemsCompatible $RestoreEntryTemp $CurrentCheck.Dat)) {
                throw "自动重建后的专属基线仍与当前 GGPK 结构不匹配。请通过官方启动器校验/修复。"
            }
        }
        Write-Host "Restore package matches current game data." -ForegroundColor Green
    }
    elseif ($GameMode -eq "Bundles2") {
        $CleanDatForCheck = Ensure-CleanBaseItemForRestore
        $RestoreEntryTemp = Get-ZipBaseItemsEntryAsTempFile -ZipPath $RestoreZip -EntryName $InstallInfo.TcBaseItemsPath
        if (-not (Test-BaseItemsCompatible $RestoreEntryTemp $CleanDatForCheck)) {
            Write-Warning "现有还原包属于其它客户端或旧游戏版本，正在从当前 Bundles2 自动重建专属基线。"
            Remove-Item -LiteralPath $RestoreEntryTemp -Force -ErrorAction SilentlyContinue
            $RestoreEntryTemp = ""
            $RestoreZip = New-Poe2RestoreBaselineFromCurrentGame -OutputZip $RestoreOutZip
            $RestoreZip = Publish-Poe2RestoreBaseline -Source $RestoreZip
            $RestoreEntryTemp = Get-ZipBaseItemsEntryAsTempFile -ZipPath $RestoreZip -EntryName $InstallInfo.TcBaseItemsPath
            if (-not (Test-BaseItemsCompatible $RestoreEntryTemp $CleanDatForCheck)) {
                throw "自动重建后的专属基线仍与当前 Bundles2 结构不匹配。请通过游戏平台校验/修复。"
            }
        }
        Write-Host "Restore package structure matches current game data." -ForegroundColor Green
    }
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($RestoreEntryTemp) -and (Test-Path -LiteralPath $RestoreEntryTemp -PathType Leaf)) {
        Remove-Item -LiteralPath $RestoreEntryTemp -Force
    }
    if ($null -ne $CurrentCheck -and (Test-Path -LiteralPath $CurrentCheck.Dir -PathType Container)) {
        Remove-Item -LiteralPath $CurrentCheck.Dir -Recurse -Force
    }
}

try {
    Assert-Poe2LogicalRestoreManifest -ZipPath $RestoreZip -InstallInfo $InstallInfo | Out-Null
}
catch {
    if (-not (Test-Poe2LegacyRestorePatchZipName -Path $RestoreZip)) {
        throw
    }
    Write-Host "正在把已验证的旧版共享还原包迁移为当前客户端专属基线..." -ForegroundColor Yellow
    $MigrationZip = Join-Path $RestoreOutDir ([string]::Concat(".legacy-migration-", [Guid]::NewGuid().ToString("N"), ".zip"))
    try {
        New-CurrentTargetRestoreZip -SourceZip $RestoreZip -OutputZip $MigrationZip | Out-Null
        if ($GameMode -eq "Bundles2") {
            Add-CleanCurrentWordsToRestoreZip -ZipPath $MigrationZip | Out-Null
            Add-CleanCurrentEndgameMapsToRestoreZip -ZipPath $MigrationZip | Out-Null
        }
        Add-Poe2RestoreManifest -ZipPath $MigrationZip -BaselineKind "legacy-validated-migration" | Out-Null
        $RestoreZip = Publish-Poe2RestoreBaseline -Source $MigrationZip
    }
    finally {
        if (Test-Path -LiteralPath $MigrationZip -PathType Leaf) {
            Remove-Item -LiteralPath $MigrationZip -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $NoInstall -and -not ([System.IO.Path]::GetFullPath($RestoreZip)).Equals(
        [System.IO.Path]::GetFullPath($PersistentLogicalRestoreZip),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    New-Item -ItemType Directory -Force -Path $PersistentRestoreDir | Out-Null
    Copy-Poe2FileAtomically -Source $RestoreZip -Destination $PersistentLogicalRestoreZip | Out-Null
    Assert-Poe2LogicalRestoreManifest -ZipPath $PersistentLogicalRestoreZip -InstallInfo $InstallInfo | Out-Null
    $RestoreZip = (Resolve-Path -LiteralPath $PersistentLogicalRestoreZip).Path
}

$InstallRestoreZip = $RestoreZip
if ($GameMode -eq "Bundles2" -or -not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*")) {
    $SingleTargetRestoreZip = Join-Path $RestoreOutDir ([string]::Concat("install_", $RestoreZipName))
    if (([System.IO.Path]::GetFullPath($RestoreZip)).Equals([System.IO.Path]::GetFullPath($SingleTargetRestoreZip), [System.StringComparison]::OrdinalIgnoreCase)) {
        $SingleTargetRestoreZip = Join-Path $RestoreOutDir ([string]::Concat("install_", [Guid]::NewGuid().ToString("N"), "_", $RestoreZipName))
    }
    $InstallRestoreZip = New-CurrentTargetRestoreZip -SourceZip $RestoreZip -OutputZip $SingleTargetRestoreZip
}
if ($GameMode -eq "Bundles2") {
    $InstallRestoreZip = Add-CleanCurrentWordsToRestoreZip -ZipPath $InstallRestoreZip
    $InstallRestoreZip = Add-CleanCurrentEndgameMapsToRestoreZip -ZipPath $InstallRestoreZip
    Add-Poe2RestoreManifest -ZipPath $InstallRestoreZip -BaselineKind "restore-install-payload" | Out-Null
    Assert-RestoreZip $InstallRestoreZip
}

if ($NoInstall) {
    Write-Step "Verify restore patch only"
    Write-Host "Restore : $RestoreZip"
    Write-Host "Install : $InstallRestoreZip"
    Write-Host "NoInstall enabled. Restore package verified; game files were not changed." -ForegroundColor Yellow
    return
}

if ($GameMode -eq "GGPK") {
    Write-Step "Install restore patch into Content.ggpk"
    Write-Host "Installer: $BundledPatchDll"
    Write-Host "GGPK     : $ContentGgpk"
    Write-Host "Patch    : $InstallRestoreZip"

    for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
        try {
            Invoke-GgpkRestorePatch -ZipPath $InstallRestoreZip
            Assert-GgpkRestoreApplied -ZipPath $InstallRestoreZip
            break
        }
        catch {
            if ($Attempt -ge 2) {
                throw "GGPK 还原写入或读回校验重试后仍失败：$($_.Exception.Message)"
            }
            Write-Warning "GGPK 还原写入或读回校验未通过，正在自动重试一次：$($_.Exception.Message)"
        }
    }

    Write-Host "Restore installed and verified in Content.ggpk." -ForegroundColor Green
}
else {
    Write-Step "Install restore patch into Bundles2 using PatchBundle3"

    $UsePatchBundleDll = Test-Path -LiteralPath $BundledBundlePatchDll -PathType Leaf
    if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
        $BundledBundlePatchExe = Join-Path $CodeToolsRoot "PatchBundle3.exe"
    }
    if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
        throw "Missing PatchBundle3.dll or PatchBundle3.exe: $BundledBundlePatchDll"
    }

    if ($UsePatchBundleDll) {
        Write-Host "Bundle3: $($BundledBundlePatchDll)"
    }
    else {
        Write-Host "Bundle3: $($BundledBundlePatchExe)"
    }
    Write-Host "Index  : $($Bundles2Paths.IndexBin)"
    Write-Host "Patch  : $InstallRestoreZip"
    # Candidate checks and clean-layer generation can take time. Close the race
    # again immediately before PatchBundle3 touches the live index.
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin

    Push-Location -LiteralPath $BundledInstallerDir
    try {
        if ($UsePatchBundleDll) {
            $BundlePatchResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledBundlePatchDll, $Bundles2Paths.IndexBin, $InstallRestoreZip) -InputText "" -Quiet
            $BundlePatchOutput = $BundlePatchResult.Lines
            $BundlePatchExitCode = $BundlePatchResult.ExitCode
        }
        else {
            $BundlePatchOutput = & $BundledBundlePatchExe $Bundles2Paths.IndexBin $InstallRestoreZip 2>&1
            $BundlePatchExitCode = $LASTEXITCODE
        }
    }
    finally {
        Pop-Location
    }

    $BundlePatchOutput | ForEach-Object { Write-Host $_ }
    $BundlePatchText = ($BundlePatchOutput | Out-String)
    if ($BundlePatchExitCode -ne 0 -or $BundlePatchText -match 'Exception|Unhandled|FileNotFound|Could not load|Error:|錯誤|错误|失敗|失败') {
        if (Test-GgpkExtractorMissingRuntimeDependency -Text $BundlePatchText) {
            throw "GGPKExtractor missing VC runtime dependency. Exit code: $BundlePatchExitCode. Log: restore-install"
        }
        throw "PatchBundle3 restore failed. Exit code: $BundlePatchExitCode"
    }

    try {
        Assert-Bundles2RestoreApplied -ZipPath $InstallRestoreZip -EntryNames @(
            $InstallInfo.TcBaseItemsPath,
            $TcWordsPath,
            $InstallInfo.TcEndgameMapsPath
        )
    }
    catch {
        Write-Warning "Bundles2 还原读回校验未通过，正在自动重试一次：$($_.Exception.Message)"
        Push-Location -LiteralPath $BundledInstallerDir
        try {
            if ($UsePatchBundleDll) {
                $RetryResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledBundlePatchDll, $Bundles2Paths.IndexBin, $InstallRestoreZip) -InputText "" -Quiet
                $RetryExitCode = $RetryResult.ExitCode
                $RetryText = $RetryResult.Text
            }
            else {
                $RetryOutput = & $BundledBundlePatchExe $Bundles2Paths.IndexBin $InstallRestoreZip 2>&1
                $RetryExitCode = $LASTEXITCODE
                $RetryText = ($RetryOutput | Out-String)
            }
        }
        finally {
            Pop-Location
        }
        if ($RetryExitCode -ne 0 -or $RetryText -match 'Exception|Unhandled|FileNotFound|Could not load|Error:|錯誤|错误|失敗|失败') {
            throw "PatchBundle3 restore retry failed. Exit code: $RetryExitCode"
        }
        Assert-Bundles2RestoreApplied -ZipPath $InstallRestoreZip -EntryNames @(
            $InstallInfo.TcBaseItemsPath,
            $TcWordsPath,
            $InstallInfo.TcEndgameMapsPath
        )
    }

    Write-Host "Restore installed into Bundles2." -ForegroundColor Green
}
