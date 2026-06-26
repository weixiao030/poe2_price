param(
    [string]$Poe2Dir = "",
    [string]$RestoreZip = "",
    [switch]$NoInstall
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

if ([string]::IsNullOrWhiteSpace($Poe2Dir)) {
    $Poe2Dir = (Split-Path -Parent $RepoRoot)
}
$Poe2Dir = (Resolve-Path -LiteralPath $Poe2Dir).Path

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
            return $true
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

function Get-BaseItemsMetadataSignature {
    param([string]$SourceDat)

    Assert-File $SourceDat "BaseItemTypes.datc64"
    $TempCsv = Join-Path $env:TEMP ([string]::Concat("poe2_baseitems_sig_", [Guid]::NewGuid().ToString("N"), ".csv"))
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
            throw "Failed to export BaseItemTypes metadata signature. Exit code: $($ExportResult.ExitCode)`n$($ExportResult.Text)"
        }

        $Rows = Import-Csv -LiteralPath $TempCsv -Encoding UTF8
        $Paths = @($Rows | ForEach-Object { $_.metadata_path } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        $Joined = [string]::Join("`n", $Paths)
        $Sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Joined)
            $Hash = [System.BitConverter]::ToString($Sha.ComputeHash($Bytes)).Replace("-", "")
        }
        finally {
            $Sha.Dispose()
        }

        return [pscustomobject]@{
            Count = $Paths.Count
            Hash  = $Hash
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempCsv -PathType Leaf) {
            Remove-Item -LiteralPath $TempCsv -Force
        }
    }
}

function Test-BaseItemsCompatible {
    param(
        [string]$LeftDat,
        [string]$RightDat
    )

    try {
        $Left = Get-BaseItemsMetadataSignature $LeftDat
        $Right = Get-BaseItemsMetadataSignature $RightDat
        return ($Left.Count -eq $Right.Count -and $Left.Hash -eq $Right.Hash)
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

function New-BaseItemRestoreZip {
    param(
        [string]$SourceDat,
        [string]$SourceWords = "",
        [string]$OutputZip
    )

    Assert-File $SourceDat "clean BaseItemTypes.datc64"
    if (Test-BaseItemsLookPatched $SourceDat) {
        throw "Cached BaseItemTypes looks patched. Refusing to build a restore zip from it."
    }

    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    if (Test-Path -LiteralPath $OutputZip -PathType Leaf) {
        Remove-Item -LiteralPath $OutputZip -Force
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::Open($OutputZip, [System.IO.Compression.ZipArchiveMode]::Create)
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
    }
    finally {
        $Archive.Dispose()
    }
}

function Assert-RestoreZip {
    param([string]$Path)

    Assert-File $Path "restore zip"
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
        if ($SupportsUniqueWords -and $null -eq $Archive.GetEntry($TcWordsPath)) {
            Write-Warning "还原包缺少 $TcWordsPath；将只还原 BaseItemTypes。请在游戏文件干净后运行一次一键更新，以刷新包含 Words 的新版还原包。"
        }

        $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_restore_assert_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        try {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
            if (Test-BaseItemsLookPatched $TempDat) {
                throw "Restore zip BaseItemTypes looks patched. Refusing to restore from a polluted backup."
            }
        }
        finally {
            if (Test-Path -LiteralPath $TempDat -PathType Leaf) {
                Remove-Item -LiteralPath $TempDat -Force
            }
        }
    }
    finally {
        $Archive.Dispose()
    }
}

function Test-RestoreZipUsable {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    }
    catch {
        return $false
    }
    try {
        $Entry = $Archive.GetEntry($InstallInfo.TcBaseItemsPath)
        if ($null -eq $Entry -or $Entry.Length -le 1048576) {
            return $false
        }
        $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_restore_validate_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        try {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
            return (-not (Test-BaseItemsLookPatched $TempDat))
        }
        catch {
            return $false
        }
        finally {
            if (Test-Path -LiteralPath $TempDat -PathType Leaf) {
                Remove-Item -LiteralPath $TempDat -Force
            }
        }
    }
    finally {
        $Archive.Dispose()
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
    try {
        $OutputDir = Split-Path -Parent $OutputZip
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
        if (Test-Path -LiteralPath $OutputZip -PathType Leaf) {
            Remove-Item -LiteralPath $OutputZip -Force
        }

        $TargetArchive = [System.IO.Compression.ZipFile]::Open($OutputZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Copy-ZipEntry -SourceArchive $SourceArchive -TargetArchive $TargetArchive -EntryName $InstallInfo.TcBaseItemsPath -Required | Out-Null
            if ($SupportsUniqueWords) {
                if (-not (Copy-ZipEntry -SourceArchive $SourceArchive -TargetArchive $TargetArchive -EntryName $TcWordsPath)) {
                    Write-Warning "还原包缺少 $TcWordsPath；本次安装包不会包含 Words 还原条目。"
                }
            }
        }
        finally {
            $TargetArchive.Dispose()
        }
    }
    finally {
        $SourceArchive.Dispose()
    }

    return (Resolve-Path -LiteralPath $OutputZip).Path
}

function Get-RestoreZipCandidates {
    $Paths = New-Object System.Collections.Generic.List[string]
    foreach ($Name in (Get-Poe2RestorePatchZipCandidateNames -InstallInfo $InstallInfo)) {
        $Paths.Add((Join-Path $RepoRoot $Name))
        $Paths.Add((Join-Path $RestoreOutDir $Name))
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
    $Names = @(
        (Get-Poe2FixedPhysicalRestorePatchZipName -InstallInfo $InstallInfo),
        (Get-Poe2PatchName "PhysicalRestorePatchZip")
    )

    $SearchRoots = @(
        $RepoRoot,
        $RestoreOutDir,
        (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)),
        (Join-Path (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)) "output\restore")
    )

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

    Assert-File $Path "physical restore zip"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $ManifestEntry = $Archive.GetEntry("manifest.json")
        if ($null -eq $ManifestEntry) {
            throw "Physical restore zip is missing manifest.json"
        }

        $Reader = New-Object System.IO.StreamReader($ManifestEntry.Open(), [System.Text.Encoding]::UTF8)
        try {
            $Manifest = $Reader.ReadToEnd() | ConvertFrom-Json
        }
        finally {
            $Reader.Dispose()
        }
        if ([string]$Manifest.kind -ne "poe2-price-patch-physical-restore") {
            throw "Physical restore zip manifest kind is invalid"
        }
        if ([string]$Manifest.install_kind -ne [string]$InstallInfo.InstallKind) {
            throw "Physical restore zip is for $($Manifest.install_kind), current install is $($InstallInfo.InstallKind)"
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Manifest.target_path) -and [string]$Manifest.target_path -ne [string]$InstallInfo.TcBaseItemsPath) {
            throw "Physical restore zip is for $($Manifest.target_path), current target is $($InstallInfo.TcBaseItemsPath)"
        }

        $Entry = $Archive.GetEntry("Bundles2/_.index.bin")
        if ($null -eq $Entry -or $Entry.Length -le 1048576) {
            throw "Physical restore zip does not contain a valid Bundles2/_.index.bin"
        }
    }
    finally {
        $Archive.Dispose()
    }
}

function Restore-PhysicalBundles2 {
    param([string]$Path)

    Assert-PhysicalRestoreZip $Path

    $Bundles2Root = (Resolve-Path -LiteralPath $Bundles2Paths.Bundles2Dir).Path
    $GameRoot = (Resolve-Path -LiteralPath $Poe2Dir).Path
    Assert-Poe2PathInside -Path $Bundles2Root -Root $GameRoot -Message "Refusing to restore outside game folder" | Out-Null

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $Entries = @($Archive.Entries | Where-Object { $_.FullName -like "Bundles2/*" -and -not [string]::IsNullOrEmpty($_.Name) })
        if (-not ($Entries | Where-Object { $_.FullName -eq "Bundles2/_.index.bin" } | Select-Object -First 1)) {
            throw "Physical restore zip does not contain Bundles2/_.index.bin"
        }

        $HasLibBackup = [bool]($Entries | Where-Object { $_.FullName -like "Bundles2/LibGGPK3/*" } | Select-Object -First 1)
        $LibDir = Join-Path $Bundles2Root "LibGGPK3"
        if (-not $HasLibBackup -and (Test-Path -LiteralPath $LibDir -PathType Container)) {
            $ResolvedLibDir = (Resolve-Path -LiteralPath $LibDir).Path
            Assert-Poe2PathInside -Path $ResolvedLibDir -Root $Bundles2Root -Message "Refusing to remove unexpected LibGGPK3 path" | Out-Null
            Remove-Item -LiteralPath $ResolvedLibDir -Recurse -Force
        }

        foreach ($Entry in $Entries) {
            $Relative = $Entry.FullName.Substring("Bundles2/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            $Target = [System.IO.Path]::GetFullPath((Join-Path $Bundles2Root $Relative))
            Assert-Poe2PathInside -Path $Target -Root $Bundles2Root -Message "Refusing to restore path outside Bundles2" | Out-Null

            $TargetDir = Split-Path -Parent $Target
            New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Target, $true)
        }
    }
    finally {
        $Archive.Dispose()
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
    }
    else {
        & $Extractor $ContentGgpk $TempDir *> $ExtractLog
        $ExtractorExitCode = $LASTEXITCODE
    }
    if ($ExtractorExitCode -ne 0) {
        throw "Failed to extract current BaseItemTypes for compatibility check. Log: $ExtractLog"
    }

    $Extracted = Join-Path $TempDir ("data\" + $InstallInfo.LanguageFileSlug)
    Assert-File $Extracted "current BaseItemTypes"
    return [pscustomobject]@{
        Dir = $TempDir
        Dat = $Extracted
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
$RestoreOutDir = Join-Path $RepoRoot "output\restore"
$RestoreOutZip = Join-Path $RestoreOutDir $RestoreZipName
$PhysicalRestoreOutZip = Join-Path $RestoreOutDir $PhysicalRestoreZipName
$PatchFolderRestoreZip = Join-Path $RepoRoot $RestoreZipName
$PatchFolderPhysicalRestoreZip = Join-Path $RepoRoot $PhysicalRestoreZipName
$CleanDat = Join-Path $RepoRoot ("output\dat_files_latest\data\" + $InstallInfo.LanguageFileSlug)
$TcWordsPath = $InstallInfo.TcWordsPath
$SupportsUniqueWords = Test-Poe2UniqueWordsSupported -WordsPath $TcWordsPath

Write-Host "POE2 price patch restore" -ForegroundColor Green
Write-Host "Game dir : $Poe2Dir"
Write-Host "Patch dir: $RepoRoot"
Write-Host "Detected : $($InstallInfo.DisplayName)" -ForegroundColor Cyan
Write-Host "Mode     : $GameMode" -ForegroundColor Cyan
Write-Host "Language : $($InstallInfo.LanguageName) ($($InstallInfo.ConfigLanguage))" -ForegroundColor Cyan
Write-Host "Target   : $($InstallInfo.TcBaseItemsPath)" -ForegroundColor Cyan
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
    Resolve-BundleExtractor
}
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot

if ($GameMode -eq "Bundles2") {
    $PhysicalRestoreZip = ""
    foreach ($Candidate in (Get-PhysicalRestoreZipCandidates)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            try {
                Assert-PhysicalRestoreZip $Candidate
                $PhysicalRestoreZip = (Resolve-Path -LiteralPath $Candidate).Path
                break
            }
            catch {
                Write-Warning "Ignore invalid physical restore zip: $Candidate ($($_.Exception.Message))"
            }
        }
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

function Ensure-CleanBaseItemForRestore {
    if (Test-Path -LiteralPath $CleanDat -PathType Leaf) {
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
        Write-Warning "Extracted BaseItemTypes already contains price markers; restore zip compatibility cannot be checked against current patched data."
    }

    return $CleanDat
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
        throw "Missing fixed restore zip. Put $RestoreZipName in the patch folder, then re-run."
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
            throw "Restore zip is outdated for the current game files. Run the official launcher until the game is clean, then run one-key update to refresh restore packages."
        }
        Write-Host "Restore package matches current game data." -ForegroundColor Green
    }
    elseif ($GameMode -eq "Bundles2") {
        $CleanDatForCheck = Ensure-CleanBaseItemForRestore
        if (-not (Test-BaseItemsLookPatched $CleanDatForCheck)) {
            $RestoreEntryTemp = Get-ZipBaseItemsEntryAsTempFile -ZipPath $RestoreZip -EntryName $InstallInfo.TcBaseItemsPath
            if (-not (Test-BaseItemsCompatible $RestoreEntryTemp $CleanDatForCheck)) {
                throw "Restore zip is outdated for the current game files. Run the official launcher until the game is clean, then run one-key update to refresh restore packages."
            }
        }
        else {
            Write-Warning "Current BaseItemTypes already contains price markers; skipping compatibility check against patched game data and using the clean restore package."
        }
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

if ($RestoreZip -ne $PatchFolderRestoreZip -and -not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*")) {
    Copy-Item -LiteralPath $RestoreZip -Destination $PatchFolderRestoreZip -Force
}

$InstallRestoreZip = $RestoreZip
if ($GameMode -eq "Bundles2" -or -not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*")) {
    $SingleTargetRestoreZip = Join-Path $RestoreOutDir ([string]::Concat("install_", $RestoreZipName))
    $InstallRestoreZip = New-CurrentTargetRestoreZip -SourceZip $RestoreZip -OutputZip $SingleTargetRestoreZip
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

    Push-Location -LiteralPath $BundledInstallerDir
    try {
        $InstallerResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledPatchDll, $ContentGgpk, $InstallRestoreZip) -InputText ""
        if ($InstallerResult.ExitCode -ne 0 -or $InstallerResult.Text -match 'Exception|Unhandled|錯誤|错误|失敗|失败') {
            throw "Restore installer failed. Exit code: $($InstallerResult.ExitCode)"
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Restore installed into Content.ggpk." -ForegroundColor Green
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

    Push-Location -LiteralPath $BundledInstallerDir
    try {
        if ($UsePatchBundleDll) {
            $BundlePatchResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledBundlePatchDll, $Bundles2Paths.IndexBin, $InstallRestoreZip) -Quiet
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
        throw "PatchBundle3 restore failed. Exit code: $BundlePatchExitCode"
    }

    Write-Host "Restore installed into Bundles2." -ForegroundColor Green
}
