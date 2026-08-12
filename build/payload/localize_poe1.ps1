param(
    [string]$Poe1Dir = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot "poe1_patch_common.ps1")

$CodeToolsRoot = $PSScriptRoot
$RepoRoot = if ([string]::IsNullOrWhiteSpace($env:POE2_PATCH_ROOT)) {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    (Resolve-Path -LiteralPath $env:POE2_PATCH_ROOT).Path
}
$script:PatchVersion = "v0.5.7"
$script:GameDirectoryMutex = $null
$script:LocalizationAssetName = "PoeChinese3_win-x64.exe"
$script:LatestReleaseUrl = "https://github.com/aianlinb/LibGGPK3/releases/latest"
# 国内加速源始终优先；GitHub 官方源只作为兜底。元数据和程序本体都按
# 此顺序获取，且程序本体必须匹配 Release 页面公布的 SHA256 才会执行。
$script:LocalizationSourcePrefixes = @(
    [pscustomobject]@{
        Name = "国内加速源 ghfast.top"
        Prefix = "https://ghfast.top/"
    },
    [pscustomobject]@{
        Name = "国内加速源 gh-proxy.com"
        Prefix = "https://gh-proxy.com/"
    },
    [pscustomobject]@{
        Name = "GitHub 官方源"
        Prefix = ""
    }
)

function Resolve-Poe1LocalizationDirectory {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return (Resolve-PoePatchManualSelection -RequestedGameVersion poe1 -Path $Requested `
            -Poe1LanguageMode localization).Path
    }
    $Candidates = @(Get-Poe1GameDirectoryCandidates -PreferredRoot (Split-Path -Parent $RepoRoot))
    if ($Candidates.Count -eq 1) {
        return [string]$Candidates[0].Path
    }
    if ($Candidates.Count -eq 0) {
        throw "没有找到 POE1 客户端，请从统一界面手动选择游戏目录。"
    }
    throw "检测到多个 POE1 客户端，请选择 POE1 国际服后再点击汉化。"
}

function Test-Poe1LocalizationExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256
    )

    Assert-Poe1File -Path $Path -Name "PoeChinese3_win-x64.exe"
    $File = Get-Item -LiteralPath $Path
    if ($File.Length -lt 1048576 -or $File.Length -gt 104857600) {
        throw "最新版 PoeChinese3 文件大小异常：$($File.Length) bytes"
    }
    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Header = New-Object byte[] 2
        [void]$Stream.Read($Header, 0, 2)
    }
    finally {
        $Stream.Dispose()
    }
    if ($Header[0] -ne 0x4D -or $Header[1] -ne 0x5A) {
        throw "下载的 PoeChinese3 不是有效的 Windows 可执行文件。"
    }
    $ActualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $ActualSha256.Equals($ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "PoeChinese3 SHA256 与最新版 Release 公布值不一致：期望 $ExpectedSha256，实际 $ActualSha256"
    }
    $VersionInfo = $File.VersionInfo
    $Identity = "$( [string]$VersionInfo.ProductName ) $( [string]$VersionInfo.CompanyName ) $( [string]$VersionInfo.OriginalFilename )"
    if ($Identity -notmatch "(?i)PoeChinese3|LibGGPK3") {
        throw "下载文件不是 PoeChinese3：$Identity"
    }
    $Version = [string]$VersionInfo.FileVersion
    if ([string]::IsNullOrWhiteSpace($Version)) {
        $Version = [string]$VersionInfo.ProductVersion
    }
    if ($Version -notmatch '^\d+\.\d+') {
        throw "无法读取 PoeChinese3 版本号。"
    }
    return [pscustomobject]@{
        Version = $Version
        Sha256 = $ActualSha256
    }
}

function Get-Poe1LatestLocalizationRelease {
    $Errors = New-Object System.Collections.Generic.List[string]
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }
    foreach ($Source in $script:LocalizationSourcePrefixes) {
        try {
            $LatestUrl = "$($Source.Prefix)$($script:LatestReleaseUrl)"
            Write-Host "正在从 $($Source.Name) 查询 PoeChinese3 最新 Release..." -ForegroundColor Cyan
            $Page = Invoke-WebRequest -Uri $LatestUrl -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 60 `
                -Headers @{ "User-Agent" = "poe2-price-patch/$script:PatchVersion" }
            $FinalUrl = [string]$Page.BaseResponse.ResponseUri.AbsoluteUri
            $TagMatch = [regex]::Match($FinalUrl, '/releases/tag/(?<tag>[^/?#]+)', 'IgnoreCase')
            if (-not $TagMatch.Success) {
                $TagMatch = [regex]::Match([string]$Page.Content, '/releases/tag/(?<tag>[^"/?#]+)', 'IgnoreCase')
            }
            if (-not $TagMatch.Success) {
                throw "最新版页面未返回 Release 标签。"
            }
            $Tag = [Uri]::UnescapeDataString($TagMatch.Groups['tag'].Value)
            if ($Tag -notmatch '^v?\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?$') {
                throw "最新版 Release 标签格式异常：$Tag"
            }
            $ExpandedOfficialUrl = "https://github.com/aianlinb/LibGGPK3/releases/expanded_assets/$([Uri]::EscapeDataString($Tag))"
            $ExpandedUrl = "$($Source.Prefix)$ExpandedOfficialUrl"
            $AssetsPage = Invoke-WebRequest -Uri $ExpandedUrl -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 60 `
                -Headers @{ "User-Agent" = "poe2-price-patch/$script:PatchVersion" }
            $AssetNamePattern = [regex]::Escape($script:LocalizationAssetName)
            $AssetMatch = [regex]::Match(
                [string]$AssetsPage.Content,
                "(?is)href=`"(?<url>[^`"]*$AssetNamePattern)`".*?sha256:(?<hash>[0-9a-f]{64})"
            )
            if (-not $AssetMatch.Success) {
                throw "最新版 Release 未公布 $($script:LocalizationAssetName) 或 SHA256。"
            }
            $RelativeUrl = [System.Net.WebUtility]::HtmlDecode($AssetMatch.Groups['url'].Value)
            if ($RelativeUrl -notmatch '^/aianlinb/LibGGPK3/releases/download/[^/]+/PoeChinese3_win-x64\.exe$') {
                throw "最新版 Release 资源地址异常：$RelativeUrl"
            }
            $OfficialAssetUrl = "https://github.com$RelativeUrl"
            return [pscustomobject]@{
                Tag = $Tag
                Url = $OfficialAssetUrl
                Sha256 = $AssetMatch.Groups['hash'].Value.ToLowerInvariant()
                MetadataSourceName = $Source.Name
            }
        }
        catch {
            $Message = "$($Source.Name) 查询失败：$($_.Exception.Message)"
            [void]$Errors.Add($Message)
            Write-Warning $Message
        }
    }
    throw "无法确认 PoeChinese3 最新 Release：$([string]::Join(' | ', $Errors))"
}

function Get-Poe1LatestLocalizationTool {
    param([Parameter(Mandatory = $true)][string]$DestinationDirectory)

    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $Release = Get-Poe1LatestLocalizationRelease
    Write-Host "已确认最新版本：$($Release.Tag)（元数据：$($Release.MetadataSourceName)）" -ForegroundColor Cyan
    Write-Host "官方 SHA256：$($Release.Sha256)" -ForegroundColor DarkGray
    $Destination = Join-Path $DestinationDirectory $script:LocalizationAssetName
    $Errors = New-Object System.Collections.Generic.List[string]
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }
    foreach ($Source in $script:LocalizationSourcePrefixes) {
        $DownloadUrl = "$($Source.Prefix)$($Release.Url)"
        for ($Attempt = 1; $Attempt -le 2; $Attempt += 1) {
            $Temp = Join-Path $DestinationDirectory ([string]::Concat("PoeChinese3-", [Guid]::NewGuid().ToString("N"), ".download"))
            try {
                Write-Host "正在从 $($Source.Name) 获取 PoeChinese3 最新版本（第 $Attempt 次尝试）..." -ForegroundColor Cyan
                Invoke-WebRequest -Uri $DownloadUrl -OutFile $Temp -UseBasicParsing `
                    -Headers @{ "User-Agent" = "poe2-price-patch/$script:PatchVersion" } `
                    -MaximumRedirection 5 -TimeoutSec 180
                $Info = Test-Poe1LocalizationExecutable -Path $Temp -ExpectedSha256 $Release.Sha256
                Move-Poe2FileAtomically -Source $Temp -Destination $Destination | Out-Null
                return [pscustomobject]@{
                    Path = $Destination
                    Version = $Info.Version
                    ReleaseTag = $Release.Tag
                    Sha256 = $Info.Sha256
                    Url = $DownloadUrl
                    SourceName = $Source.Name
                }
            }
            catch {
                $Message = "$($Source.Name) 第 $Attempt 次尝试失败：$($_.Exception.Message)"
                [void]$Errors.Add($Message)
                if ($Attempt -lt 2) {
                    Write-Warning "$Message，将重试。"
                    Start-Sleep -Seconds 2
                }
                else {
                    Write-Warning $Message
                }
            }
            finally {
                if (Test-Path -LiteralPath $Temp -PathType Leaf) {
                    Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
    throw "PoeChinese3 最新版本下载失败：$([string]::Join(' | ', $Errors))"
}

function Invoke-Poe1LocalizationTool {
    param(
        [Parameter(Mandatory = $true)][string]$ToolPath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $ToolPath
    $StartInfo.Arguments = '"' + $TargetPath.Replace('"', '\"') + '"'
    $StartInfo.WorkingDirectory = Split-Path -Parent $ToolPath
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardInput = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    try { $StartInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
    try { $StartInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8 } catch { }

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    try {
        if (-not $Process.Start()) {
            throw "无法启动 PoeChinese3。"
        }
        $OutputTask = $Process.StandardOutput.ReadToEndAsync()
        $ErrorTask = $Process.StandardError.ReadToEndAsync()
        # With a command-line path PoeChinese3 only waits for this final Enter
        # after it has finished writing the index.  Supplying it up front keeps
        # the bundled tool fully non-interactive without relying on a timeout.
        $Process.StandardInput.WriteLine()
        $Process.StandardInput.Close()
        if (-not $Process.WaitForExit(900000)) {
            try { $Process.Kill() } catch { }
            throw "PoeChinese3 运行超过 15 分钟，已终止。"
        }
        $Process.WaitForExit()
        $Output = $OutputTask.GetAwaiter().GetResult()
        $ErrorOutput = $ErrorTask.GetAwaiter().GetResult()
        $Text = (($Output, $ErrorOutput) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n"
        foreach ($Line in ($Text -split "`r?`n")) {
            if (-not [string]::IsNullOrWhiteSpace($Line)) { Write-Host $Line }
        }
        if ($Process.ExitCode -ne 0) {
            throw "PoeChinese3 退出码异常：$($Process.ExitCode)。$Text"
        }
        if ($Text -notmatch '(?m)Done!') {
            throw "PoeChinese3 未报告完成。$Text"
        }
        if ($Text -notmatch '中文化完成') {
            throw "PoeChinese3 未报告中文化完成。$Text"
        }
        return [pscustomobject]@{ ExitCode = $Process.ExitCode; Text = $Text }
    }
    finally {
        $Process.Dispose()
    }
}

function Set-Poe1LocalizationConfigLanguage {
    $ConfigDirectory = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Path of Exile"
    if (-not (Test-Path -LiteralPath $ConfigDirectory -PathType Container)) {
        return [pscustomobject]@{ Path = ""; Changed = $false }
    }
    $Config = @(Get-ChildItem -LiteralPath $ConfigDirectory -File -Filter "production*_Config.ini" `
        -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq "production_Config.ini" } |
        Select-Object -First 1)
    if ($Config.Count -eq 0) {
        $Config = @(Get-ChildItem -LiteralPath $ConfigDirectory -File -Filter "production*_Config.ini" `
            -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1)
    }
    if ($Config.Count -eq 0) {
        return [pscustomobject]@{ Path = ""; Changed = $false }
    }
    $Path = $Config[0].FullName
    $Original = [System.IO.File]::ReadAllText($Path)
    $NewLine = if ($Original.Contains("`r`n")) { "`r`n" } else { "`n" }
    $HadTrailingNewLine = $Original.EndsWith("`r`n") -or $Original.EndsWith("`n") -or $Original.EndsWith("`r")
    $Lines = New-Object System.Collections.Generic.List[string]
    foreach ($Line in ([System.Text.RegularExpressions.Regex]::Split($Original, "`r`n|`n|`r"))) {
        [void]$Lines.Add($Line)
    }
    $InLanguage = $false
    $SectionFound = $false
    $LanguageFound = $false
    $Changed = $false
    for ($Index = 0; $Index -lt $Lines.Count; $Index += 1) {
        $Line = [string]$Lines[$Index]
        if ($Line -match '^\s*\[(?<section>[^\]]+)\]\s*$') {
            if ($InLanguage -and -not $LanguageFound) {
                $Lines.Insert($Index, "language=fr")
                $Index += 1
                $LanguageFound = $true
                $Changed = $true
            }
            $InLanguage = $Matches.section -ieq "LANGUAGE"
            if ($InLanguage) { $SectionFound = $true }
            continue
        }
        if ($InLanguage -and $Line -match '^(?<prefix>\s*language\s*=\s*).*$') {
            $Replacement = $Matches.prefix + "fr"
            if ($Line -cne $Replacement) {
                $Lines[$Index] = $Replacement
                $Changed = $true
            }
            $LanguageFound = $true
        }
    }
    if ($InLanguage -and -not $LanguageFound) {
        [void]$Lines.Add("language=fr")
        $LanguageFound = $true
        $Changed = $true
    }
    if (-not $SectionFound) {
        if ($Lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($Lines[$Lines.Count - 1])) {
            [void]$Lines.Add("")
        }
        [void]$Lines.Add("[LANGUAGE]")
        [void]$Lines.Add("language=fr")
        $Changed = $true
    }
    if ($Changed) {
        $NewText = [string]::Join($NewLine, $Lines)
        if ($HadTrailingNewLine -and -not $NewText.EndsWith($NewLine)) { $NewText += $NewLine }
        $Temp = Join-Path (Split-Path -Parent $Path) ([string]::Concat(".", (Split-Path -Leaf $Path), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
        try {
            [System.IO.File]::WriteAllText($Temp, $NewText, (New-Object System.Text.UTF8Encoding($false)))
            Move-Poe2FileAtomically -Source $Temp -Destination $Path | Out-Null
        }
        finally {
            if (Test-Path -LiteralPath $Temp -PathType Leaf) {
                Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
            }
        }
    }
    return [pscustomobject]@{ Path = $Path; Changed = $Changed }
}

try {
    $Poe1Dir = Resolve-Poe1LocalizationDirectory -Requested $Poe1Dir
    $script:GameDirectoryMutex = Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe1Dir
    $InstallInfo = Get-Poe1InstallInfo -GameDirectory $Poe1Dir -LanguageMode localization
    if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "POE1-CN-*") {
        throw "一键汉化仅支持 POE1 国际服，当前目录识别为国服。"
    }
    Save-PoePatchGameDirectory -GameVersion poe1 -GameDirectory $Poe1Dir | Out-Null
    Save-Poe1LanguageMode -LanguageMode localization | Out-Null
    $Target = if ($InstallInfo.Mode -eq "Bundles2") {
        Join-Path $Poe1Dir "Bundles2\_.index.bin"
    }
    else {
        Join-Path $Poe1Dir "Content.ggpk"
    }
    Assert-Poe1File -Path $Target -Name "POE1 国际服游戏包"

    Write-Poe1Step "检查 POE1 游戏包是否可写"
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe1Dir -IndexPath $Target
    Write-Host "目标：$Target" -ForegroundColor Cyan
    Write-Host "汉化方式：PoeChinese3 最新 Release（繁体中文，法语入口）" -ForegroundColor Cyan

    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ([string]::Concat("poe1-localization-", [Guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    try {
        $Tool = Get-Poe1LatestLocalizationTool -DestinationDirectory $TempRoot
        Write-Poe1Step "使用 PoeChinese3 $($Tool.Version) 汉化 POE1 国际服"
        Write-Host "下载来源：$($Tool.SourceName)" -ForegroundColor DarkGray
        Write-Host "工具 SHA256：$($Tool.Sha256)" -ForegroundColor DarkGray
        $BeforeHash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
        Invoke-Poe1LocalizationTool -ToolPath $Tool.Path -TargetPath $Target | Out-Null
        $AfterHash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
        $Config = Set-Poe1LocalizationConfigLanguage
        if ([string]::IsNullOrWhiteSpace($Config.Path)) {
            Write-Warning "未找到 POE1 production*_Config.ini，请进入游戏后选择第二个（法文）国旗。"
        }
        else {
            Write-Host "已将 POE1 语言配置设为 fr：$($Config.Path)" -ForegroundColor Green
        }
        Write-Host "POE1 中文化完成（工具版本 $($Tool.Version)）。" -ForegroundColor Green
        if ($BeforeHash -eq $AfterHash) {
            Write-Host "当前客户端已经是中文化状态，本次仍使用了刚下载的最新工具。" -ForegroundColor Yellow
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
catch {
    Write-Host ""
    Write-Host "POE1 一键汉化失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if ($null -ne $script:GameDirectoryMutex) {
        try { $script:GameDirectoryMutex.ReleaseMutex() } catch { }
        $script:GameDirectoryMutex.Dispose()
    }
}
