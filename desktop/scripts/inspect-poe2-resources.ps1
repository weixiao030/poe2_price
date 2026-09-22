param(
  [Parameter(Mandatory=$true)][string]$Engine,
  [Parameter(Mandatory=$true)][string]$GameDirectory,
  [Parameter(Mandatory=$true)][string]$OutputDirectory,
  [string]$PatchZip = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $Engine 'tools/poe2_patch_common.ps1')
$Info = Get-Poe2InstallInfo -Poe2Dir $GameDirectory
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$Archive = $null
try {
  if ($PatchZip) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead($PatchZip)
    $Paths = @($Archive.Entries | Where-Object { $_.Name -and $_.FullName -notmatch '(?i)manifest\.json$' } | ForEach-Object { $_.FullName.Replace('\','/') })
  } else {
    $Paths = @($Info.EnBaseItemsPath, $Info.TcBaseItemsPath, $Info.TcWordsPath,
      'data/balance/words.datc64', 'data/balance/endgamemaps.datc64', $Info.TcEndgameMapsPath,
      'metadata/items/toweraugments/toweraugment.it',
      'data/statdescriptions/tablet_stat_descriptions.csd',
      'data/statdescriptions/map_stat_descriptions.csd',
      'data/statdescriptions/stat_descriptions.csd') | Select-Object -Unique
  }
  if (!$Paths.Count) { throw 'No resources selected' }
  $List = Join-Path $OutputDirectory 'paths.txt'
  [IO.File]::WriteAllLines($List, [string[]]$Paths, [Text.UTF8Encoding]::new($false))
  $Extractor = Join-Path $Engine 'tools/BundleExtractor/BundleExtractor.exe'
  if ($Info.Mode -eq 'GGPK') {
    & $Extractor --extract-ggpk-list (Join-Path $GameDirectory 'Content.ggpk') $List $OutputDirectory
  } else {
    & $Extractor --extract-list (Join-Path $GameDirectory 'Bundles2/_.index.bin') $List $OutputDirectory
  }
  if ($LASTEXITCODE -ne 0) { throw "Resource extraction failed: $LASTEXITCODE" }
  $Records = for ($i=0; $i -lt $Paths.Count; $i++) {
    $File = Join-Path $OutputDirectory ($i.ToString('D6') + '.bin')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Archive) {
      $Expected = Get-Poe2ZipEntryStreamIntegrity -Entry $Archive.GetEntry($Paths[$i])
      if ($Hash -ne $Expected.Sha256 -or (Get-Item -LiteralPath $File).Length -ne $Expected.Length) {
        throw "Installed resource differs from generated patch: $($Paths[$i])"
      }
    }
    [pscustomobject]@{ path=$Paths[$i]; sha256=$Hash; size=(Get-Item -LiteralPath $File).Length }
  }
  [IO.File]::WriteAllText((Join-Path $OutputDirectory 'resources.json'), ($Records | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $OutputDirectory 'client.json'), ($Info | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
  Write-Host "READBACK_VERIFIED $($Paths.Count) resources"
} finally { if ($Archive) { $Archive.Dispose() } }
