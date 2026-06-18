param(
    [string]$Poe2Dir = "",
    [string]$RestoreZip = ""
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

function New-BaseItemRestoreZip {
    param(
        [string]$SourceDat,
        [string]$OutputZip
    )

    Assert-File $SourceDat "clean BaseItemTypes.datc64"
    if (Test-BaseItemsLookPatched $SourceDat) {
        throw "Cached BaseItemTypes looks patched. Refusing to build a restore zip from it."
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    if (Test-Path -LiteralPath $OutputZip -PathType Leaf) {
        Remove-Item -LiteralPath $OutputZip -Force
    }

    $Archive = [System.IO.Compression.ZipFile]::Open($OutputZip, [System.IO.Compression.ZipArchiveMode]::Create)
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
}

function Assert-RestoreZip {
    param([string]$Path)

    Assert-File $Path "restore zip"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $Entry = $Archive.GetEntry("data/balance/traditional chinese/baseitemtypes.datc64")
        if ($null -eq $Entry) {
            throw "Restore zip does not contain data/balance/traditional chinese/baseitemtypes.datc64"
        }
    }
    finally {
        $Archive.Dispose()
    }
}

$ContentGgpk = Join-Path $Poe2Dir "Content.ggpk"
$BundledInstallerDir = Join-Path $RepoRoot (Get-Poe2PatchName "InstallerDir")
$BundledPatchDll = Join-Path $BundledInstallerDir "PatchBundledGGPK3.dll"
$BundledPatchRuntimeConfig = Join-Path $BundledInstallerDir "PatchBundledGGPK3.runtimeconfig.json"
$RestoreZipName = Get-Poe2PatchName "RestorePatchZip"
$RestoreOutDir = Join-Path $RepoRoot "output\restore"
$RestoreOutZip = Join-Path $RestoreOutDir $RestoreZipName
$PatchFolderRestoreZip = Join-Path $RepoRoot $RestoreZipName
$GameRootRestoreZip = Join-Path $Poe2Dir $RestoreZipName
$CleanDat = Join-Path $RepoRoot "output\dat_files_latest\data\data_balance_traditional chinese_baseitemtypes.datc64"

Write-Host "POE2 price patch restore" -ForegroundColor Green
Write-Host "Game dir : $Poe2Dir"
Write-Host "Patch dir: $RepoRoot"

Assert-File $ContentGgpk "Content.ggpk"
Assert-File $BundledPatchDll "PatchBundledGGPK3.dll"
Assert-File $BundledPatchRuntimeConfig "PatchBundledGGPK3.runtimeconfig.json"
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot

if ([string]::IsNullOrWhiteSpace($RestoreZip)) {
    $Candidates = @($PatchFolderRestoreZip, $RestoreOutZip, $GameRootRestoreZip)
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $RestoreZip = (Resolve-Path -LiteralPath $Candidate).Path
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($RestoreZip)) {
    Write-Step "Build restore zip from cached clean BaseItemTypes"
    New-BaseItemRestoreZip $CleanDat $RestoreOutZip
    $RestoreZip = $RestoreOutZip
}
else {
    $RestoreZip = (Resolve-Path -LiteralPath $RestoreZip).Path
}

Assert-RestoreZip $RestoreZip

if ($RestoreZip -ne $PatchFolderRestoreZip) {
    Copy-Item -LiteralPath $RestoreZip -Destination $PatchFolderRestoreZip -Force
}
Copy-Item -LiteralPath $RestoreZip -Destination $GameRootRestoreZip -Force

Write-Step "Install restore patch into Content.ggpk"
Write-Host "Installer: $BundledPatchDll"
Write-Host "GGPK     : $ContentGgpk"
Write-Host "Patch    : $GameRootRestoreZip"

Push-Location -LiteralPath $BundledInstallerDir
try {
    $InstallerOutput = "" | & $Dotnet $BundledPatchDll $ContentGgpk $GameRootRestoreZip 2>&1
    $InstallerOutput | ForEach-Object { Write-Host $_ }
    $InstallerText = ($InstallerOutput | Out-String)
    if ($LASTEXITCODE -ne 0 -or $InstallerText -match 'Exception|Unhandled|錯誤|错误|失敗|失败') {
        throw "Restore installer failed. Exit code: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Restore installed into Content.ggpk." -ForegroundColor Green
