param(
    [string]$Poe2Dir = "",
    [switch]$SkipExtract,
    [switch]$NoOpenTool,
    [switch]$NoInstall,
    [switch]$NoPoe2dbFallback
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
$PublicToolsRoot = Join-Path $RepoRoot "tools"
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

function Remove-FileIfInside {
    param([string]$Path, [string]$Root)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }

    $ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    if (-not $ResolvedPath.StartsWith($ResolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove file outside expected folder: $ResolvedPath"
    }
    Remove-Item -LiteralPath $ResolvedPath -Force
}

function Stop-LegacyInstallerProcesses {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and ([System.IO.Path]::GetFileName($_.Path) -eq (Get-Poe2PatchName "InstallerExe"))
            }
            catch {
                $false
            }
        } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Remove-LegacyFiles {
    $LegacyPatchZipNames = @(
        (Get-Poe2PatchName "LegacyPatchZip"),
        "price_patch.zip"
    )

    foreach ($Name in $LegacyPatchZipNames) {
        Remove-FileIfInside (Join-Path $RepoRoot $Name) $RepoRoot
        Remove-FileIfInside (Join-Path $Poe2Dir $Name) $Poe2Dir
        Remove-FileIfInside (Join-Path $BundledInstallerDir $Name) $RepoRoot
        Remove-FileIfInside (Join-Path $OutDir $Name) $RepoRoot
    }

    Remove-FileIfInside (Join-Path $BundledInstallerDir (Get-Poe2PatchName "InstallerExe")) $RepoRoot

    $CleanupBatPattern = [string]::Concat(
        "*", [char]0x6E05, [char]0x7406, [char]0x8865, [char]0x4E01,
        [char]0x5DE5, [char]0x5177, "*"
    )
    Get-ChildItem -LiteralPath $BundledInstallerDir -File -Filter "*.bat" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $CleanupBatPattern } |
        ForEach-Object { Remove-FileIfInside $_.FullName $RepoRoot }
}

function Compact-LatestBaseItems {
    param([string]$Root, [string[]]$KeepFiles)

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return
    }

    $RootPath = (Resolve-Path -LiteralPath $Root).Path
    $RepoPath = (Resolve-Path -LiteralPath $RepoRoot).Path
    if (-not $RootPath.StartsWith($RepoPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean extracted files outside patch folder: $RootPath"
    }

    $Keep = @{}
    foreach ($KeepFile in $KeepFiles) {
        if (Test-Path -LiteralPath $KeepFile -PathType Leaf) {
            $Keep[(Resolve-Path -LiteralPath $KeepFile).Path.ToLowerInvariant()] = $true
        }
    }

    Get-ChildItem -LiteralPath $RootPath -Recurse -File | ForEach-Object {
        if (-not $Keep.ContainsKey($_.FullName.ToLowerInvariant())) {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    }

    Get-ChildItem -LiteralPath $RootPath -Recurse -Directory |
        Sort-Object FullName -Descending |
        ForEach-Object {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force)) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }
}

function Test-BaseItemsLookPatched {
    param([string]$SourceDat)

    $TempCsv = Join-Path $env:TEMP ([string]::Concat("poe2_price_patch_", [Guid]::NewGuid().ToString("N"), ".csv"))
    try {
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $ExportScript = Join-Path $CodeToolsRoot "poe2_name_price_patch.py"
        & $Python $ExportScript export --source $SourceDat --output $TempCsv *> $null
        if ($LASTEXITCODE -ne 0) {
            return $true
        }
        $Rows = Import-Csv -LiteralPath $TempCsv -Encoding UTF8
        return [bool]($Rows | Where-Object { $_.name -match '=[0-9]+(?:\.[0-9]+)?[DE]$' } | Select-Object -First 1)
    }
    finally {
        if (Test-Path -LiteralPath $TempCsv -PathType Leaf) {
            Remove-Item -LiteralPath $TempCsv -Force
        }
    }
}

function Ensure-RestoreZip {
    param([string]$SourceDat)

    New-Item -ItemType Directory -Force -Path $RestoreOutDir | Out-Null

    foreach ($Candidate in @($RestoreOutZip, $RestorePatchFolderZip, $RestoreGameRootZip)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $ResolvedCandidate = (Resolve-Path -LiteralPath $Candidate).Path
            if ($ResolvedCandidate -ne $RestoreOutZip) {
                Copy-Item -LiteralPath $ResolvedCandidate -Destination $RestoreOutZip -Force
            }
            return (Resolve-Path -LiteralPath $RestoreOutZip).Path
        }
    }

    if (Test-BaseItemsLookPatched $SourceDat) {
        throw "Missing restore zip and current BaseItemTypes looks patched. Please restore from a clean backup once, then re-run."
    }

    Write-Step "Build restore zip"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::Open($RestoreOutZip, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $Archive,
            $SourceDat,
            "data/balance/traditional chinese/baseitemtypes.datc64",
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    finally {
        $Archive.Dispose()
    }

    return (Resolve-Path -LiteralPath $RestoreOutZip).Path
}

$ContentGgpk = Join-Path $Poe2Dir "Content.ggpk"
$LocalExtractorDll = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.dll"
$LocalExtractorExe = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.exe"
$FallbackExtractor = Join-Path $Poe2Dir "tiaoshi\extractor_tool\GGPKExtractor\bin\Release\net8.0-windows\GGPKExtractor.exe"
$BundledInstallerDir = Join-Path $RepoRoot (Get-Poe2PatchName "InstallerDir")
$BundledPatchDll = Join-Path $BundledInstallerDir "PatchBundledGGPK3.dll"
$BundledPatchRuntimeConfig = Join-Path $BundledInstallerDir "PatchBundledGGPK3.runtimeconfig.json"
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
$LatestDir = Join-Path $RepoRoot "output\dat_files_latest"
$ExtractLog = Join-Path $RepoRoot "output\dat_files_latest_extract.log"
$EnBaseItems = Join-Path $LatestDir "data\data_balance_baseitemtypes.datc64"
$TcBaseItems = Join-Path $LatestDir "data\data_balance_traditional chinese_baseitemtypes.datc64"
$OutDir = Join-Path $RepoRoot "output\poe2_price_patch_latest"
$RestoreOutDir = Join-Path $RepoRoot "output\restore"
$RestoreZipName = Get-Poe2PatchName "RestorePatchZip"
$RestoreOutZip = Join-Path $RestoreOutDir $RestoreZipName
$RestorePatchFolderZip = Join-Path $RepoRoot $RestoreZipName
$RestoreGameRootZip = Join-Path $Poe2Dir $RestoreZipName
$PricePatchZipName = Get-Poe2PatchName "PricePatchZip"
$PatchZip = Join-Path $OutDir $PricePatchZipName
$PatchedDat = Join-Path $OutDir "baseitemtypes.patched.datc64"
$ReportJson = Join-Path $OutDir "price_patch.report.json"
$SummaryJson = Join-Path $OutDir "summary.json"

Write-Host "POE2 price patch updater" -ForegroundColor Green
Write-Host "Game dir : $Poe2Dir"
Write-Host "Patch dir: $RepoRoot"

Assert-File $ContentGgpk "Content.ggpk"
Assert-File $Extractor "GGPKExtractor"
Assert-File $BundledPatchDll "PatchBundledGGPK3.dll"
Assert-File $BundledPatchRuntimeConfig "PatchBundledGGPK3.runtimeconfig.json"
Assert-File (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py") "price fetch script"
Assert-File (Join-Path $CodeToolsRoot "poe2_name_price_patch.py") "patch build script"
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
Stop-LegacyInstallerProcesses
Remove-LegacyFiles

if (-not $SkipExtract) {
    Write-Step "Extract latest BaseItemTypes from Content.ggpk"
    New-Item -ItemType Directory -Force -Path $LatestDir | Out-Null
    try {
        if ($ExtractorUsesDotnet) {
            & $Dotnet $Extractor $ContentGgpk $LatestDir *> $ExtractLog
        }
        else {
            & $Extractor $ContentGgpk $LatestDir *> $ExtractLog
        }
        if ($LASTEXITCODE -ne 0) {
            throw "GGPKExtractor exit code: $LASTEXITCODE"
        }
        Write-Host "Extracted to: $LatestDir"
    }
    catch {
        Write-Warning "Extract failed: $($_.Exception.Message)"
        Write-Warning "If the game is running, close it and run this updater again."
        if ((Test-Path -LiteralPath $EnBaseItems) -and (Test-Path -LiteralPath $TcBaseItems)) {
            Write-Warning "Using existing dat_files_latest instead."
        }
        else {
            throw "No usable BaseItemTypes files. Log: $ExtractLog"
        }
    }
}
else {
    Write-Step "Skip extract and use existing BaseItemTypes"
}

Assert-File $EnBaseItems "English BaseItemTypes"
Assert-File $TcBaseItems "Traditional Chinese BaseItemTypes"
Compact-LatestBaseItems $LatestDir @($EnBaseItems, $TcBaseItems)
$RestoreZip = Ensure-RestoreZip $TcBaseItems
Copy-Item -LiteralPath $RestoreZip -Destination $RestorePatchFolderZip -Force
Copy-Item -LiteralPath $RestoreZip -Destination $RestoreGameRootZip -Force

Write-Step "Fetch POE2 Scout prices and build patch zip"
$Python = Ensure-PythonRequests -RepoRoot $RepoRoot
$BuildArgs = @(
    (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
    "--en-baseitems", $EnBaseItems,
    "--tc-baseitems", $TcBaseItems,
    "--out-dir", $OutDir,
    "--output-zip", $PatchZip,
    "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
    "--mode", "append",
    "--patched-dat", $PatchedDat,
    "--report", $ReportJson
)
if (-not $NoPoe2dbFallback) {
    $BuildArgs += "--poe2db-fallback"
}

& $Python @BuildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Price fetch or patch build failed. Exit code: $LASTEXITCODE"
}

Assert-File $PatchZip $PricePatchZipName

Write-Step "Copy patch zip"
$PatchFolderZip = Join-Path $RepoRoot $PricePatchZipName
$GameRootPatchZip = Join-Path $Poe2Dir $PricePatchZipName
$InstallerPatchZip = Join-Path $BundledInstallerDir $PricePatchZipName
Copy-Item -LiteralPath $PatchZip -Destination $PatchFolderZip -Force
Copy-Item -LiteralPath $PatchZip -Destination $GameRootPatchZip -Force
Copy-Item -LiteralPath $PatchZip -Destination $InstallerPatchZip -Force

Write-Host "Generated:" -ForegroundColor Green
Write-Host "  $PatchZip"
Write-Host "Copied:" -ForegroundColor Green
Write-Host "  $PatchFolderZip"
Write-Host "  $GameRootPatchZip"
Write-Host "  $InstallerPatchZip"

if (Test-Path -LiteralPath $SummaryJson -PathType Leaf) {
    Write-Step "Summary"
    Get-Content -LiteralPath $SummaryJson -Encoding UTF8
}

if ($NoOpenTool) {
    $NoInstall = $true
}

if (-not $NoInstall) {
    Write-Step "Install patch into Content.ggpk"
    Assert-File $BundledPatchDll "PatchBundledGGPK3.dll"
    Assert-File $GameRootPatchZip "patch zip"

    Write-Host "Installer: $BundledPatchDll"
    Write-Host "GGPK     : $ContentGgpk"
    Write-Host "Patch    : $GameRootPatchZip"

    Push-Location -LiteralPath $BundledInstallerDir
    try {
        $InstallerOutput = "" | & $Dotnet $BundledPatchDll $ContentGgpk $GameRootPatchZip 2>&1
        $InstallerOutput | ForEach-Object { Write-Host $_ }
        $InstallerText = ($InstallerOutput | Out-String)
        if ($LASTEXITCODE -ne 0 -or $InstallerText -match 'Exception|Unhandled|錯誤|错误|失敗|失败') {
            throw "Patch installer failed. Exit code: $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
    Write-Host "Patch installed into Content.ggpk." -ForegroundColor Green
}
else {
    Write-Host "Skip installing patch into Content.ggpk." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
