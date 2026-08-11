param(
    [string]$Poe1Dir = "",
    [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
    [string]$Poe1LanguageMode = "auto",
    [string]$RestoreZip = "",
    [string]$PhysicalRestoreZip = "",
    [switch]$NoInstall,
    [switch]$SkipGameDirectoryMutex
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot "poe1_patch_common.ps1")

if ([string]::IsNullOrWhiteSpace($env:POE2_PATCH_ROOT)) {
    $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path -LiteralPath $env:POE2_PATCH_ROOT).Path
}
Set-Location -LiteralPath $RepoRoot
$script:PatchVersion = "v0.5.4"
$script:GameDirectoryMutex = $null
$ValidationDir = ""

function Resolve-Poe1RestoreDirectory {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return (Resolve-PoePatchManualSelection -RequestedGameVersion poe1 -Path $Requested).Path
    }
    $Candidates = @(Get-Poe1GameDirectoryCandidates -PreferredRoot (Split-Path -Parent $RepoRoot))
    if ($Candidates.Count -eq 1) { return [string]$Candidates[0].Path }
    if ($Candidates.Count -eq 0) {
        throw "没有找到 POE1 客户端，请从统一还原界面手动选择游戏目录。"
    }
    throw "检测到多个 POE1 客户端，请从统一还原界面选择本次要还原的客户端。"
}

try {
    $Poe1Dir = Resolve-Poe1RestoreDirectory -Requested $Poe1Dir
    if (-not $SkipGameDirectoryMutex) {
        $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe1Dir
    }
    try {
        Save-PoePatchGameDirectory -GameVersion poe1 -GameDirectory $Poe1Dir | Out-Null
        Save-Poe1LanguageMode -LanguageMode $Poe1LanguageMode | Out-Null
    }
    catch {
        Write-Warning "无法保存最近使用的 POE1 目录，本次还原仍会继续：$($_.Exception.Message)"
    }

    $InstallInfo = Get-Poe1InstallInfo -GameDirectory $Poe1Dir -LanguageMode $Poe1LanguageMode
    $OutputKey = Get-Poe1PatchOutputKey -Poe1Dir $Poe1Dir
    $ClientOutputRoot = Join-Path $RepoRoot ("output\poe1\" + $OutputKey)
    $RestoreDir = Join-Path $ClientOutputRoot "restore"
    $PersistentDir = Join-Path $Poe1Dir ".poe1-price-patch"
    $LogicalRestoreName = Get-Poe1LogicalRestoreZipName -InstallInfo $InstallInfo
    $PhysicalRestoreName = Get-Poe1PhysicalRestoreZipName -InstallInfo $InstallInfo
    $PhysicalRestoreNames = @(Get-Poe1PhysicalRestoreZipCandidateNames -InstallInfo $InstallInfo)
    $ValidationDir = Join-Path $ClientOutputRoot ([string]::Concat(".restore-validation-", [Guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Force -Path $ValidationDir | Out-Null

    Write-Host "POE1 物价补丁还原器 $script:PatchVersion" -ForegroundColor Green
    Write-Host "游戏目录：$Poe1Dir"
    Write-Host "客户端  ：$($InstallInfo.DisplayName)" -ForegroundColor Cyan
    Write-Host "安装模式：$($InstallInfo.Mode)" -ForegroundColor Cyan
    Write-Host "还原语言：$(Get-Poe1DisplayLanguageName -Name $InstallInfo.LanguageName) ($($InstallInfo.EffectiveLanguageCode))" -ForegroundColor Cyan
    Write-Host "语言模式：$($InstallInfo.LanguageMode)；$($InstallInfo.LanguageSelectionReason)" -ForegroundColor Cyan

    Write-Poe1Step "读取当前 POE1 DAT 并验证还原包兼容性"
    $Current = Invoke-Poe1ExtractDatFiles -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
        -RepoRoot $RepoRoot -DestinationDirectory $ValidationDir
    Assert-Poe1File -Path $Current.LocalizedBaseItems -Name "当前 BaseItemTypes.datc64"
    Assert-Poe1File -Path $Current.LocalizedWords -Name "当前 Words.datc64"

    $SelectedPhysical = ""
    if ($InstallInfo.Mode -eq "Bundles2") {
        $PhysicalCandidates = if (-not [string]::IsNullOrWhiteSpace($PhysicalRestoreZip)) {
            @($PhysicalRestoreZip)
        }
        else {
            @($PhysicalRestoreNames | ForEach-Object {
                    Join-Path $PersistentDir $_
                    Join-Path $RestoreDir $_
                    Join-Path $RepoRoot $_
                })
        }
        foreach ($Candidate in $PhysicalCandidates) {
            if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
            try {
                Assert-Poe1PhysicalRestoreZip -ZipPath $Candidate -InstallInfo $InstallInfo `
                    -CurrentBaseItems $Current.LocalizedBaseItems -RepoRoot $RepoRoot | Out-Null
                $SelectedPhysical = (Resolve-Path -LiteralPath $Candidate).Path
                break
            }
            catch {
                if (-not [string]::IsNullOrWhiteSpace($PhysicalRestoreZip)) { throw }
                Write-Warning "忽略不可用的 POE1 真实还原包：$($_.Exception.Message)"
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($SelectedPhysical)) {
        Write-Host "已验证真实还原包：$SelectedPhysical" -ForegroundColor Green
        if ($NoInstall) {
            Write-Host "NoInstall 已启用：真实还原包验证通过，未修改任何 POE1 游戏文件。" -ForegroundColor Yellow
            return
        }
        Write-Poe1Step "恢复 Bundles2 写入前的真实文件"
        Restore-Poe1PhysicalBundles2 -Poe1Dir $Poe1Dir -ZipPath $SelectedPhysical `
            -InstallInfo $InstallInfo -CurrentBaseItems $Current.LocalizedBaseItems -RepoRoot $RepoRoot

        $VerifyDir = Join-Path $ValidationDir "after-physical-restore"
        $Verified = Invoke-Poe1ExtractDatFiles -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
            -RepoRoot $RepoRoot -DestinationDirectory $VerifyDir
        if (Test-Poe1BaseItemsLookPatched -SourceDat $Verified.LocalizedBaseItems -RepoRoot $RepoRoot) {
            throw "真实还原完成后 BaseItemTypes 仍包含价格标记。"
        }
        if (Test-Poe1WordsLookPatched -SourceWords $Verified.LocalizedWords -RepoRoot $RepoRoot) {
            throw "真实还原完成后 Words 仍包含价格标记。"
        }
        Write-Host "POE1 Bundles2 已恢复到写入前状态并通过读回校验。" -ForegroundColor Green
        return
    }

    $LogicalCandidates = if (-not [string]::IsNullOrWhiteSpace($RestoreZip)) {
        @($RestoreZip)
    }
    else {
        @(
            (Join-Path $PersistentDir $LogicalRestoreName),
            (Join-Path $RestoreDir $LogicalRestoreName),
            (Join-Path $RepoRoot $LogicalRestoreName)
        )
    }
    $SelectedLogical = ""
    foreach ($Candidate in $LogicalCandidates) {
        if (Test-Poe1LogicalRestoreZip -ZipPath $Candidate -InstallInfo $InstallInfo `
            -CurrentBaseItems $Current.LocalizedBaseItems -RepoRoot $RepoRoot) {
            $SelectedLogical = (Resolve-Path -LiteralPath $Candidate).Path
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($SelectedLogical)) {
        if (-not [string]::IsNullOrWhiteSpace($RestoreZip)) {
            throw "指定的 POE1 逻辑还原包不可用：$RestoreZip"
        }
        throw "找不到与当前 POE1 客户端兼容的还原包。请先在干净游戏状态运行一次更新，或通过游戏平台校验/修复游戏。"
    }
    Write-Host "已验证逻辑还原包：$SelectedLogical" -ForegroundColor Green
    if ($NoInstall) {
        Write-Host "NoInstall 已启用：逻辑还原包验证通过，未修改任何 POE1 游戏文件。" -ForegroundColor Yellow
        return
    }

    Write-Poe1Step "写入干净 POE1 DAT 并读回校验"
    $Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
    Invoke-Poe1LogicalRestoreWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo `
        -LogicalRestoreZip $SelectedLogical -RepoRoot $RepoRoot -Dotnet $Dotnet
    Write-Host "POE1 物价补丁已还原并通过读回校验。" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "POE1 还原失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (-not [string]::IsNullOrWhiteSpace([string]$ValidationDir) -and
        (Test-Path -LiteralPath $ValidationDir -PathType Container)) {
        Remove-Item -LiteralPath $ValidationDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $script:GameDirectoryMutex) {
        try { $script:GameDirectoryMutex.ReleaseMutex() } catch { }
        $script:GameDirectoryMutex.Dispose()
    }
}
