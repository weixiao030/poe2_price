param(
    [Parameter(Mandatory = $true)][string]$ChinaGameDir,
    [Parameter(Mandatory = $true)][string]$IntlGameDir
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PatchDirName = -join @([char]0x7269, [char]0x4EF7, [char]0x8865, [char]0x4E01)
$ToolsDir = Join-Path (Join-Path $Root $PatchDirName) "tools"
. (Join-Path $ToolsDir "poe2_patch_common.ps1")

$Extractor = Join-Path $ToolsDir "BundleExtractor\BundleExtractor.exe"
$NamePatchScript = Join-Path $ToolsDir "poe2_name_price_patch.py"
$PricePatchScript = Join-Path $ToolsDir "build_poe2scout_price_patch.py"
$IslandScript = Join-Path $ToolsDir "poe2_island_rumour_patch.py"
$ChinaSeed = Join-Path (Join-Path $Root "restore-seeds") (Get-Poe2PatchName "ChinaRestorePatchZip")
$IntlSeed = Join-Path (Join-Path $Root "restore-seeds") (Get-Poe2PatchName "IntlRestorePatchZip")
$PythonCommand = Get-Command python -ErrorAction Stop
$Python = $PythonCommand.Source

function Assert-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Name)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing $Name`: $Path"
    }
}

function Extract-BundleEntries {
    param(
        [Parameter(Mandatory = $true)][string]$GameDir,
        [Parameter(Mandatory = $true)][string[]]$EntryNames,
        [Parameter(Mandatory = $true)][string]$OutputDir
    )

    $IndexPath = Join-Path $GameDir "Bundles2\_.index.bin"
    Assert-File $IndexPath "Bundles2 index"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $RequestPath = Join-Path $OutputDir "requests.txt"
    $LogPath = Join-Path $OutputDir "extract.log"
    [System.IO.File]::WriteAllLines($RequestPath, $EntryNames, [System.Text.UTF8Encoding]::new($false))
    & $Extractor --extract-list $IndexPath $RequestPath $OutputDir *> $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "Bundle extraction failed. Exit code: $LASTEXITCODE. Log: $LogPath"
    }

    $Result = @{}
    for ($Index = 0; $Index -lt $EntryNames.Count; $Index++) {
        $Extracted = Join-Path $OutputDir ([string]::Format("{0:D6}.bin", $Index))
        Assert-File $Extracted $EntryNames[$Index]
        $Result[$EntryNames[$Index]] = $Extracted
    }
    return $Result
}

function Assert-CleanDatEntry {
    param(
        [Parameter(Mandatory = $true)][string]$EntryName,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$TempDir
    )

    $Info = Get-Item -LiteralPath $Path
    if ($EntryName.EndsWith("baseitemtypes.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 1048576) {
            throw "BaseItemTypes entry is too small: $EntryName"
        }
        $CsvPath = Join-Path $TempDir ([Guid]::NewGuid().ToString("N") + ".csv")
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $NamePatchScript, "export", "--source", $Path, "--output", $CsvPath
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            throw "BaseItemTypes validation failed: $EntryName`n$($Result.Text)"
        }
        $Marker = Import-Csv -LiteralPath $CsvPath -Encoding UTF8 | Where-Object {
            $Name = [string]$_.name
            $Name -match '=(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
            $Name -match '^(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
            ($Name.Length -le 12 -and $Name -match '(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$')
        } | Select-Object -First 1
        Remove-Item -LiteralPath $CsvPath -Force -ErrorAction SilentlyContinue
        if ($null -ne $Marker) {
            throw "BaseItemTypes seed contains a price marker: $EntryName"
        }
        return
    }

    if ($EntryName.EndsWith("words.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 1024) {
            throw "Words entry is too small: $EntryName"
        }
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $PricePatchScript, "--check-words", $Path
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            throw "Words validation failed: $EntryName`n$($Result.Text)"
        }
        $Inspection = $Result.Text | ConvertFrom-Json
        if ([int]$Inspection.patched_count -ne 0) {
            throw "Words seed contains active price markers: $EntryName"
        }
        return
    }

    if ($EntryName.EndsWith("endgamemaps.datc64", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($Info.Length -le 4096) {
            throw "EndgameMaps entry is too small: $EntryName"
        }
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $IslandScript, "check", "--source", $Path, "--game-path", $EntryName
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            throw "EndgameMaps validation failed: $EntryName`n$($Result.Text)"
        }
        $Inspection = $Result.Text | ConvertFrom-Json
        if ([int]$Inspection.patched_count -ne 0) {
            throw "EndgameMaps seed contains island hints: $EntryName"
        }
    }
}

function Write-RestoreSeed {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$BaseZip = "",
        [Parameter(Mandatory = $true)][hashtable]$FilesByEntry,
        [Parameter(Mandatory = $true)][string[]]$EntryNames
    )

    $DestinationDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    $TempZip = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $Destination), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        if (-not [string]::IsNullOrWhiteSpace($BaseZip)) {
            [System.IO.File]::Copy((Resolve-Path -LiteralPath $BaseZip).Path, $TempZip, $false)
            $Mode = [System.IO.Compression.ZipArchiveMode]::Update
        }
        else {
            $Mode = [System.IO.Compression.ZipArchiveMode]::Create
        }

        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, $Mode)
        try {
            foreach ($EntryName in $EntryNames) {
                $OldEntry = if ($Mode -eq [System.IO.Compression.ZipArchiveMode]::Update) {
                    $Archive.GetEntry($EntryName)
                }
                else {
                    $null
                }
                if ($null -ne $OldEntry) {
                    $OldEntry.Delete()
                }
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    [string]$FilesByEntry[$EntryName],
                    $EntryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $Archive.Dispose()
        }
        Move-Poe2FileAtomically -Source $TempZip -Destination $Destination | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
}

$ChinaGameDir = (Resolve-Path -LiteralPath $ChinaGameDir).Path
$IntlGameDir = (Resolve-Path -LiteralPath $IntlGameDir).Path
$TempRoot = Join-Path $env:TEMP ([string]::Concat("poe2_restore_seed_refresh_", [Guid]::NewGuid().ToString("N")))
try {
    $ChinaEntries = @(
        "data/balance/simplified chinese/baseitemtypes.datc64",
        "data/balance/simplified chinese/words.datc64",
        "data/balance/simplified chinese/endgamemaps.datc64"
    )
    $IntlEntries = New-Object System.Collections.Generic.List[string]
    foreach ($BaseItemsPath in (Get-Poe2KnownBaseItemsPaths)) {
        if ($BaseItemsPath -like "*/simplified chinese/*") {
            continue
        }
        $IntlEntries.Add($BaseItemsPath)
        $IntlEntries.Add((Get-Poe2WordsPathFromBaseItemsPath -BaseItemsPath $BaseItemsPath))
        $IntlEntries.Add((Get-Poe2EndgameMapsPathFromBaseItemsPath -BaseItemsPath $BaseItemsPath))
    }

    $ChinaFiles = Extract-BundleEntries -GameDir $ChinaGameDir -EntryNames $ChinaEntries -OutputDir (Join-Path $TempRoot "china")
    $IntlFiles = Extract-BundleEntries -GameDir $IntlGameDir -EntryNames $IntlEntries.ToArray() -OutputDir (Join-Path $TempRoot "intl")
    foreach ($EntryName in $ChinaEntries) {
        Assert-CleanDatEntry -EntryName $EntryName -Path $ChinaFiles[$EntryName] -TempDir $TempRoot
        $IntlFiles[$EntryName] = $ChinaFiles[$EntryName]
    }
    foreach ($EntryName in $IntlEntries) {
        Assert-CleanDatEntry -EntryName $EntryName -Path $IntlFiles[$EntryName] -TempDir $TempRoot
    }

    Write-RestoreSeed -Destination $ChinaSeed -FilesByEntry $ChinaFiles -EntryNames $ChinaEntries
    $AllIntlEntries = @($IntlEntries.ToArray()) + $ChinaEntries
    Write-RestoreSeed -Destination $IntlSeed -BaseZip $IntlSeed -FilesByEntry $IntlFiles -EntryNames $AllIntlEntries
    Write-Host "Restore seeds refreshed and validated:" -ForegroundColor Green
    Write-Host "  $ChinaSeed"
    Write-Host "  $IntlSeed"
}
finally {
    if (Test-Path -LiteralPath $TempRoot -PathType Container) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
