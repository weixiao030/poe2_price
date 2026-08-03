param(
    [string]$Poe1Dir = "",
    [switch]$SkipExtract,
    [switch]$NoInstall,
    [switch]$SkipGameDirectoryMutex,
    [ValidateSet("", "all", "currency", "uniques", "none")]
    [string]$PatchScope = ""
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
$script:PatchVersion = "v0.5.0"
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
        [string]$CacheZip,
        [string]$CacheMetadata,
        [string]$CurrentBaseItems,
        [string]$CurrentWords,
        [string]$Scope,
        [string]$Source,
        [string]$Python
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

try {
    $Poe1Dir = Resolve-Poe1UpdateDirectory -Requested $Poe1Dir
    if (-not $SkipGameDirectoryMutex) {
        $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe1Dir
    }
    try {
        Save-PoePatchGameDirectory -GameVersion poe1 -GameDirectory $Poe1Dir | Out-Null
    }
    catch {
        Write-Warning "无法保存最近使用的 POE1 目录，本次更新仍会继续：$($_.Exception.Message)"
    }

    if ([string]::IsNullOrWhiteSpace($PatchScope)) { $PatchScope = "all" }
    $InstallInfo = Get-Poe1InstallInfo -GameDirectory $Poe1Dir
    $DisplayLanguage = Get-Poe1DisplayLanguageName -Name $InstallInfo.LanguageName
    $PriceSource = if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "POE1-CN-*") {
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
    $LogicalRestoreOut = Join-Path $RestoreDir $LogicalRestoreName
    $PhysicalRestoreOut = Join-Path $RestoreDir $PhysicalRestoreName
    $PersistentDir = Join-Path $Poe1Dir ".poe1-price-patch"
    $PersistentLogicalRestore = Join-Path $PersistentDir $LogicalRestoreName
    $PersistentPhysicalRestore = Join-Path $PersistentDir $PhysicalRestoreName
    $PatchZip = Join-Path $OutDir "POE1物价补丁.zip"
    $PatchFolderZip = Join-Path $RepoRoot "POE1物价补丁.zip"
    $PatchedDat = Join-Path $OutDir "baseitemtypes.patched.datc64"
    $PatchedWords = Join-Path $OutDir "words.patched.datc64"

    Write-Host "POE1 物价补丁更新器 $script:PatchVersion" -ForegroundColor Green
    Write-Host "游戏目录：$Poe1Dir"
    Write-Host "客户端  ：$($InstallInfo.DisplayName)" -ForegroundColor Cyan
    Write-Host "安装模式：$($InstallInfo.Mode)" -ForegroundColor Cyan
    Write-Host "游戏语言：$DisplayLanguage ($($InstallInfo.ConfigLanguage))" -ForegroundColor Cyan
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
            throw "当前 POE1 DAT 已包含价格标记，但没有兼容的干净还原底板。请先通过游戏平台校验/修复游戏，再重新运行更新。"
        }
        $LogicalRestoreZip = New-Poe1LogicalRestoreZip -BaseItems $Extracted.LocalizedBaseItems `
            -Words $Extracted.LocalizedWords -OutputZip $LogicalRestoreOut -InstallInfo $InstallInfo -RepoRoot $RepoRoot
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
    if ($InstallInfo.Mode -eq "Bundles2" -and -not $NoInstall) {
        foreach ($Candidate in @($PersistentPhysicalRestore, $PhysicalRestoreOut)) {
            try {
                if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                    Assert-Poe1PhysicalRestoreZip -ZipPath $Candidate -InstallInfo $InstallInfo `
                        -CurrentBaseItems $Extracted.LocalizedBaseItems -RepoRoot $RepoRoot | Out-Null
                    $PhysicalRestoreZip = (Resolve-Path -LiteralPath $Candidate).Path
                    break
                }
            }
            catch {
                Write-Warning "忽略不可用的 POE1 真实还原包：$($_.Exception.Message)"
            }
        }
        if ([string]::IsNullOrWhiteSpace($PhysicalRestoreZip)) {
            if ($CurrentBasePatched -or $CurrentWordsPatched) {
                throw "当前 POE1 已打过补丁，但缺少兼容的真实还原包。请先校验/修复游戏后重试。"
            }
            Write-Host "正在备份 Bundles2 索引与 LibGGPK3；首次运行可能需要一些时间..." -ForegroundColor Yellow
            $PhysicalRestoreZip = New-Poe1PhysicalRestoreZip -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
                -CurrentBaseItems $Extracted.LocalizedBaseItems -OutputZip $PhysicalRestoreOut -RepoRoot $RepoRoot
            Copy-Poe2FileAtomically -Source $PhysicalRestoreZip -Destination $PersistentPhysicalRestore | Out-Null
            $PhysicalRestoreZip = $PersistentPhysicalRestore
        }
    }

    Write-Poe1Step "获取实时 POE1 价格并生成 C/D 补丁"
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $CacheKey = [string]::Join("_", @(
            ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_'),
            ([string]$InstallInfo.ConfigLanguage -replace '[^A-Za-z0-9_-]+', '_'),
            $PatchScope,
            $PriceSource
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
            -Scope $PatchScope -Source $PriceSource -Python $Python) {
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
    try {
        Invoke-Poe1PatchWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $PatchZip `
            -RepoRoot $RepoRoot -Dotnet $Dotnet
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
                Invoke-Poe1PatchWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $LogicalRestoreZip `
                    -RepoRoot $RepoRoot -Dotnet $Dotnet
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
