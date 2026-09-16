param([Parameter(Mandatory = $true)][string]$RequestPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProgressPreference = 'SilentlyContinue'
$HeldMutex = $null
try {
    $Request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $Root = $PSScriptRoot
    $Tools = Join-Path $Root 'tools'
    $env:POE2_PATCH_ROOT = $Root
    $env:POE2_PATCH_RELEASE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    . (Join-Path $Tools 'poe2_patch_common.ps1')
    . (Join-Path $Tools 'poe_patch_profiles.ps1')
    function Client($Candidate) {
        return [pscustomobject]@{
            gameVersion = $Candidate.GameVersion; path = $Candidate.Path
            displayName = $Candidate.InstallInfo.DisplayName; installKind = $Candidate.InstallInfo.InstallKind
            isChina = [bool]$Candidate.InstallInfo.IsChina; language = $Candidate.InstallInfo.LanguageName
        }
    }
    switch ($Request.action) {
        'discover' {
            $Result = @(Get-PoePatchGameDirectoryCandidates -GameVersion $Request.gameVersion -PreferredRoot $Request.preferredRoot | ForEach-Object { Client $_ })
        }
        'inspect' {
            $Result = Client (Resolve-PoePatchManualSelection -RequestedGameVersion $Request.gameVersion -Path $Request.directory -Poe1LanguageMode $Request.language)
        }
        'leagues' {
            $Result = @(Get-PoePatchLeagueOptions -GameVersion $Request.gameVersion -China:([bool]$Request.china) -TimeoutSeconds 10)
        }
        'run' {
            $r = $Request.request
            $Candidate = Resolve-PoePatchManualSelection -RequestedGameVersion $r.gameVersion -Path $r.gameDirectory -Poe1LanguageMode $r.languageMode
            if ($Request.expectedKind -and $Request.expectedKind -ne $Candidate.InstallInfo.InstallKind) { throw '客户端类型已变化，请重新手动更新。' }
            if ($r.operation -eq 'localize' -and $Candidate.InstallInfo.IsChina) { throw '汉化仅支持 POE1 国际服。' }
            $Names = @('PathOfExile','PathOfExile_x64','PathOfExileSteam','PathOfExile_x64Steam','PathOfExile2','PathOfExile2Steam','PathOfExile2_x64','PathOfExile2_x64Steam')
            $GameRoot = [IO.Path]::GetFullPath($Candidate.Path).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
            $Running = @(Get-Process -Name $Names -ErrorAction SilentlyContinue | Where-Object {
                try { return [string]::IsNullOrWhiteSpace($_.Path) -or [IO.Path]::GetFullPath($_.Path).StartsWith($GameRoot, [StringComparison]::OrdinalIgnoreCase) } catch { return $true }
            })
            if ($Running.Count -gt 0) {
                if ($Request.automatic) { Write-Output '当前游戏正在运行，已跳过本轮自动更新。'; exit 2 }
                throw '检测到当前游戏正在运行，请关闭游戏后再执行。'
            }
            $Arguments = @{}
            foreach ($Property in $Request.arguments.PSObject.Properties) { $Arguments[$Property.Name] = $Property.Value }
            if ($Request.automatic -and $r.operation -eq 'update') {
                try { $HeldMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Candidate.Path }
                catch { Write-Output '同一游戏目录已有更新任务，已跳过本轮自动更新。'; exit 2 }
                $Arguments.SkipGameDirectoryMutex = $true
            }
            $AllowedScripts = @('update_price_patch.ps1','update_poe1_price_patch.ps1','restore_price_patch.ps1','restore_poe1_price_patch.ps1','localize_poe1.ps1')
            if ($Request.script -notin $AllowedScripts) { throw '无效脚本。' }
            if ($r.gameVersion -eq 'poe1' -and -not $Candidate.InstallInfo.IsChina -and
                $r.languageMode -eq 'zh-CN' -and $r.operation -in @('update', 'restore')) {
                . (Join-Path $Tools 'poe1_patch_common.ps1')
                $Probe = Join-Path ([IO.Path]::GetTempPath()) ('poe-language-' + [Guid]::NewGuid().ToString('N'))
                try {
                    Write-Output '正在检查客户端中文资源…'
                    $Info = $Candidate.InstallInfo
                    $ChinesePaths = @($Info.TcBaseItemsPath, $Info.TcWordsPath)
                    $Extracted = Invoke-Poe1ExtractBatch -Mode $Info.Mode -Poe1Dir $Candidate.Path `
                        -Extractor (Resolve-Poe1BundleExtractor -RepoRoot $Root) `
                        -Paths @($Info.EnBaseItemsPath, $Info.TcBaseItemsPath, $Info.TcWordsPath) `
                        -OptionalPaths $ChinesePaths -DestinationDirectory $Probe -Attempts 1 6>$null
                    if (-not $Extracted.ContainsKey($Info.TcBaseItemsPath) -or -not $Extracted.ContainsKey($Info.TcWordsPath)) {
                        Write-Output '此客户端没有简体中文资源，将使用项目现有汉化（繁体中文）。'
                        if ($r.operation -eq 'update') {
                            $global:LASTEXITCODE = 0
                            & (Join-Path $Tools 'localize_poe1.ps1') -Poe1Dir $Candidate.Path
                            if ($LASTEXITCODE -ne 0) { throw '汉化未完成，本次物价更新已停止。' }
                        }
                        $Arguments.Poe1LanguageMode = 'localization'
                        Write-Output '__POE_LANGUAGE_MODE__localization'
                    }
                } finally {
                    if (Test-Path -LiteralPath $Probe) { Remove-Item -LiteralPath $Probe -Recurse -Force }
                }
            }
            $global:LASTEXITCODE = 0
            & (Join-Path $Tools $Request.script) @Arguments
            exit $LASTEXITCODE
        }
        default { throw '无效后台动作。' }
    }
    Write-Output ('__POE_RESULT__' + (ConvertTo-Json -InputObject $Result -Depth 10 -Compress))
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($null -ne $HeldMutex) {
        try { $HeldMutex.ReleaseMutex() } catch { }
        $HeldMutex.Dispose()
    }
}
