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

function Get-DisplayLanguageName {
    param([string]$Name)

    switch ($Name) {
        "English" { return "英文" }
        "Traditional Chinese" { return "繁体中文" }
        "Simplified Chinese" { return "简体中文" }
        "Japanese" { return "日文" }
        "Korean" { return "韩文" }
        "Russian" { return "俄文" }
        "French" { return "法文" }
        "German" { return "德文" }
        "Spanish" { return "西班牙文" }
        "Portuguese" { return "葡萄牙文" }
        "Thai" { return "泰文" }
        default {
            if ([string]::IsNullOrWhiteSpace($Name)) {
                return "未知语言"
            }
            return $Name
        }
    }
}

function Get-FriendlyFileName {
    param([string]$Name)

    switch -Regex ($Name) {
        "^English BaseItemTypes$" { return "英文 BaseItemTypes.datc64" }
        "^(.+) BaseItemTypes$" { return "$(Get-DisplayLanguageName $Matches[1]) BaseItemTypes.datc64" }
        "^English Words$" { return "英文 Words.datc64" }
        "^(.+) Words$" { return "$(Get-DisplayLanguageName $Matches[1]) Words.datc64" }
        "^UniqueGoldPrices$" { return "UniqueGoldPrices.datc64" }
        "BaseItemTypes" { return "$Name.datc64" }
        "^Content\.ggpk$" { return "游戏数据文件 Content.ggpk" }
        "^GGPKExtractor$" { return "GGPK 提取工具" }
        "^PatchBundledGGPK3\.dll$" { return "GGPK 安装工具 PatchBundledGGPK3.dll" }
        "^PatchBundledGGPK3\.runtimeconfig\.json$" { return "GGPK 安装工具运行配置" }
        "^Bundles2 _\.index\.bin$" { return "Bundles2 索引文件 _.index.bin" }
        "^BundleExtractor\.exe$" { return "BundleExtractor 提取工具" }
        "^oo2core\.dll$" { return "oo2core.dll 解压库" }
        "^PatchBundle3\.dll or PatchBundle3\.exe$" { return "Bundles2 安装工具 PatchBundle3" }
        "^price fetch script$" { return "价格获取脚本" }
        "^patch build script$" { return "补丁生成脚本" }
        default { return $Name }
    }
}

function New-FailureMessage {
    param(
        [Parameter(Mandatory = $true)][string]$Reason,
        [string[]]$Suggestions = @(),
        [string[]]$Details = @()
    )

    $Lines = @($Reason)
    if ($Suggestions.Count -gt 0) {
        $Lines += ""
        $Lines += "建议处理："
        foreach ($Suggestion in $Suggestions) {
            $Lines += "  - $Suggestion"
        }
    }
    if ($Details.Count -gt 0) {
        $Lines += ""
        $Lines += "技术信息："
        foreach ($Detail in $Details) {
            $Lines += "  - $Detail"
        }
    }
    return ($Lines -join "`n")
}

function Get-BaseItemsFailureSuggestions {
    return @(
        "请完全关闭 POE2 客户端，以及官方启动器、Steam、Epic 或 WeGame 后再运行一键更新。",
        "如果游戏刚更新过，请等官方更新完成；必要时先让平台验证或修复一次游戏文件。",
        "如果仍然失败，把下方日志路径里的内容一起发给作者排查。"
    )
}

function Convert-ErrorMessage {
    param([string]$Message)

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return "没有收到具体错误信息。请重新运行一次，并确认游戏客户端已经关闭。"
    }

    if ($Message -match '^Missing (.+?): (.+)$') {
        $Name = Get-FriendlyFileName $Matches[1]
        $Path = $Matches[2]
        $Suggestions = @("请确认补丁文件夹完整，且游戏目录选择正确。")
        if ($Matches[1] -match 'BaseItemTypes') {
            $Suggestions = Get-BaseItemsFailureSuggestions
        }
        return New-FailureMessage -Reason "缺少必要文件：$Name" -Suggestions $Suggestions -Details @("路径：$Path")
    }

    if ($Message -match '^No usable BaseItemTypes files\. Log: (.+)$') {
        return New-FailureMessage `
            -Reason "没有提取到可用的 BaseItemTypes.datc64，无法继续生成物价补丁。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("提取日志：$($Matches[1])")
    }

    if ($Message -match '^GGPKExtractor exit code: (.+)$') {
        return New-FailureMessage `
            -Reason "从 Content.ggpk 提取游戏数据失败。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("GGPK 提取工具退出码：$($Matches[1])")
    }

    if ($Message -match '^Failed to extract (.+?)\. Exit code: (.+)$') {
        $Name = Get-FriendlyFileName $Matches[1]
        return New-FailureMessage `
            -Reason "提取 $Name 失败。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("提取工具退出码：$($Matches[2])")
    }

    if ($Message -match '^Price fetch or patch build failed\. Exit code: (.+)$') {
        return New-FailureMessage `
            -Reason "获取价格或生成补丁失败。" `
            -Suggestions @(
                "请检查网络是否能访问当前价格源。",
                "如果是临时网络问题，稍后重新运行一键更新即可。"
            ) `
            -Details @("脚本退出码：$($Matches[1])")
    }

    if ($Message -match '^Patch installer failed\. Exit code: (.+)$') {
        return New-FailureMessage `
            -Reason "写入 Content.ggpk 失败。" `
            -Suggestions @(
                "请完全关闭 POE2 客户端和官方启动器后重试。",
                "如果杀毒软件拦截了写入，请把物价补丁文件夹加入信任列表。"
            ) `
            -Details @("安装工具退出码：$($Matches[1])")
    }

    if ($Message -match '^PatchBundle3 failed\. Exit code: (.+)$') {
        return New-FailureMessage `
            -Reason "写入 Bundles2 失败。" `
            -Suggestions @(
                "请完全关闭 POE2 客户端和 Steam、Epic 或 WeGame 后重试。",
                "如果游戏正在更新，请等更新完成后再运行。"
            ) `
            -Details @("安装工具退出码：$($Matches[1])")
    }

    if ($Message -match '^Invalid POE2_PATCH_BUILD_MODE') {
        return "环境变量 POE2_PATCH_BUILD_MODE 设置不正确，只能填写 append 或 fixed。"
    }

    return $Message
}

function Write-FriendlyFailure {
    param([Parameter(Mandatory = $true)]$ErrorRecord)

    $FriendlyMessage = Convert-ErrorMessage -Message ([string]$ErrorRecord.Exception.Message)
    Write-Host ""
    Write-Host "更新失败：" -ForegroundColor Red
    Write-Host $FriendlyMessage
}

function Test-ToolOutputFailure {
    param(
        [string]$Text,
        [string[]]$ExtraNeedles = @()
    )

    if ([string]::IsNullOrEmpty($Text)) {
        return $false
    }

    # Fix #11: avoid regex parsing of localized output under Windows PowerShell encoding fallback.
    $Needles = @(
        "Exception",
        "Unhandled",
        "Error:"
    ) + @(
        [string]::Concat([char]0x932F, [char]0x8AA4),
        [string]::Concat([char]0x9519, [char]0x8BEF),
        [string]::Concat([char]0x5931, [char]0x6557),
        [string]::Concat([char]0x5931, [char]0x8D25)
    ) + $ExtraNeedles

    foreach ($Needle in $Needles) {
        if ($Text.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }

    return $false
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
    Assert-Poe2PathInside -Path $ResolvedPath -Root $Root -Message "Refusing to remove file outside expected folder" | Out-Null
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
    Assert-Poe2PathInside -Path $RootPath -Root $RepoPath -Message "Refusing to clean extracted files outside patch folder" | Out-Null

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
                    $Name -match '=[0-9]+(?:\.[0-9]+)?[DE]$' -or
                    $Name -match '^[0-9]+(?:\.[0-9]+)?[DE]$' -or
                    $Name -match '^<1[DE]$' -or
                    ($Name.Length -le 12 -and $Name -match '[0-9]+(?:\.[0-9]+)?[DE]$')
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

    try {
        $Bytes = [System.IO.File]::ReadAllBytes($SourceWords)
        $Text = [System.Text.Encoding]::Unicode.GetString($Bytes)
        return [bool]($Text -match '(?:\r?\n\[[0-9]+(?:\.[0-9]+)?[DE]\]|<<\[[0-9]+(?:\.[0-9]+)?[DE]\]>>|\[[^\]\r\n|]*[0-9]+(?:\.[0-9]+)?[DE][^\]\r\n|]*\|[^\]\r\n]+\])')
    }
    catch {
        Write-Warning "检查 Words.datc64 是否已打补丁时失败：$($_.Exception.Message)"
        return $true
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
            throw "导出 BaseItemTypes 元数据签名失败。退出码：$($ExportResult.ExitCode)`n$($ExportResult.Text)"
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
        Write-Warning "BaseItemTypes 兼容性检查失败：$($_.Exception.Message)"
        return $false
    }
}

function Test-RestoreZipUsable {
    param(
        [string]$Path,
        [string]$ReferenceDat = ""
    )

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
            if (Test-BaseItemsLookPatched $TempDat) {
                return $false
            }
            if (-not [string]::IsNullOrWhiteSpace($ReferenceDat) -and -not (Test-BaseItemsCompatible $TempDat $ReferenceDat)) {
                return $false
            }
            return $true
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

function Test-PhysicalRestoreZipUsable {
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
        $ManifestEntry = $Archive.GetEntry("manifest.json")
        if ($null -eq $ManifestEntry) {
            return $false
        }

        $Reader = New-Object System.IO.StreamReader($ManifestEntry.Open(), [System.Text.Encoding]::UTF8)
        try {
            $Manifest = $Reader.ReadToEnd() | ConvertFrom-Json
        }
        catch {
            return $false
        }
        finally {
            $Reader.Dispose()
        }
        if ([string]$Manifest.kind -ne "poe2-price-patch-physical-restore") {
            return $false
        }
        if ([string]$Manifest.install_kind -ne [string]$InstallInfo.InstallKind) {
            return $false
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Manifest.target_path) -and [string]$Manifest.target_path -ne [string]$InstallInfo.TcBaseItemsPath) {
            return $false
        }

        $Entry = $Archive.GetEntry("Bundles2/_.index.bin")
        return ($null -ne $Entry -and $Entry.Length -gt 1048576)
    }
    finally {
        $Archive.Dispose()
    }
}

function Get-RestoreZipCandidates {
    $Paths = New-Object System.Collections.Generic.List[string]
    foreach ($Name in (Get-Poe2RestorePatchZipCandidateNames -InstallInfo $InstallInfo)) {
        $Paths.Add((Join-Path $RepoRoot $Name))
        $Paths.Add((Join-Path $RestoreOutDir $Name))
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

function Extract-RestoreBaseItems {
    param(
        [Parameter(Mandatory = $true)][string]$RestoreZip,
        [Parameter(Mandatory = $true)][string]$OutputDat
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($RestoreZip)
    try {
        $Entry = $Archive.GetEntry($InstallInfo.TcBaseItemsPath)
        if ($null -eq $Entry) {
            throw "还原包缺少目标文件 $($InstallInfo.TcBaseItemsPath)：$RestoreZip"
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputDat) | Out-Null
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $OutputDat, $true)
    }
    finally {
        $Archive.Dispose()
    }

    if (Test-BaseItemsLookPatched $OutputDat) {
        throw "还原包里的 BaseItemTypes.datc64 已经带有物价补丁标记，拒绝继续使用：$RestoreZip"
    }
}

function Extract-RestoreWords {
    param(
        [Parameter(Mandatory = $true)][string]$RestoreZip,
        [Parameter(Mandatory = $true)][string]$OutputWords
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($RestoreZip)
    try {
        $Entry = $Archive.GetEntry($TcWordsPath)
        if ($null -eq $Entry) {
            throw "还原包缺少目标文件 $($TcWordsPath)：$RestoreZip"
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputWords) | Out-Null
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $OutputWords, $true)
    }
    finally {
        $Archive.Dispose()
    }

    if (Test-WordsLookPatched $OutputWords) {
        throw "还原包里的 Words.datc64 已经带有物价补丁标记，拒绝继续使用：$RestoreZip"
    }
}

function New-BaseItemZip {
    param(
        [string]$SourceDat,
        [string]$SourceWords = "",
        [string]$OutputZip
    )

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
            if (Test-WordsLookPatched $SourceWords) {
                throw "检测到 Words.datc64 已包含物价补丁标记，拒绝用它创建还原包。"
            }
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

function Test-ZipEntryExists {
    param(
        [string]$ZipPath,
        [string]$EntryName
    )

    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
        return $false
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        return ($null -ne $Archive.GetEntry($EntryName.Replace("\", "/")))
    }
    finally {
        $Archive.Dispose()
    }
}

function Update-ZipEntryFromFile {
    param(
        [string]$ZipPath,
        [string]$SourceDat,
        [string]$EntryName
    )

    Assert-File $SourceDat $EntryName
    $EntryName = $EntryName.Replace("\", "/")
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ZipPath) | Out-Null

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Mode = if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
        [System.IO.Compression.ZipArchiveMode]::Update
    }
    else {
        [System.IO.Compression.ZipArchiveMode]::Create
    }

    $Archive = [System.IO.Compression.ZipFile]::Open($ZipPath, $Mode)
    try {
        $OldEntry = $Archive.GetEntry($EntryName)
        if ($null -ne $OldEntry) {
            $OldEntry.Delete()
        }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $Archive,
            $SourceDat,
            $EntryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    finally {
        $Archive.Dispose()
    }
}

function Update-RestoreZipEntry {
    param(
        [string]$ZipPath,
        [string]$SourceDat,
        [string]$EntryName
    )

    Assert-File $SourceDat "clean BaseItemTypes.datc64"
    if (Test-BaseItemsLookPatched $SourceDat) {
        throw "检测到 BaseItemTypes.datc64 已包含物价补丁标记，拒绝用它刷新还原包。"
    }

    Update-ZipEntryFromFile -ZipPath $ZipPath -SourceDat $SourceDat -EntryName $EntryName
}

function Get-ExtractedBaseItemsPathForEntry {
    param([string]$EntryName)

    return (Join-Path $LatestDir ("data\" + ($EntryName -replace '/', '_')))
}

function Update-IntlRestoreZipFromExtractedBaseItems {
    param([string]$ZipPath)

    if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") {
        return $ZipPath
    }

    $EntryNames = Get-Poe2KnownBaseItemsPaths

    $Updated = 0
    foreach ($EntryName in $EntryNames) {
        $ExtractedDat = Get-ExtractedBaseItemsPathForEntry $EntryName
        if (-not (Test-Path -LiteralPath $ExtractedDat -PathType Leaf)) {
            continue
        }
        if (Test-BaseItemsLookPatched $ExtractedDat) {
            Write-Warning "跳过还原包条目刷新：该文件已包含补丁标记。条目：$EntryName"
            continue
        }
        Update-RestoreZipEntry -ZipPath $ZipPath -SourceDat $ExtractedDat -EntryName $EntryName
        $Updated += 1

        $WordsEntryName = Get-Poe2WordsPathFromBaseItemsPath -BaseItemsPath $EntryName
        $ExtractedWords = Get-ExtractedBaseItemsPathForEntry $WordsEntryName
        if (Test-Path -LiteralPath $ExtractedWords -PathType Leaf) {
            if (Test-WordsLookPatched $ExtractedWords) {
                Write-Warning "跳过 Words 还原条目刷新：该文件已包含补丁标记。条目：$WordsEntryName"
                continue
            }
            Update-ZipEntryFromFile -ZipPath $ZipPath -SourceDat $ExtractedWords -EntryName $WordsEntryName
            $Updated += 1
        }
    }

    if ($Updated -gt 0) {
        Write-Host "已用当前干净游戏数据刷新 $Updated 个还原包条目。" -ForegroundColor Green
    }
    return (Resolve-Path -LiteralPath $ZipPath).Path
}

function New-BaseItemZipFromPhysicalRestore {
    param([string]$OutputZip)

    if ($GameMode -ne "Bundles2") {
        return $null
    }

    foreach ($Candidate in (Get-PhysicalRestoreZipCandidates)) {
        if (-not (Test-PhysicalRestoreZipUsable $Candidate)) {
            continue
        }

        $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_physical_restore_", [Guid]::NewGuid().ToString("N")))
        try {
            Add-Type -AssemblyName System.IO.Compression
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::ExtractToDirectory($Candidate, $TempDir)

            $TempIndex = Join-Path $TempDir "Bundles2\_.index.bin"
            $TempDat = Join-Path $TempDir "BaseItemTypes.datc64"
            $TempWords = Join-Path $TempDir "Words.datc64"
            $ExtractLog = Join-Path $TempDir "extract.log"
            Assert-File $TempIndex "physical restore Bundles2 _.index.bin"
            Resolve-BundleExtractor

            & $BundledBundleExtractorExe $TempIndex $InstallInfo.TcBaseItemsPath $TempDat *> $ExtractLog
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "忽略真实还原包：提取 BaseItemTypes 失败。文件：$Candidate；日志：$ExtractLog"
                continue
            }

            if (Test-BaseItemsLookPatched $TempDat) {
                Write-Warning "忽略真实还原包：提取出的 BaseItemTypes 已包含补丁标记。文件：$Candidate"
                continue
            }

            if ($SupportsUniqueWords) {
                & $BundledBundleExtractorExe $TempIndex $TcWordsPath $TempWords *> $ExtractLog
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "忽略真实还原包：提取 Words 失败。文件：$Candidate；日志：$ExtractLog"
                    continue
                }
                if (Test-WordsLookPatched $TempWords) {
                    Write-Warning "忽略真实还原包：提取出的 Words 已包含补丁标记。文件：$Candidate"
                    continue
                }
            }

            New-BaseItemZip -SourceDat $TempDat -SourceWords $TempWords -OutputZip $OutputZip
            return (Resolve-Path -LiteralPath $OutputZip).Path
        }
        finally {
            if (Test-Path -LiteralPath $TempDir -PathType Container) {
                Remove-Item -LiteralPath $TempDir -Recurse -Force
            }
        }
    }

    return $null
}

function New-PhysicalRestoreZip {
    param([string]$OutputZip)

    if ($GameMode -ne "Bundles2") {
        return $null
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputZip) | Out-Null
    if (Test-Path -LiteralPath $OutputZip -PathType Leaf) {
        Remove-Item -LiteralPath $OutputZip -Force
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::Open($OutputZip, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $Manifest = [ordered]@{
            kind = "poe2-price-patch-physical-restore"
            version = 1
            created_at = (Get-Date).ToString("o")
            install_kind = $InstallInfo.InstallKind
            target_path = $InstallInfo.TcBaseItemsPath
            mode = $GameMode
            note = "Restore these physical Bundles2 files to return to the state before this price patch was installed."
        }
        $ManifestJson = $Manifest | ConvertTo-Json -Depth 5
        $ManifestEntry = $Archive.CreateEntry("manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
        $Writer = New-Object System.IO.StreamWriter($ManifestEntry.Open(), [System.Text.UTF8Encoding]::new($false))
        try {
            $Writer.Write($ManifestJson)
        }
        finally {
            $Writer.Dispose()
        }

        foreach ($Relative in @(
            "_.index.bin",
            "_.index.high.bin",
            "_.index.low.bin",
            ".index.dbg"
        )) {
            $Source = Join-Path $Bundles2Paths.Bundles2Dir $Relative
            if (Test-Path -LiteralPath $Source -PathType Leaf) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $Source,
                    ("Bundles2/" + ($Relative -replace '\\', '/')),
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }

        $LibDir = Join-Path $Bundles2Paths.Bundles2Dir "LibGGPK3"
        if (Test-Path -LiteralPath $LibDir -PathType Container) {
            $Bundles2Prefix = $Bundles2Paths.Bundles2Dir.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
            Get-ChildItem -LiteralPath $LibDir -Recurse -File | ForEach-Object {
                $Relative = $_.FullName.Substring($Bundles2Prefix.Length).Replace("\", "/")
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $_.FullName,
                    ("Bundles2/" + $Relative),
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
    }
    finally {
        $Archive.Dispose()
    }

    return (Resolve-Path -LiteralPath $OutputZip).Path
}

function Ensure-PhysicalRestoreZip {
    param([bool]$SourceLooksPatched)

    if ($GameMode -ne "Bundles2") {
        return ""
    }

    foreach ($Candidate in (Get-PhysicalRestoreZipCandidates)) {
        if (Test-PhysicalRestoreZipUsable $Candidate) {
            $ResolvedCandidate = (Resolve-Path -LiteralPath $Candidate).Path
            if ($ResolvedCandidate -ne $PhysicalRestorePatchFolderZip) {
                Copy-Item -LiteralPath $ResolvedCandidate -Destination $PhysicalRestorePatchFolderZip -Force
                return (Resolve-Path -LiteralPath $PhysicalRestorePatchFolderZip).Path
            }
            return $ResolvedCandidate
        }
    }

    if ($SourceLooksPatched) {
        throw "缺少真实还原包，而且当前 Bundles2 已经包含物价补丁标记。请先让 Steam/Epic/WeGame 验证或修复一次游戏文件，再从干净状态运行一键更新。"
    }

    Write-Host "正在从当前干净游戏文件创建真实 Bundles2 还原包..." -ForegroundColor Yellow
    $Created = New-PhysicalRestoreZip -OutputZip $PhysicalRestoreOutZip
    if ([string]::IsNullOrWhiteSpace($Created) -or -not (Test-PhysicalRestoreZipUsable $Created)) {
        throw "创建真实还原包失败：$PhysicalRestoreOutZip"
    }

    if ($Created -ne $PhysicalRestorePatchFolderZip) {
        Copy-Item -LiteralPath $Created -Destination $PhysicalRestorePatchFolderZip -Force
    }
    return (Resolve-Path -LiteralPath $PhysicalRestorePatchFolderZip).Path
}

function Ensure-RestoreZip {
    param([string]$SourceDat)

    New-Item -ItemType Directory -Force -Path $RestoreOutDir | Out-Null
    $SourceLooksPatched = Test-BaseItemsLookPatched $SourceDat

    foreach ($Candidate in (Get-RestoreZipCandidates)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            if (-not (Test-RestoreZipUsable -Path $Candidate -ReferenceDat $SourceDat)) {
                Write-Warning "忽略不可用或已过期的还原包：$Candidate"
                continue
            }
            $ResolvedCandidate = (Resolve-Path -LiteralPath $Candidate).Path
            if ($ResolvedCandidate -ne $RestoreOutZip) {
                Copy-Item -LiteralPath $ResolvedCandidate -Destination $RestoreOutZip -Force
            }
            if (
                $SupportsUniqueWords -and
                (Test-Path -LiteralPath $TcWords -PathType Leaf) -and
                -not (Test-WordsLookPatched $TcWords) -and
                -not (Test-ZipEntryExists -ZipPath $RestoreOutZip -EntryName $TcWordsPath)
            ) {
                Update-ZipEntryFromFile -ZipPath $RestoreOutZip -SourceDat $TcWords -EntryName $TcWordsPath
            }
            return (Resolve-Path -LiteralPath $RestoreOutZip).Path
        }
    }

    if (-not $SourceLooksPatched) {
        Write-Host "正在用当前干净 BaseItemTypes 刷新固定还原包..." -ForegroundColor Yellow
        $CleanTcWords = ""
        if ($SupportsUniqueWords -and (Test-Path -LiteralPath $TcWords -PathType Leaf) -and -not (Test-WordsLookPatched $TcWords)) {
            $CleanTcWords = $TcWords
        }
        if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") {
            New-BaseItemZip -SourceDat $SourceDat -SourceWords $CleanTcWords -OutputZip $RestoreOutZip
        }
        else {
            $SeedZip = ""
            foreach ($Candidate in (Get-RestoreZipCandidates)) {
                if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                    $SeedZip = (Resolve-Path -LiteralPath $Candidate).Path
                    break
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($SeedZip) -and $SeedZip -ne $RestoreOutZip) {
                Copy-Item -LiteralPath $SeedZip -Destination $RestoreOutZip -Force
            }
            Update-RestoreZipEntry -ZipPath $RestoreOutZip -SourceDat $SourceDat -EntryName $InstallInfo.TcBaseItemsPath
            if (-not [string]::IsNullOrWhiteSpace($CleanTcWords)) {
                Update-ZipEntryFromFile -ZipPath $RestoreOutZip -SourceDat $CleanTcWords -EntryName $TcWordsPath
            }
        }
        if (-not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") -and $RestoreOutZip -ne $RestorePatchFolderZip) {
            Copy-Item -LiteralPath $RestoreOutZip -Destination $RestorePatchFolderZip -Force
        }
        return (Resolve-Path -LiteralPath $RestoreOutZip).Path
    }

    $PhysicalBaseItemZip = New-BaseItemZipFromPhysicalRestore -OutputZip $RestoreOutZip
    if (-not [string]::IsNullOrWhiteSpace($PhysicalBaseItemZip)) {
        return $PhysicalBaseItemZip
    }

    throw "当前 BaseItemTypes 已包含物价补丁标记，并且没有找到兼容的还原包。请先让官方启动器完成更新或修复游戏文件，然后重新运行一键更新。"
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

try {
$InstallInfo = Get-Poe2InstallInfo -Poe2Dir $Poe2Dir
$GameMode = $InstallInfo.Mode
$DisplayLanguageName = Get-DisplayLanguageName $InstallInfo.LanguageName
$ContentGgpk = Join-Path $Poe2Dir "Content.ggpk"
$Bundles2Paths = Get-Bundles2Paths -Poe2Dir $Poe2Dir
$LocalExtractorDll = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.dll"
$LocalExtractorExe = Join-Path $PublicToolsRoot "GGPKExtractor\GGPKExtractor.exe"
$FallbackExtractor = Join-Path $Poe2Dir "tiaoshi\extractor_tool\GGPKExtractor\bin\Release\net8.0-windows\GGPKExtractor.exe"
$BundledInstallerDir = Join-Path $RepoRoot (Get-Poe2PatchName "InstallerDir")
$BundledPatchDll = Join-Path $BundledInstallerDir "PatchBundledGGPK3.dll"
$BundledPatchRuntimeConfig = Join-Path $BundledInstallerDir "PatchBundledGGPK3.runtimeconfig.json"
$BundledBundlePatchExe = Join-Path $BundledInstallerDir "PatchBundle3.exe"
$BundledBundlePatchDll = Join-Path $BundledInstallerDir "PatchBundle3.dll"
$BundledBundleExtractorExe = Join-Path $PublicToolsRoot "BundleExtractor\BundleExtractor.exe"
$BundledOodleDll = Join-Path $PublicToolsRoot "BundleExtractor\oo2core.dll"
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
$TcBaseItems = Join-Path $LatestDir ("data\" + $InstallInfo.LanguageFileSlug)
$EnWords = Join-Path $LatestDir "data\data_balance_words.datc64"
$TcWordsPath = $InstallInfo.TcWordsPath
$TcWords = Join-Path $LatestDir ("data\" + $InstallInfo.WordsFileSlug)
$UniqueGoldPrices = Join-Path $LatestDir "data\data_balance_uniquegoldprices.datc64"
$SupportsUniqueWords = Test-Poe2UniqueWordsSupported -WordsPath $TcWordsPath
$OutDir = Join-Path $RepoRoot "output\poe2_price_patch_latest"
$RestoreOutDir = Join-Path $RepoRoot "output\restore"
$RestoreZipName = Get-Poe2FixedRestorePatchZipName -InstallInfo $InstallInfo
$PhysicalRestoreZipName = Get-Poe2FixedPhysicalRestorePatchZipName -InstallInfo $InstallInfo
$RestoreOutZip = Join-Path $RestoreOutDir $RestoreZipName
$PhysicalRestoreOutZip = Join-Path $RestoreOutDir $PhysicalRestoreZipName
$RestorePatchFolderZip = Join-Path $RepoRoot $RestoreZipName
$PhysicalRestorePatchFolderZip = Join-Path $RepoRoot $PhysicalRestoreZipName
$PricePatchZipName = Get-Poe2PatchName "PricePatchZip"
$PatchZip = Join-Path $OutDir $PricePatchZipName
$PatchedDat = Join-Path $OutDir "baseitemtypes.patched.datc64"
$PatchedWords = Join-Path $OutDir "words.patched.datc64"
$ReportJson = Join-Path $OutDir "price_patch.report.json"
$SummaryJson = Join-Path $OutDir "summary.json"

Write-Host "POE2 物价补丁更新器" -ForegroundColor Green
Write-Host "游戏目录：$Poe2Dir"
Write-Host "补丁目录：$RepoRoot"
Write-Host "检测结果：$($InstallInfo.DisplayName)" -ForegroundColor Cyan
Write-Host "安装模式：$GameMode" -ForegroundColor Cyan
Write-Host "游戏语言：$DisplayLanguageName ($($InstallInfo.ConfigLanguage))" -ForegroundColor Cyan
Write-Host "写入目标：$($InstallInfo.TcBaseItemsPath)" -ForegroundColor Cyan
if ($InstallInfo.LanguageDefaulted) {
    Write-Warning $InstallInfo.LanguageDefaultReason
}
$IsChinaClient = [bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*"
$PriceSourceName = if ($IsChinaClient) { "国服 poecurrency.top" } else { "POE2 Scout" }

if ($GameMode -eq "GGPK") {
    Assert-File $ContentGgpk "Content.ggpk"
    Assert-File $Extractor "GGPKExtractor"
    Assert-File $BundledPatchDll "PatchBundledGGPK3.dll"
    Assert-File $BundledPatchRuntimeConfig "PatchBundledGGPK3.runtimeconfig.json"
}
else {
    Assert-File $Bundles2Paths.IndexBin "Bundles2 _.index.bin"
    Resolve-BundleExtractor
}
Assert-File (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py") "price fetch script"
Assert-File (Join-Path $CodeToolsRoot "poe2_name_price_patch.py") "patch build script"
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
Stop-LegacyInstallerProcesses
Remove-LegacyFiles

if (-not $SkipExtract) {
    New-Item -ItemType Directory -Force -Path $LatestDir | Out-Null

    if ($GameMode -eq "GGPK") {
        Write-Step "从 Content.ggpk 提取最新 BaseItemTypes"
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
            Write-Host "已提取到：$LatestDir"
        }
        catch {
            Write-Warning "提取失败：$($_.Exception.Message)"
            Write-Warning "如果游戏或启动器还在运行，请完全关闭后重新运行一键更新。"
            if ((Test-Path -LiteralPath $EnBaseItems) -and (Test-Path -LiteralPath $TcBaseItems)) {
                Write-Warning "改用已有的 dat_files_latest 缓存继续。"
            }
            else {
                throw "No usable BaseItemTypes files. Log: $ExtractLog"
            }
        }
    }
    else {
        Write-Step "使用 BundleExtractor 从 Bundles2 提取最新 BaseItemTypes"

        $DestDir = Join-Path $LatestDir "data"
        New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

        Write-Host "正在提取英文 BaseItemTypes..."
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.EnBaseItemsPath $EnBaseItems
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract English BaseItemTypes. Exit code: $LASTEXITCODE"
        }
        Write-Host "已提取到：$EnBaseItems"

        Write-Host "正在提取$DisplayLanguageName BaseItemTypes..."
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.TcBaseItemsPath $TcBaseItems
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract $($InstallInfo.LanguageName) BaseItemTypes. Exit code: $LASTEXITCODE"
        }
        Write-Host "已提取到：$TcBaseItems"

        if ($SupportsUniqueWords) {
            Write-Host "正在提取英文 Words..."
            & $BundledBundleExtractorExe $Bundles2Paths.IndexBin "data/balance/words.datc64" $EnWords
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to extract English Words. Exit code: $LASTEXITCODE"
            }
            Write-Host "已提取到：$EnWords"

            Write-Host "正在提取$DisplayLanguageName Words..."
            & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $TcWordsPath $TcWords
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to extract $($InstallInfo.LanguageName) Words. Exit code: $LASTEXITCODE"
            }
            Write-Host "已提取到：$TcWords"

            Write-Host "正在提取 UniqueGoldPrices..."
            & $BundledBundleExtractorExe $Bundles2Paths.IndexBin "data/balance/uniquegoldprices.datc64" $UniqueGoldPrices
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to extract UniqueGoldPrices. Exit code: $LASTEXITCODE"
            }
            Write-Host "已提取到：$UniqueGoldPrices"
        }
        else {
            Write-Host "当前语言不支持传奇物品 Words 提取，已跳过。语言：$DisplayLanguageName" -ForegroundColor Yellow
        }
    }
}
else {
    Write-Step "跳过提取，使用已有 BaseItemTypes"
}

Assert-File $EnBaseItems "English BaseItemTypes"
Assert-File $TcBaseItems "$($InstallInfo.LanguageName) BaseItemTypes"
$CanPatchUniqueWords = (
    $SupportsUniqueWords -and
    (Test-Path -LiteralPath $EnWords -PathType Leaf) -and
    (Test-Path -LiteralPath $TcWords -PathType Leaf) -and
    (Test-Path -LiteralPath $UniqueGoldPrices -PathType Leaf)
)
if ($SupportsUniqueWords -and -not $CanPatchUniqueWords) {
    Write-Warning "传奇物品价格标记已禁用：Words 或 UniqueGoldPrices datc64 文件没有成功提取。"
}
elseif (-not $SupportsUniqueWords) {
    Write-Warning "传奇物品价格标记已禁用：当前语言没有受支持的 Words.datc64 路径。"
}
$RestoreZip = Ensure-RestoreZip $TcBaseItems
if ($GameMode -eq "GGPK" -and -not (Test-BaseItemsLookPatched $TcBaseItems)) {
    $RestoreZip = Update-IntlRestoreZipFromExtractedBaseItems -ZipPath $RestoreZip
}
$SourceBaseItemsLooksPatched = Test-BaseItemsLookPatched $TcBaseItems
if ($SourceBaseItemsLooksPatched) {
    Write-Host "当前 BaseItemTypes 已包含补丁标记，正在从固定还原包重建干净文件..." -ForegroundColor Yellow
    Extract-RestoreBaseItems -RestoreZip $RestoreZip -OutputDat $TcBaseItems
}
if ($SupportsUniqueWords -and (Test-WordsLookPatched $TcWords)) {
    Write-Host "当前 Words.datc64 已包含传奇价格标记，正在从固定还原包重建干净文件..." -ForegroundColor Yellow
    Extract-RestoreWords -RestoreZip $RestoreZip -OutputWords $TcWords
}
$CanPatchUniqueWords = (
    $SupportsUniqueWords -and
    (Test-Path -LiteralPath $EnWords -PathType Leaf) -and
    (Test-Path -LiteralPath $TcWords -PathType Leaf) -and
    -not (Test-WordsLookPatched $TcWords) -and
    (Test-Path -LiteralPath $UniqueGoldPrices -PathType Leaf)
)
Compact-LatestBaseItems $LatestDir @($EnBaseItems, $TcBaseItems, $EnWords, $TcWords, $UniqueGoldPrices)
if (-not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*")) {
    Copy-Item -LiteralPath $RestoreZip -Destination $RestorePatchFolderZip -Force
}
if ($GameMode -eq "Bundles2") {
    $PhysicalRestoreZip = Ensure-PhysicalRestoreZip -SourceLooksPatched $SourceBaseItemsLooksPatched
    Write-Host "真实还原包：" -ForegroundColor Green
    Write-Host "  $PhysicalRestoreZip"
}

Write-Step "获取 $PriceSourceName 价格并生成补丁包"
$Python = Ensure-PythonRequests -RepoRoot $RepoRoot
$PatchBuildMode = "append"
if (-not [string]::IsNullOrWhiteSpace($env:POE2_PATCH_BUILD_MODE)) {
    $PatchBuildMode = $env:POE2_PATCH_BUILD_MODE.Trim().ToLowerInvariant()
    if ($PatchBuildMode -notin @("append", "fixed")) {
        throw "Invalid POE2_PATCH_BUILD_MODE '$($env:POE2_PATCH_BUILD_MODE)'. Use append or fixed."
    }
}
Write-Host "补丁模式：$PatchBuildMode" -ForegroundColor Cyan
$BuildArgs = @(
    (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
    "--en-baseitems", $EnBaseItems,
    "--tc-baseitems", $TcBaseItems,
    "--out-dir", $OutDir,
    "--output-zip", $PatchZip,
    "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
    "--mode", $PatchBuildMode,
    "--patched-dat", $PatchedDat,
    "--report", $ReportJson,
    "--game-path", $InstallInfo.TcBaseItemsPath
)
if ($CanPatchUniqueWords) {
    $BuildArgs += @(
        "--en-words", $EnWords,
        "--tc-words", $TcWords,
        "--unique-gold-prices", $UniqueGoldPrices,
        "--patched-words", $PatchedWords,
        "--words-game-path", $TcWordsPath
    )
}
else {
    $BuildArgs += "--no-uniques"
}
if (-not $NoPoe2dbFallback -and -not $IsChinaClient) {
    $BuildArgs += "--poe2db-fallback"
}
if ($IsChinaClient) {
    $BuildArgs += @(
        "--price-source", "poecurrency-cn",
        "--poecurrency-summary-url", "https://poecurrency.top/api/summary?version=2"
    )
}

$BuildResult = Invoke-Poe2Python -Python $Python -ArgumentList $BuildArgs
if ($BuildResult.ExitCode -ne 0) {
    throw "Price fetch or patch build failed. Exit code: $($BuildResult.ExitCode)"
}

Assert-File $PatchZip $PricePatchZipName

Write-Step "复制补丁包"
$PatchFolderZip = Join-Path $RepoRoot $PricePatchZipName
Copy-Item -LiteralPath $PatchZip -Destination $PatchFolderZip -Force

Write-Host "已生成：" -ForegroundColor Green
Write-Host "  $PatchZip"
Write-Host "已复制：" -ForegroundColor Green
Write-Host "  $PatchFolderZip"

if (Test-Path -LiteralPath $SummaryJson -PathType Leaf) {
    Write-Step "生成摘要"
    Get-Content -LiteralPath $SummaryJson -Encoding UTF8
}

if ($NoOpenTool) {
    $NoInstall = $true
}

if (-not $NoInstall) {
    if ($GameMode -eq "GGPK") {
        Write-Step "写入补丁到 Content.ggpk"
        Write-Host "安装工具：$BundledPatchDll"
        Write-Host "GGPK 文件：$ContentGgpk"
        Write-Host "补丁包  ：$PatchFolderZip"

        Push-Location -LiteralPath $BundledInstallerDir
        try {
            $InstallerOutput = "" | & $Dotnet $BundledPatchDll $ContentGgpk $PatchFolderZip 2>&1
            $InstallerOutput | ForEach-Object { Write-Host $_ }
            $InstallerText = ($InstallerOutput | Out-String)
            if ($LASTEXITCODE -ne 0 -or (Test-ToolOutputFailure -Text $InstallerText)) {
                throw "Patch installer failed. Exit code: $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }
        Write-Host "补丁已写入 Content.ggpk。" -ForegroundColor Green
    }
    else {
        Write-Step "使用 PatchBundle3 写入补丁到 Bundles2"

        $UsePatchBundleDll = Test-Path -LiteralPath $BundledBundlePatchDll -PathType Leaf
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
            $BundledBundlePatchExe = Join-Path $CodeToolsRoot "PatchBundle3.exe"
        }
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
            throw "Missing PatchBundle3.dll or PatchBundle3.exe: $BundledBundlePatchDll"
        }

        $TempPatchZip = $PatchZip

        if ($UsePatchBundleDll) {
            Write-Host "Bundle3 工具：$($BundledBundlePatchDll)"
        }
        else {
            Write-Host "Bundle3 工具：$($BundledBundlePatchExe)"
        }
        Write-Host "索引文件：$($Bundles2Paths.IndexBin)"
        Write-Host "补丁包  ：$TempPatchZip"

        Push-Location -LiteralPath $BundledInstallerDir
        try {
            if ($UsePatchBundleDll) {
                $BundlePatchOutput = & $Dotnet $BundledBundlePatchDll $Bundles2Paths.IndexBin $TempPatchZip 2>&1
            }
            else {
                $BundlePatchOutput = & $BundledBundlePatchExe $Bundles2Paths.IndexBin $TempPatchZip 2>&1
            }
        }
        finally {
            Pop-Location
        }

        $BundlePatchOutput | ForEach-Object { Write-Host $_ }
        $BundlePatchText = ($BundlePatchOutput | Out-String)
        if ($LASTEXITCODE -ne 0 -or (Test-ToolOutputFailure -Text $BundlePatchText -ExtraNeedles @("FileNotFound", "Could not load"))) {
            Remove-Item -LiteralPath $TempPatchZip -Force -ErrorAction SilentlyContinue
            throw "PatchBundle3 failed. Exit code: $LASTEXITCODE"
        }

        Remove-Item -LiteralPath $TempPatchZip -Force -ErrorAction SilentlyContinue
        Write-Host "补丁已写入 Bundles2。" -ForegroundColor Green
    }
}
else {
    Write-Host "已跳过写入游戏文件，仅生成补丁包。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "完成。" -ForegroundColor Green
}
catch {
    Write-FriendlyFailure -ErrorRecord $_
    exit 1
}
