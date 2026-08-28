param(
    [string]$Poe1Dir = "",
    [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
    [string]$Poe1LanguageMode = "auto",
    [switch]$SkipExtract,
    [switch]$NoInstall,
    [switch]$SkipGameDirectoryMutex,
    [ValidateSet("", "all", "currency", "uniques", "none")]
    [string]$PatchScope = "",
    [string]$League = "",
    [bool]$LeagueIsCurrent = $true
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot "poe1_patch_common.ps1")

$CodeToolsRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:POE2_PATCH_ROOT)) {
    $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path -LiteralPath $env:POE2_PATCH_ROOT).Path
}
Set-Location -LiteralPath $RepoRoot
$script:PatchVersion = "v0.6.1"
$script:GameDirectoryMutex = $null

function Resolve-Poe1UpdateDirectory {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return (Resolve-PoePatchManualSelection -RequestedGameVersion poe1 -Path $Requested).Path
    }
    $Candidates = @(Get-Poe1GameDirectoryCandidates -PreferredRoot (Split-Path -Parent $RepoRoot))
    if ($Candidates.Count -eq 1) { return [string]$Candidates[0].Path }
    if ($Candidates.Count -eq 0) {
        throw "没有找到 POE1 客户端，请从统一界面手动选择游戏目录。"
    }
    throw "检测到多个 POE1 客户端，请从统一界面选择本次要更新的客户端。"
}

function Publish-Poe1BuildStage {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $StageFull = [System.IO.Path]::GetFullPath($Stage).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    foreach ($File in @(Get-ChildItem -LiteralPath $Stage -Recurse -File)) {
        $Relative = $File.FullName.Substring($StageFull.Length)
        $Target = Join-Path $Destination $Relative
        Copy-Poe2FileAtomically -Source $File.FullName -Destination $Target | Out-Null
    }
}
function Get-Poe1WordsRowCount {
    param([string]$WordsPath, [string]$Python)

    $Builder = Join-Path $CodeToolsRoot "build_poe1_price_patch.py"
    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @($Builder, "--check-words", $WordsPath) -Quiet
    if ($Result.ExitCode -ne 0) { throw "Words 行结构检查失败。" }
    return [int](($Result.Text | ConvertFrom-Json).row_count)
}

function Test-Poe1CacheUsable {
    param(
        [Parameter(Mandatory = $true)][string]$CacheZip,
        [Parameter(Mandatory = $true)][string]$CacheMetadata,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$CurrentWords,
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    if (-not (Test-Path -LiteralPath $CacheZip -PathType Leaf) -or
        -not (Test-Path -LiteralPath $CacheMetadata -PathType Leaf)) { return $false }
    $BaseTemp = ""
    $WordsTemp = ""
    try {
        $Metadata = Get-Content -LiteralPath $CacheMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$Metadata.game_version -ne "poe1" -or
            [string]$Metadata.patch_scope -ne $Scope -or
            [string]$Metadata.price_source -ne $Source -or
            ([string]$Metadata.league -ne [string]$League -and -not [string]::IsNullOrWhiteSpace([string]$Metadata.league)) -or
            [string]$Metadata.baseitems_path -ne [string]$InstallInfo.TcBaseItemsPath -or
            [string]$Metadata.words_path -ne [string]$InstallInfo.TcWordsPath) { return $false }
        $BaseTemp = Get-Poe1ZipEntryTempFile -ZipPath $CacheZip -EntryName $InstallInfo.TcBaseItemsPath
        $WordsTemp = Get-Poe1ZipEntryTempFile -ZipPath $CacheZip -EntryName $InstallInfo.TcWordsPath
        if (-not (Test-Poe1BaseItemsCompatible -LeftDat $BaseTemp -RightDat $CurrentBaseItems -RepoRoot $RepoRoot)) { return $false }
        return ((Get-Poe1WordsRowCount -WordsPath $WordsTemp -Python $Python) -eq
            (Get-Poe1WordsRowCount -WordsPath $CurrentWords -Python $Python))
    }
    catch {
        Write-Warning "忽略不可用的 POE1 价格缓存：$($_.Exception.Message)"
        return $false
    }
    finally {
        foreach ($Temp in @($BaseTemp, $WordsTemp)) {
            if (-not [string]::IsNullOrWhiteSpace($Temp) -and (Test-Path -LiteralPath $Temp -PathType Leaf)) {
                Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Get-Poe1Bundles2InstalledState {
    if (
        [string]::IsNullOrWhiteSpace($Poe1Bundles2InstalledStatePath) -or
        -not (Test-Path -LiteralPath $Poe1Bundles2InstalledStatePath -PathType Leaf)
    ) {
        return $null
    }

    try {
        $State = Get-Content -LiteralPath $Poe1Bundles2InstalledStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$State.kind -ne "poe1-price-patch-bundles2-installed-state" -or [int]$State.version -ne 1) {
            throw "状态文件类型或版本无效。"
        }
        if ([string]$State.install_kind -ne [string]$InstallInfo.InstallKind) {
            throw "状态文件属于其它客户端。"
        }
        if ([string]$State.target_path -ne [string]$InstallInfo.TcBaseItemsPath) {
            throw "状态文件属于其它语言目标。"
        }
        if ([string]$State.restore_zip_sha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "状态文件缺少有效的还原包 SHA256。"
        }
        if (
            $null -eq $State.bundles2_fingerprint -or
            [int]$State.bundles2_fingerprint.version -ne 1 -or
            [string]$State.bundles2_fingerprint.algorithm -ne "path-length-sha256-v1"
        ) {
            throw "状态文件缺少有效的 Bundles2 指纹。"
        }
        return $State
    }
    catch {
        Write-Warning "忽略无效的 POE1 上次安装状态：$($_.Exception.Message)"
        return $null
    }
}

function Test-Poe1Bundles2InstalledStateCurrent {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$RestoreZip
    )

    try {
        $RestoreHash = (Get-FileHash -LiteralPath $RestoreZip -Algorithm SHA256 -ErrorAction Stop).Hash
        if (-not $RestoreHash.Equals([string]$State.restore_zip_sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "POE1 上次安装状态绑定的真实还原包与当前候选不同。"
        }
        Assert-Poe1Bundles2MutationFingerprintCurrent `
            -Expected $State.bundles2_fingerprint `
            -Poe1Dir $Poe1Dir | Out-Null
        $script:LastPoe1Bundles2InstalledStateError = ""
        return $true
    }
    catch {
        $script:LastPoe1Bundles2InstalledStateError = $_.Exception.Message
        return $false
    }
}

function Write-Poe1Bundles2InstalledState {
    param([Parameter(Mandatory = $true)][string]$RestoreZip)

    $Fingerprint = Get-Poe1Bundles2MutationFingerprint -Poe1Dir $Poe1Dir
    $RestoreHash = (Get-FileHash -LiteralPath $RestoreZip -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    Write-Poe1JsonAtomically -Path $Poe1Bundles2InstalledStatePath -Value ([ordered]@{
            kind = "poe1-price-patch-bundles2-installed-state"
            version = 1
            updated_at = (Get-Date).ToUniversalTime().ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
            install_kind = $InstallInfo.InstallKind
            target_path = $InstallInfo.TcBaseItemsPath
            restore_zip_sha256 = $RestoreHash
            bundles2_fingerprint = $Fingerprint
        })
    return $Fingerprint
}

function Publish-Poe1PhysicalRestoreZip {
    param([Parameter(Mandatory = $true)][string]$Source)

    $SourceFull = (Resolve-Path -LiteralPath $Source).Path
    $DestinationFull = [System.IO.Path]::GetFullPath($PersistentPhysicalRestore)
    if (-not $SourceFull.Equals($DestinationFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Copy-Poe2FileAtomically -Source $SourceFull -Destination $DestinationFull | Out-Null
    }
    Assert-Poe1PhysicalRestoreZip -ZipPath $DestinationFull -InstallInfo $InstallInfo `
        -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot | Out-Null
    return $DestinationFull
}

function New-CleanPoe1PhysicalRestoreZipFromPatchedState {
    param([Parameter(Mandatory = $true)][string]$OutputZip)

    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe1_clean_restore_migration_", [Guid]::NewGuid().ToString("N")))
    $SandboxRoot = Join-Path $TempRoot "sandbox"
    $SandboxBundles2 = Join-Path $SandboxRoot "Bundles2"
    $CleanBaseItems = ""
    try {
        Write-Host "正在离线清理旧 POE1 价格层并重建安全还原基线；真实游戏文件不会被修改..." -ForegroundColor Yellow
        Assert-Poe2GameFilesAvailable -Poe2Dir $Poe1Dir -IndexPath (Join-Path $Poe1Dir "Bundles2\_.index.bin")
        $MigrationPrecondition = Get-Poe1Bundles2MutationFingerprint -Poe1Dir $Poe1Dir
        New-Item -ItemType Directory -Force -Path $SandboxBundles2 | Out-Null
        foreach ($Name in @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")) {
            $Source = Join-Path $Poe1Dir ("Bundles2\" + $Name)
            if (Test-Path -LiteralPath $Source -PathType Leaf) {
                Copy-Item -LiteralPath $Source -Destination (Join-Path $SandboxBundles2 $Name) -Force
            }
        }
        Assert-Poe1File -Path (Join-Path $SandboxBundles2 "_.index.bin") -Name "沙盒 Bundles2\_.index.bin"
        $SourceLib = Join-Path $Poe1Dir "Bundles2\LibGGPK3"
        if (Test-Path -LiteralPath $SourceLib -PathType Container) {
            Copy-Item -LiteralPath $SourceLib -Destination $SandboxBundles2 -Recurse -Force
        }
        Assert-Poe1Bundles2MutationFingerprintCurrent -Expected $MigrationPrecondition -Poe1Dir $Poe1Dir | Out-Null

        $MigrationDotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
        Invoke-Poe1LogicalRestoreWithRetry -Poe1Dir $SandboxRoot -InstallInfo $InstallInfo `
            -LogicalRestoreZip $LogicalRestoreZip -RepoRoot $RepoRoot -Dotnet $MigrationDotnet
        $CleanBaseItems = Get-Poe1ZipEntryTempFile -ZipPath $LogicalRestoreZip -EntryName $InstallInfo.TcBaseItemsPath
        $Created = New-Poe1PhysicalRestoreZip -Poe1Dir $SandboxRoot -InstallInfo $InstallInfo `
            -CurrentBaseItems $CleanBaseItems -OutputZip $OutputZip -RepoRoot $RepoRoot
        Assert-Poe1PhysicalRestoreZip -ZipPath $Created -InstallInfo $InstallInfo `
            -CurrentBaseItems $CleanBaseItems -RepoRoot $RepoRoot `
            -Poe1Dir $SandboxRoot -RequireCurrentPhysical | Out-Null
        Assert-Poe1Bundles2MutationFingerprintCurrent -Expected $MigrationPrecondition -Poe1Dir $Poe1Dir | Out-Null
        Write-Host "POE1 干净还原基线已在离线沙盒中重建并验证。" -ForegroundColor Green
        return $Created
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($CleanBaseItems) -and (Test-Path -LiteralPath $CleanBaseItems -PathType Leaf)) {
            Remove-Item -LiteralPath $CleanBaseItems -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-CleanPoe1LogicalRestoreZipFromPatchedState {
    param(
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$CurrentWords,
        [Parameter(Mandatory = $true)][string]$OutputZip
    )

    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe1_logical_restore_migration_", [Guid]::NewGuid().ToString("N")))
    $CleanLayerZip = Join-Path $TempRoot "clean-layer.zip"
    $CleanBaseItems = Join-Path $TempRoot "baseitemtypes.clean.datc64"
    $CleanWords = Join-Path $TempRoot "words.clean.datc64"
    try {
        New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
        Write-Host "没有可用的 POE1 专属基线，正在只清理本工具价格标记并离线重建..." -ForegroundColor Yellow
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            (Join-Path $CodeToolsRoot "build_poe1_price_patch.py"),
            "--patch-scope", "none",
            "--fallback-price-sources", "none",
            "--tc-baseitems", $CurrentBaseItems,
            "--tc-words", $CurrentWords,
            "--out-dir", $TempRoot,
            "--output-zip", $CleanLayerZip,
            "--patched-dat", $CleanBaseItems,
            "--patched-words", $CleanWords,
            "--game-path", $InstallInfo.TcBaseItemsPath,
            "--words-game-path", $InstallInfo.TcWordsPath,
            "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
            "--no-uniques",
            "--strict-feature-cleanup"
        )
        if ($Result.ExitCode -ne 0) {
            throw "POE1 自动清理迁移失败，退出码：$($Result.ExitCode)。$($Result.Text)"
        }
        Assert-Poe1File -Path $CleanBaseItems -Name "清理后的 POE1 BaseItemTypes"
        Assert-Poe1File -Path $CleanWords -Name "清理后的 POE1 Words"
        if (Test-Poe1BaseItemsLookPatched -SourceDat $CleanBaseItems -RepoRoot $RepoRoot) {
            throw "POE1 清理后的 BaseItemTypes 仍包含价格标记。"
        }
        if (Test-Poe1WordsLookPatched -SourceWords $CleanWords -RepoRoot $RepoRoot) {
            throw "POE1 清理后的 Words 仍包含价格标记。"
        }
        if (-not (Test-Poe1BaseItemsCompatible -LeftDat $CleanBaseItems -RightDat $CurrentBaseItems -RepoRoot $RepoRoot)) {
            throw "POE1 清理后的 BaseItemTypes 结构发生了非预期变化。"
        }
        $Created = New-Poe1LogicalRestoreZip -BaseItems $CleanBaseItems -Words $CleanWords `
            -OutputZip $OutputZip -InstallInfo $InstallInfo -RepoRoot $RepoRoot
        if (-not (Test-Poe1LogicalRestoreZip -ZipPath $Created -InstallInfo $InstallInfo `
                -CurrentBaseItems $CurrentBaseItems -RepoRoot $RepoRoot)) {
            throw "POE1 自动生成的专属还原基线未通过最终校验。"
        }
        return $Created
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-Poe1PhysicalRestoreZip {
    param([Parameter(Mandatory = $true)][bool]$SourceLooksPatched)

    $Candidates = New-Object System.Collections.Generic.List[object]
    foreach ($Name in $PhysicalRestoreNames) {
        foreach ($Path in @((Join-Path $PersistentDir $Name), (Join-Path $RestoreDir $Name))) {
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { continue }
            try {
                $Manifest = Assert-Poe1PhysicalRestoreZip -ZipPath $Path -InstallInfo $InstallInfo `
                    -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot
                $Resolved = (Resolve-Path -LiteralPath $Path).Path
                $Candidates.Add([pscustomobject]@{
                        Path = $Resolved
                        Manifest = $Manifest
                        Hash = (Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash
                    })
            }
            catch {
                Write-Warning "忽略不可用的 POE1 真实还原包：$($_.Exception.Message)"
            }
        }
    }

    $InstalledState = Get-Poe1Bundles2InstalledState
    if ($null -ne $InstalledState) {
        $StateCandidates = @($Candidates | Where-Object {
                ([string]$_.Hash).Equals([string]$InstalledState.restore_zip_sha256, [System.StringComparison]::OrdinalIgnoreCase)
            })
        if ($StateCandidates.Count -gt 0) {
            $Selected = @($StateCandidates | Sort-Object { (Get-Item -LiteralPath $_.Path).LastWriteTimeUtc } -Descending)[0]
            if (Test-Poe1Bundles2InstalledStateCurrent -State $InstalledState -RestoreZip $Selected.Path) {
                return Publish-Poe1PhysicalRestoreZip -Source $Selected.Path
            }
            Write-Warning "POE1 上次安装后 Bundles2 又发生了变化，将刷新安全还原基线：$script:LastPoe1Bundles2InstalledStateError"
        }
        else {
            Write-Warning "POE1 上次安装状态绑定的真实还原包已不存在，将刷新安全还原基线。"
        }
    }

    $CurrentCandidates = New-Object System.Collections.Generic.List[object]
    foreach ($Candidate in $Candidates) {
        try {
            Assert-Poe1PhysicalRestoreCurrent -Manifest $Candidate.Manifest -Poe1Dir $Poe1Dir | Out-Null
            $CurrentCandidates.Add($Candidate)
        }
        catch {
            # Stale pre-install snapshots are migrated below when the active
            # DAT still contains this tool's price layer.
        }
    }
    if ($CurrentCandidates.Count -gt 0) {
        $Selected = @($CurrentCandidates | Sort-Object { (Get-Item -LiteralPath $_.Path).LastWriteTimeUtc } -Descending)[0]
        return Publish-Poe1PhysicalRestoreZip -Source $Selected.Path
    }

    if ($SourceLooksPatched) {
        $Migrated = New-CleanPoe1PhysicalRestoreZipFromPatchedState -OutputZip $PhysicalRestoreOut
        return Publish-Poe1PhysicalRestoreZip -Source $Migrated
    }

    Write-Host "正在备份 Bundles2 索引与 LibGGPK3；首次运行可能需要一些时间..." -ForegroundColor Yellow
    $Created = New-Poe1PhysicalRestoreZip -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
        -CurrentBaseItems $Extracted.LocalizedBaseItems -OutputZip $PhysicalRestoreOut -RepoRoot $RepoRoot
    return Publish-Poe1PhysicalRestoreZip -Source $Created
}

try {
    $Poe1Dir = Resolve-Poe1UpdateDirectory -Requested $Poe1Dir
    if (-not $SkipGameDirectoryMutex) {
        $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe1Dir
    }
    try {
        Save-PoePatchGameDirectory -GameVersion poe1 -GameDirectory $Poe1Dir | Out-Null
        Save-Poe1LanguageMode -LanguageMode $Poe1LanguageMode | Out-Null
    }
    catch {
        Write-Warning "无法保存最近使用的 POE1 目录，本次更新仍会继续：$($_.Exception.Message)"
    }

    if ([string]::IsNullOrWhiteSpace($PatchScope)) { $PatchScope = "all" }
    $InstallInfo = Get-Poe1InstallInfo -GameDirectory $Poe1Dir -LanguageMode $Poe1LanguageMode
    $DisplayLanguage = Get-Poe1DisplayLanguageName -Name $InstallInfo.LanguageName
    $IsChinaClient = [bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "POE1-CN-*"
    if ($PatchScope -ne "none") {
        $SelectedLeague = Resolve-PoePatchLeagueSelection -GameVersion "poe1" `
            -League $League -TimeoutSeconds 20
        $League = [string]$SelectedLeague.PoeNinjaLeague
        $LeagueIsCurrent = [bool]$SelectedLeague.IsCurrent
        if ($IsChinaClient -and -not $LeagueIsCurrent) {
            throw "POE1 国服价格源只支持当前赛季，不能使用历史赛季，已停止以避免混用数据。"
        }
    }
    $PriceSource = if ($IsChinaClient) {
        "poecurrency-cn"
    }
    else {
        "poe-ninja"
    }
    $OutputKey = Get-Poe1PatchOutputKey -Poe1Dir $Poe1Dir
    $ClientOutputRoot = Join-Path $RepoRoot ("output\poe1\" + $OutputKey)
    $DatDir = Join-Path $ClientOutputRoot "dat_files_latest"
    $OutDir = Join-Path $ClientOutputRoot "price_patch_latest"
    $RestoreDir = Join-Path $ClientOutputRoot "restore"
    $LogicalRestoreName = Get-Poe1LogicalRestoreZipName -InstallInfo $InstallInfo
    $PhysicalRestoreName = Get-Poe1PhysicalRestoreZipName -InstallInfo $InstallInfo
    $PhysicalRestoreNames = @(Get-Poe1PhysicalRestoreZipCandidateNames -InstallInfo $InstallInfo)
    $LogicalRestoreOut = Join-Path $RestoreDir $LogicalRestoreName
    $PhysicalRestoreOut = Join-Path $RestoreDir $PhysicalRestoreName
    $PersistentDir = Join-Path $Poe1Dir ".poe1-price-patch"
    $PersistentLogicalRestore = Join-Path $PersistentDir $LogicalRestoreName
    $PersistentPhysicalRestore = Join-Path $PersistentDir $PhysicalRestoreName
    $StateKind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    $StateLanguage = ([string]$InstallInfo.EffectiveLanguageCode -replace '[^A-Za-z0-9_-]+', '_')
    $Poe1Bundles2InstalledStatePath = Join-Path $PersistentDir "POE1Bundles2InstalledState_${StateKind}_${StateLanguage}.json"
    $PatchZip = Join-Path $OutDir "POE1物价补丁.zip"
    $PatchFolderZip = Join-Path $RepoRoot "POE1物价补丁.zip"
    $PatchedDat = Join-Path $OutDir "baseitemtypes.patched.datc64"
    $PatchedWords = Join-Path $OutDir "words.patched.datc64"

    Write-Host "POE1 物价补丁更新器 $script:PatchVersion" -ForegroundColor Green
    Write-Host "游戏目录：$Poe1Dir"
    Write-Host "客户端  ：$($InstallInfo.DisplayName)" -ForegroundColor Cyan
    Write-Host "安装模式：$($InstallInfo.Mode)" -ForegroundColor Cyan
    $ConfiguredLanguageText = if ([string]::IsNullOrWhiteSpace([string]$InstallInfo.ConfiguredLanguage)) { "未读取到" } else { [string]$InstallInfo.ConfiguredLanguage }
    Write-Host "配置语言：$ConfiguredLanguageText" -ForegroundColor Cyan
    Write-Host "写入语言：$DisplayLanguage ($($InstallInfo.EffectiveLanguageCode))" -ForegroundColor Cyan
    Write-Host "语言模式：$($InstallInfo.LanguageMode)；$($InstallInfo.LanguageSelectionReason)" -ForegroundColor Cyan
    Write-Host "价格单位：混沌石 / 神圣石 (C/D)" -ForegroundColor Cyan
    Write-Host "更新范围：$PatchScope" -ForegroundColor Cyan
    Write-Host "数据来源：$PriceSource" -ForegroundColor Cyan
    if ($InstallInfo.LanguageDefaulted) { Write-Warning $InstallInfo.LanguageDefaultReason }

    Assert-Poe1File -Path (Join-Path $CodeToolsRoot "build_poe1_price_patch.py") -Name "POE1 价格构建器"
    Assert-Poe1File -Path (Join-Path $CodeToolsRoot "poe2_name_price_patch.py") -Name "DAT 写入器"
    if ($InstallInfo.Mode -eq "Bundles2") {
        Assert-Poe1File -Path (Join-Path $Poe1Dir "Bundles2\_.index.bin") -Name "Bundles2\_.index.bin"
    }
    else {
        Assert-Poe1File -Path (Join-Path $Poe1Dir "Content.ggpk") -Name "Content.ggpk"
    }

    New-Item -ItemType Directory -Force -Path $DatDir, $OutDir, $RestoreDir | Out-Null
    if (-not $SkipExtract) {
        Write-Poe1Step "从 $($InstallInfo.Mode) 精确提取 POE1 DAT"
        $Extracted = Invoke-Poe1ExtractDatFiles -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
            -RepoRoot $RepoRoot -DestinationDirectory $DatDir
    }
    else {
        $Extracted = [pscustomobject]@{
            LocalizedBaseItems = Join-Path $DatDir $InstallInfo.LanguageFileSlug
            LocalizedWords = Join-Path $DatDir $InstallInfo.WordsFileSlug
            EnglishBaseItems = Join-Path $DatDir (($InstallInfo.EnBaseItemsPath -replace '/', '_'))
            EnglishWords = Join-Path $DatDir (($InstallInfo.EnWordsPath -replace '/', '_'))
        }
    }
    Assert-Poe1File -Path $Extracted.LocalizedBaseItems -Name "$DisplayLanguage BaseItemTypes.datc64"
    Assert-Poe1File -Path $Extracted.LocalizedWords -Name "$DisplayLanguage Words.datc64"
    $CurrentBasePatched = Test-Poe1BaseItemsLookPatched -SourceDat $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot
    $CurrentWordsPatched = Test-Poe1WordsLookPatched -SourceWords $Extracted.LocalizedWords -RepoRoot $RepoRoot

    Write-Poe1Step "准备独立 POE1 还原底板"
    $LogicalRestoreZip = ""
    foreach ($Candidate in @($PersistentLogicalRestore, $LogicalRestoreOut)) {
        if (Test-Poe1LogicalRestoreZip -ZipPath $Candidate -InstallInfo $InstallInfo `
            -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot) {
            $LogicalRestoreZip = (Resolve-Path -LiteralPath $Candidate).Path
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($LogicalRestoreZip)) {
        if ($CurrentBasePatched -or $CurrentWordsPatched) {
            try {
                $LogicalRestoreZip = New-CleanPoe1LogicalRestoreZipFromPatchedState `
                    -CurrentBaseItems $Extracted.LocalizedBaseItems `
                    -CurrentWords $Extracted.LocalizedWords `
                    -OutputZip $LogicalRestoreOut
            }
            catch {
                throw "POE1 专属基线缺失，自动清理迁移也无法通过严格校验：$($_.Exception.Message)。为避免损坏游戏，已拒绝写入；请通过游戏平台校验/修复后重试。"
            }
        }
        else {
            $LogicalRestoreZip = New-Poe1LogicalRestoreZip -BaseItems $Extracted.LocalizedBaseItems `
                -Words $Extracted.LocalizedWords -OutputZip $LogicalRestoreOut -InstallInfo $InstallInfo -RepoRoot $RepoRoot
        }
    }
    if (-not $NoInstall) {
        New-Item -ItemType Directory -Force -Path $PersistentDir | Out-Null
        if (-not ([System.IO.Path]::GetFullPath($LogicalRestoreZip)).Equals(
                [System.IO.Path]::GetFullPath($PersistentLogicalRestore),
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            Copy-Poe2FileAtomically -Source $LogicalRestoreZip -Destination $PersistentLogicalRestore | Out-Null
        }
        $LogicalRestoreZip = $PersistentLogicalRestore
    }

    $PhysicalRestoreZip = ""
    $Poe1Bundles2WritePrecondition = $null
    if ($InstallInfo.Mode -eq "Bundles2" -and -not $NoInstall) {
        $PhysicalRestoreZip = Ensure-Poe1PhysicalRestoreZip `
            -SourceLooksPatched ($CurrentBasePatched -or $CurrentWordsPatched)
        $Poe1Bundles2WritePrecondition = Get-Poe1Bundles2MutationFingerprint -Poe1Dir $Poe1Dir
    }

    Write-Poe1Step "获取实时 POE1 价格并生成 C/D 补丁"
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $LeagueCacheToken = Get-PoePatchLeagueCacheToken -ScoutLeague $League -PoeNinjaLeague $League
    $CacheKey = [string]::Join("_", @(
            ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_'),
            ([string]$InstallInfo.EffectiveLanguageCode -replace '[^A-Za-z0-9_-]+', '_'),
            $PatchScope,
            $PriceSource,
            $LeagueCacheToken
        ))
    $CacheDir = Join-Path $RepoRoot ("output\poe1_price_patch_cache\" + $CacheKey)
    $CachedPatchZip = Join-Path $CacheDir "POE1物价补丁.zip"
    $CacheMetadata = Join-Path $CacheDir "metadata.json"
    $BuildStage = Join-Path $ClientOutputRoot ([string]::Concat(".build-", [Guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Force -Path $BuildStage | Out-Null
    $BuildFailed = $false
    $BuildFailure = ""
    try {
        $StagePatchZip = Join-Path $BuildStage "POE1物价补丁.zip"
        $StagePatchedDat = Join-Path $BuildStage "baseitemtypes.patched.datc64"
        $StagePatchedWords = Join-Path $BuildStage "words.patched.datc64"
        $BuilderArgs = @(
            (Join-Path $CodeToolsRoot "build_poe1_price_patch.py"),
            "--price-source", $PriceSource,
            "--tc-baseitems", $Extracted.LocalizedBaseItems,
            "--tc-words", $Extracted.LocalizedWords,
            "--out-dir", $BuildStage,
            "--patch-scope", $PatchScope,
            "--output-zip", $StagePatchZip,
            "--patched-dat", $StagePatchedDat,
            "--patched-words", $StagePatchedWords,
            "--game-path", $InstallInfo.TcBaseItemsPath,
            "--words-game-path", $InstallInfo.TcWordsPath,
            "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py")
        )
        if (-not [string]::IsNullOrWhiteSpace([string]$Extracted.EnglishBaseItems) -and
            (Test-Path -LiteralPath $Extracted.EnglishBaseItems -PathType Leaf)) {
            $BuilderArgs += @("--en-baseitems", $Extracted.EnglishBaseItems)
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Extracted.EnglishWords) -and
            (Test-Path -LiteralPath $Extracted.EnglishWords -PathType Leaf)) {
            $BuilderArgs += @("--en-words", $Extracted.EnglishWords)
        }
        if (-not [string]::IsNullOrWhiteSpace($League)) {
            $BuilderArgs += @(
                "--league", $League,
                "--fallback-price-sources", "poe2scout"
            )
        }
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList $BuilderArgs
        if ($Result.ExitCode -ne 0) {
            throw "POE1 实时价格构建失败，退出码：$($Result.ExitCode)。$($Result.Text)"
        }
        Assert-Poe1File -Path $StagePatchZip -Name "POE1物价补丁.zip"
        Assert-Poe1PatchZipCompatible -ZipPath $StagePatchZip -InstallInfo $InstallInfo `
            -CurrentBaseItems $Extracted.LocalizedBaseItems -CurrentWords $Extracted.LocalizedWords -RepoRoot $RepoRoot
    }
    catch {
        $BuildFailed = $true
        $BuildFailure = $_.Exception.Message
    }

    if (-not $BuildFailed) {
        Assert-Poe1File -Path (Join-Path $BuildStage "POE1物价补丁.zip") -Name "POE1物价补丁.zip"
        Publish-Poe1BuildStage -Stage $BuildStage -Destination $OutDir
        New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
        Copy-Poe2FileAtomically -Source $PatchZip -Destination $CachedPatchZip | Out-Null
        $Signature = Get-Poe1BaseItemsSignature -SourceDat $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot
        Write-Poe1JsonAtomically -Path $CacheMetadata -Value ([ordered]@{
                game_version = "poe1"
                patch_scope = $PatchScope
                price_source = $PriceSource
                league = $League
                league_is_current = [bool]$LeagueIsCurrent
                install_kind = [string]$InstallInfo.InstallKind
                baseitems_path = [string]$InstallInfo.TcBaseItemsPath
                words_path = [string]$InstallInfo.TcWordsPath
                compatibility_sha256 = [string]$Signature.compatibility_sha256
                saved_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            })
    }
    else {
        Write-Warning "实时构建失败：$BuildFailure"
        if (Test-Poe1CacheUsable -CacheZip $CachedPatchZip -CacheMetadata $CacheMetadata `
            -CurrentBaseItems $Extracted.LocalizedBaseItems -CurrentWords $Extracted.LocalizedWords `
            -Scope $PatchScope -Source $PriceSource -Python $Python `
            -InstallInfo $InstallInfo -RepoRoot $RepoRoot) {
            Write-Warning "已使用当前客户端、语言和范围完全匹配的 POE1 缓存。"
            Copy-Poe2FileAtomically -Source $CachedPatchZip -Destination $PatchZip | Out-Null
        }
        else {
            throw "实时价格与兼容缓存均不可用，本次未修改 POE1 游戏文件。原始错误：$BuildFailure"
        }
    }
    Copy-Poe2FileAtomically -Source $PatchZip -Destination $PatchFolderZip | Out-Null

    if ($NoInstall) {
        Write-Host "NoInstall 已启用：补丁与还原包已生成，未修改任何 POE1 游戏文件。" -ForegroundColor Yellow
        Write-Host "补丁包：$PatchZip"
        return
    }

    Write-Poe1Step "写入并读回校验 POE1 补丁"
    $Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
    if ($InstallInfo.Mode -eq "Bundles2") {
        Assert-Poe1PhysicalRestoreZip -ZipPath $PhysicalRestoreZip -InstallInfo $InstallInfo `
            -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot | Out-Null
        Assert-Poe1Bundles2MutationFingerprintCurrent `
            -Expected $Poe1Bundles2WritePrecondition `
            -Poe1Dir $Poe1Dir | Out-Null
    }
    try {
        Invoke-Poe1PatchWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $PatchZip `
            -RepoRoot $RepoRoot -Dotnet $Dotnet
        if ($InstallInfo.Mode -eq "Bundles2") {
            Write-Poe1Bundles2InstalledState -RestoreZip $PhysicalRestoreZip | Out-Null
        }
    }
    catch {
        $InstallFailure = $_.Exception.Message
        Write-Warning "POE1 写入失败，正在自动恢复更新前状态：$InstallFailure"
        try {
            if ($InstallInfo.Mode -eq "Bundles2") {
                Restore-Poe1PhysicalBundles2 -Poe1Dir $Poe1Dir -ZipPath $PhysicalRestoreZip `
                    -InstallInfo $InstallInfo -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot
            }
            else {
                Invoke-Poe1LogicalRestoreWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
                    -LogicalRestoreZip $LogicalRestoreZip -RepoRoot $RepoRoot -Dotnet $Dotnet
            }
        }
        catch {
            throw "POE1 写入失败，自动恢复也失败。写入错误：$InstallFailure；恢复错误：$($_.Exception.Message)"
        }
        throw "POE1 写入失败，但已自动恢复并通过校验：$InstallFailure"
    }
    Write-Host "POE1 物价补丁已安装并通过读回校验。" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "POE1 更新失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (-not [string]::IsNullOrWhiteSpace([string]$BuildStage) -and
        (Test-Path -LiteralPath $BuildStage -PathType Container)) {
        Remove-Item -LiteralPath $BuildStage -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $script:GameDirectoryMutex) {
        try { $script:GameDirectoryMutex.ReleaseMutex() } catch { }
        $script:GameDirectoryMutex.Dispose()
    }
}
