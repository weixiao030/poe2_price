function Get-Poe2PatchName {
    param([Parameter(Mandatory = $true)][string]$Name)

    switch ($Name) {
        "InstallerDir" {
            return [string]::Concat(
                [char]0x4E00, [char]0x952E, [char]0x5B89, [char]0x88C5,
                [char]0x7279, [char]0x6B8A, [char]0x8865, [char]0x4E01,
                [char]0x5DE5, [char]0x5177
            )
        }
        "InstallerExe" {
            return [string]::Concat((Get-Poe2PatchName "InstallerDir"), ".exe")
        }
        "LegacyPatchZip" {
            return [string]::Concat([char]0x8865, [char]0x4E01, ".zip")
        }
        "PricePatchZip" {
            return [string]::Concat([char]0x7269, [char]0x4EF7, [char]0x8865, [char]0x4E01, ".zip")
        }
        "RestorePatchZip" {
            return [string]::Concat(
                [char]0x8FD8, [char]0x539F, [char]0x7269, [char]0x4EF7,
                [char]0x8865, [char]0x4E01, ".zip"
            )
        }
        "ChinaRestorePatchZip" {
            return [string]::Concat(
                [char]0x56FD, [char]0x670D, [char]0x8FD8, [char]0x539F,
                [char]0x5305, ".zip"
            )
        }
        "IntlRestorePatchZip" {
            return [string]::Concat(
                [char]0x56FD, [char]0x9645, [char]0x670D, [char]0x8FD8,
                [char]0x539F, [char]0x8865, [char]0x4E01, ".zip"
            )
        }
        "PhysicalRestorePatchZip" {
            return [string]::Concat(
                [char]0x771F, [char]0x5B9E, [char]0x8FD8, [char]0x539F,
                [char]0x7269, [char]0x4EF7, [char]0x8865, [char]0x4E01,
                ".zip"
            )
        }
        default {
            throw "Unknown patch name: $Name"
        }
    }
}

function Get-GgpkExtractorFailureSuggestions {
    return @(
        "请确认工具目录里的 vcruntime140.dll 没有被杀毒软件误删。",
        "如果系统还没安装 Microsoft Visual C++ 2015-2022 x64 运行库，请先安装或修复后再重试。",
        "如果仍然失败，把下方日志路径里的内容一起发给作者排查。"
    )
}

function Test-GgpkExtractorMissingRuntimeDependency {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    return ($Text -match 'DllNotFoundException|oo2core|VCRUNTIME140|api-ms-win-crt')
}

function Get-Poe2FixedRestorePatchZipName {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") {
        return Get-Poe2PatchName "ChinaRestorePatchZip"
    }

    return Get-Poe2PatchName "IntlRestorePatchZip"
}

function Get-Poe2RestorePatchZipCandidateNames {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    return Get-Poe2FixedRestorePatchZipName -InstallInfo $InstallInfo
}

function Get-Poe2FixedPhysicalRestorePatchZipName {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    return Get-Poe2PatchName "PhysicalRestorePatchZip"
}

function Get-Poe2NormalizedFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

function Test-Poe2PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $FullPath = Get-Poe2NormalizedFullPath $Path
    $FullRoot = Get-Poe2NormalizedFullPath $Root
    $RootPrefix = $FullRoot + [System.IO.Path]::DirectorySeparatorChar
    return ($FullPath -eq $FullRoot -or $FullPath.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase))
}

function Assert-Poe2PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$Message = "Refusing to access path outside expected folder"
    )

    $FullPath = Get-Poe2NormalizedFullPath $Path
    if (-not (Test-Poe2PathInside -Path $FullPath -Root $Root)) {
        throw "$Message`: $FullPath"
    }
    return $FullPath
}

function Get-Poe2GameMode {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $ContentGgpk = Join-Path $Poe2Dir "Content.ggpk"
    $Bundles2Index = Join-Path $Poe2Dir "Bundles2\_.index.bin"

    if (Test-Path -LiteralPath $ContentGgpk -PathType Leaf) {
        return "GGPK"
    }
    elseif (Test-Path -LiteralPath $Bundles2Index -PathType Leaf) {
        return "Bundles2"
    }
    else {
        throw "无法检测 POE2 游戏目录：请把物价补丁文件夹放在游戏根目录。找不到 Content.ggpk 或 Bundles2\_.index.bin"
    }
}

function Test-Poe2ChinaClient {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $Score = 0
    foreach ($Relative in @(
        "wegame.ini",
        "rail_api64.dll",
        "rail_files",
        "WeGameLauncher",
        "TCLS",
        "AntiCheatExpert",
        "QQOpenSDK.dll"
    )) {
        if (Test-Path -LiteralPath (Join-Path $Poe2Dir $Relative)) {
            $Score += 1
        }
    }

    if ((Get-ChildItem -LiteralPath $Poe2Dir -Filter "MSDK*.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        $Score += 1
    }

    return ($Score -ge 2)
}

function Get-Poe2LanguageInfoFromCode {
    param([string]$LanguageCode)

    $CodeText = ""
    if (-not [string]::IsNullOrWhiteSpace($LanguageCode)) {
        $CodeText = $LanguageCode.Trim()
    }
    $Code = $CodeText.ToLowerInvariant().Replace("_", "-")

    if ([string]::IsNullOrWhiteSpace($CodeText)) {
        return [pscustomobject]@{
            Code          = "en"
            Name          = "English"
            Path          = "data/balance/baseitemtypes.datc64"
            Defaulted     = $true
            DefaultReason = "未读取到 POE2 语言配置，已回退到 English。可通过 POE2_PATCH_LANGUAGE 手动指定语言。"
        }
    }

    if ($Code -in @("en", "en-us", "en-gb", "english")) {
        return [pscustomobject]@{
            Code = $(if ([string]::IsNullOrWhiteSpace($LanguageCode)) { "en" } else { $LanguageCode })
            Name = "English"
            Path = "data/balance/baseitemtypes.datc64"
        }
    }
    if ($Code -in @("zh-tw", "zh-hant", "traditional chinese", "traditional-chinese", "tc")) {
        return [pscustomobject]@{
            Code = $(if ([string]::IsNullOrWhiteSpace($LanguageCode)) { "zh-TW" } else { $LanguageCode })
            Name = "Traditional Chinese"
            Path = "data/balance/traditional chinese/baseitemtypes.datc64"
        }
    }
    if ($Code -in @("zh-cn", "zh-hans", "simplified chinese", "simplified-chinese", "sc")) {
        return [pscustomobject]@{
            Code = $(if ([string]::IsNullOrWhiteSpace($LanguageCode)) { "zh-CN" } else { $LanguageCode })
            Name = "Simplified Chinese"
            Path = "data/balance/simplified chinese/baseitemtypes.datc64"
        }
    }
    if ($Code -like "ja*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Japanese"
            Path = "data/balance/japanese/baseitemtypes.datc64"
        }
    }
    if ($Code -like "ko*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Korean"
            Path = "data/balance/korean/baseitemtypes.datc64"
        }
    }
    if ($Code -like "ru*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Russian"
            Path = "data/balance/russian/baseitemtypes.datc64"
        }
    }
    if ($Code -like "fr*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "French"
            Path = "data/balance/french/baseitemtypes.datc64"
        }
    }
    if ($Code -like "de*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "German"
            Path = "data/balance/german/baseitemtypes.datc64"
        }
    }
    if ($Code -like "es*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Spanish"
            Path = "data/balance/spanish/baseitemtypes.datc64"
        }
    }
    if ($Code -like "pt*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Portuguese"
            Path = "data/balance/portuguese/baseitemtypes.datc64"
        }
    }
    if ($Code -like "th*") {
        return [pscustomobject]@{
            Code = $LanguageCode
            Name = "Thai"
            Path = "data/balance/thai/baseitemtypes.datc64"
        }
    }

    return [pscustomobject]@{
        Code          = "en"
        Name          = "English"
        Path          = "data/balance/baseitemtypes.datc64"
        Defaulted     = $true
        DefaultReason = "无法识别 POE2 语言代码 '$CodeText'，已回退到 English。可通过 POE2_PATCH_LANGUAGE 手动指定语言。"
    }
}

function Get-Poe2ConfigLanguage {
    param([string]$Poe2Dir = "")

    if (-not [string]::IsNullOrWhiteSpace($env:POE2_PATCH_LANGUAGE)) {
        return $env:POE2_PATCH_LANGUAGE
    }

    $MyGames = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Path of Exile 2"
    if (-not (Test-Path -LiteralPath $MyGames -PathType Container)) {
        return $null
    }

    $ConfigFiles = Get-ChildItem -LiteralPath $MyGames -File -Filter "poe2_production*_Config.ini" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending

    foreach ($Config in $ConfigFiles) {
        $InLanguageSection = $false
        foreach ($Line in (Get-Content -LiteralPath $Config.FullName -Encoding UTF8 -ErrorAction SilentlyContinue)) {
            $Trimmed = $Line.Trim()
            if ($Trimmed -match '^\[(.+)\]$') {
                $InLanguageSection = ($Matches[1] -ieq "LANGUAGE")
                continue
            }
            if ($InLanguageSection -and $Trimmed -match '^language\s*=\s*(.+)$') {
                return $Matches[1].Trim()
            }
        }
    }

    return $null
}

function Get-Poe2WordsPathFromBaseItemsPath {
    param([Parameter(Mandatory = $true)][string]$BaseItemsPath)

    if ($BaseItemsPath -notmatch 'baseitemtypes\.datc64$') {
        throw "Cannot derive Words path from BaseItemTypes path: $BaseItemsPath"
    }

    return ($BaseItemsPath -replace 'baseitemtypes\.datc64$', 'words.datc64')
}

function Get-Poe2EndgameMapsPathFromBaseItemsPath {
    param([Parameter(Mandatory = $true)][string]$BaseItemsPath)

    if ($BaseItemsPath -notmatch 'baseitemtypes\.datc64$') {
        throw "Cannot derive EndgameMaps path from BaseItemTypes path: $BaseItemsPath"
    }

    return ($BaseItemsPath -replace 'baseitemtypes\.datc64$', 'endgamemaps.datc64')
}

function Get-Poe2KnownBaseItemsPaths {
    return @(
        "data/balance/baseitemtypes.datc64",
        "data/balance/traditional chinese/baseitemtypes.datc64",
        "data/balance/simplified chinese/baseitemtypes.datc64",
        "data/balance/japanese/baseitemtypes.datc64",
        "data/balance/korean/baseitemtypes.datc64",
        "data/balance/russian/baseitemtypes.datc64",
        "data/balance/french/baseitemtypes.datc64",
        "data/balance/german/baseitemtypes.datc64",
        "data/balance/spanish/baseitemtypes.datc64",
        "data/balance/portuguese/baseitemtypes.datc64",
        "data/balance/thai/baseitemtypes.datc64"
    )
}

function Get-Poe2KnownEndgameMapsPaths {
    return (Get-Poe2KnownBaseItemsPaths | ForEach-Object {
            Get-Poe2EndgameMapsPathFromBaseItemsPath -BaseItemsPath $_
        })
}

function Test-Poe2UniqueWordsSupported {
    param([Parameter(Mandatory = $true)][string]$WordsPath)

    return ($WordsPath -match '(^|/)words\.datc64$')
}

function Get-Poe2InstallInfo {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $Mode = Get-Poe2GameMode -Poe2Dir $Poe2Dir
    $IsChina = Test-Poe2ChinaClient -Poe2Dir $Poe2Dir
    $ConfigLanguage = Get-Poe2ConfigLanguage -Poe2Dir $Poe2Dir
    $LanguageInfo = Get-Poe2LanguageInfoFromCode -LanguageCode $ConfigLanguage
    $LanguagePath = $LanguageInfo.Path
    $LanguageName = $LanguageInfo.Name
    $LanguageDefaulted = [bool]$LanguageInfo.Defaulted
    $LanguageDefaultReason = [string]$LanguageInfo.DefaultReason
    $InstallKind = "Intl-Bundles2"
    $DisplayName = "国际服 Steam/Epic Bundles2"

    if ($Mode -eq "GGPK") {
        $InstallKind = "Intl-Standalone-GGPK"
        $DisplayName = "国际服官方 GGPK"
    }
    elseif ($IsChina) {
        $InstallKind = "CN-WeGame-Bundles2"
        $DisplayName = "国服 WeGame Bundles2"
        $LanguagePath = "data/balance/simplified chinese/baseitemtypes.datc64"
        $LanguageName = "Simplified Chinese"
        $ConfigLanguage = "zh-CN"
        $LanguageDefaulted = $false
        $LanguageDefaultReason = ""
    }

    return [pscustomobject]@{
        Mode             = $Mode
        InstallKind      = $InstallKind
        DisplayName      = $DisplayName
        IsChina          = $IsChina
        ConfigLanguage   = $(if ($LanguageDefaulted -or [string]::IsNullOrWhiteSpace($ConfigLanguage)) { $LanguageInfo.Code } else { $ConfigLanguage })
        EnBaseItemsPath  = "data/balance/baseitemtypes.datc64"
        TcBaseItemsPath  = $LanguagePath
        TcWordsPath      = (Get-Poe2WordsPathFromBaseItemsPath -BaseItemsPath $LanguagePath)
        TcEndgameMapsPath = (Get-Poe2EndgameMapsPathFromBaseItemsPath -BaseItemsPath $LanguagePath)
        LanguageName     = $LanguageName
        LanguageFileSlug = ($LanguagePath -replace '/', '_')
        WordsFileSlug    = ((Get-Poe2WordsPathFromBaseItemsPath -BaseItemsPath $LanguagePath) -replace '/', '_')
        EndgameMapsFileSlug = ((Get-Poe2EndgameMapsPathFromBaseItemsPath -BaseItemsPath $LanguagePath) -replace '/', '_')
        LanguageDefaulted = $LanguageDefaulted
        LanguageDefaultReason = $LanguageDefaultReason
    }
}

function Get-Bundles2Paths {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $Bundles2Dir = Join-Path $Poe2Dir "Bundles2"
    $IndexBin = Join-Path $Bundles2Dir "_.index.bin"

    return @{
        Bundles2Dir  = $Bundles2Dir
        IndexBin     = $IndexBin
        EnBaseItems  = "data/balance/baseitemtypes.datc64"
        TcBaseItems  = (Get-Poe2InstallInfo -Poe2Dir $Poe2Dir).TcBaseItemsPath
        TcEndgameMaps = (Get-Poe2InstallInfo -Poe2Dir $Poe2Dir).TcEndgameMapsPath
    }
}

function Test-Poe2ReleaseMode {
    return ($env:POE2_PATCH_RELEASE -eq "1")
}

function Test-DotNet8Runtime {
    param([string]$DotnetPath)

    if ([string]::IsNullOrWhiteSpace($DotnetPath)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $DotnetPath -PathType Leaf)) {
        return $false
    }

    function Test-DotNet8RuntimeDirectory {
        param([string]$RuntimeDir)

        if ([string]::IsNullOrWhiteSpace($RuntimeDir) -or -not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
            return $false
        }
        $RequiredFiles = @(
            "System.Private.CoreLib.dll",
            "System.Runtime.dll",
            "System.Collections.dll",
            "System.Console.dll",
            "System.IO.Compression.dll"
        )
        foreach ($FileName in $RequiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir $FileName) -PathType Leaf)) {
                return $false
            }
        }
        return $true
    }

    try {
        $RuntimeLines = & $DotnetPath --list-runtimes 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        $DotnetRoot = Split-Path -Parent (Resolve-Path -LiteralPath $DotnetPath).Path
        $LocalRuntimeRoot = Join-Path $DotnetRoot "shared\Microsoft.NETCore.App"
        if (Test-Path -LiteralPath $LocalRuntimeRoot -PathType Container) {
            $LocalRuntime = Get-ChildItem -LiteralPath $LocalRuntimeRoot -Directory |
                Where-Object { $_.Name -match '^8\.' } |
                Sort-Object @{ Expression = { [version]$_.Name }; Descending = $true } |
                Select-Object -First 1
            if ($null -ne $LocalRuntime -and (Test-DotNet8RuntimeDirectory $LocalRuntime.FullName)) {
                return $true
            }
        }

        foreach ($Line in $RuntimeLines) {
            if ($Line -match '^Microsoft\.NETCore\.App\s+(8\.[0-9]+\.[0-9]+)\s+\[(.+)\]$') {
                $RuntimeDir = Join-Path $Matches[2] $Matches[1]
                if (Test-DotNet8RuntimeDirectory $RuntimeDir) {
                    return $true
                }
            }
        }
        return $false
    }
    catch {
        return $false
    }
}

function Get-LocalDotNet8 {
    param([string]$RepoRoot)

    $LocalDotnet = Join-Path $RepoRoot "tools\dotnet-runtime\dotnet.exe"
    if (Test-DotNet8Runtime $LocalDotnet) {
        return $LocalDotnet
    }

    return $null
}

function Get-SystemDotNet8 {
    $Command = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -ne $Command -and (Test-DotNet8Runtime $Command.Source)) {
        return $Command.Source
    }

    return $null
}

function Get-UsableDotNet8 {
    param([string]$RepoRoot)

    $LocalDotnet = Get-LocalDotNet8 -RepoRoot $RepoRoot
    if (-not [string]::IsNullOrWhiteSpace($LocalDotnet)) {
        return $LocalDotnet
    }

    if (Test-Poe2ReleaseMode) {
        return $null
    }

    $SystemDotnet = Get-SystemDotNet8
    if (-not [string]::IsNullOrWhiteSpace($SystemDotnet)) {
        return $SystemDotnet
    }

    return $null
}

function Test-ZipHeader {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    $File = Get-Item -LiteralPath $Path
    if ($File.Length -lt 1048576) {
        return $false
    }

    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Bytes = New-Object byte[] 2
        [void]$Stream.Read($Bytes, 0, 2)
        return ($Bytes[0] -eq 0x50 -and $Bytes[1] -eq 0x4B)
    }
    finally {
        $Stream.Dispose()
    }
}

function Invoke-DownloadWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$Retries = 3
    )

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }

    for ($Attempt = 1; $Attempt -le $Retries; $Attempt++) {
        try {
            if (Test-Path -LiteralPath $OutFile -PathType Leaf) {
                Remove-Item -LiteralPath $OutFile -Force
            }
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 180
            if (-not (Test-ZipHeader $OutFile)) {
                throw "Downloaded file is not a valid runtime zip."
            }
            return
        }
        catch {
            if ($Attempt -ge $Retries) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Min(10, $Attempt * 2))
        }
    }
}

function Install-LocalDotNet8Runtime {
    param([string]$RepoRoot)

    $RuntimeVersions = @("8.0.28", "8.0.27")
    $DownloadDir = Join-Path $RepoRoot "tools\downloads"
    $RuntimeDir = Join-Path $RepoRoot "tools\dotnet-runtime"

    New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

    foreach ($RuntimeVersion in $RuntimeVersions) {
        $RuntimeFile = "dotnet-runtime-$RuntimeVersion-win-x64.zip"
        $ZipPath = Join-Path $DownloadDir $RuntimeFile
        $Sources = @(
            @{
                Name = "Huawei Cloud mirror"
                Url = "https://mirrors.huaweicloud.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
            },
            @{
                Name = "Huawei Cloud repo mirror"
                Url = "https://repo.huaweicloud.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
            },
            @{
                Name = "Microsoft official fallback"
                Url = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
            }
        )

        foreach ($Source in $Sources) {
            try {
                Write-Host "Download .NET 8 runtime $RuntimeVersion`: $($Source.Name)"
                Invoke-DownloadWithRetry -Url $Source.Url -OutFile $ZipPath

                if (Test-Path -LiteralPath $RuntimeDir -PathType Container) {
                    Remove-Item -LiteralPath $RuntimeDir -Recurse -Force
                }
                New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
                Expand-Archive -LiteralPath $ZipPath -DestinationPath $RuntimeDir -Force

                $LocalDotnet = Join-Path $RuntimeDir "dotnet.exe"
                if (Test-DotNet8Runtime $LocalDotnet) {
                    Write-Host ".NET 8 runtime ready: $LocalDotnet" -ForegroundColor Green
                    return $LocalDotnet
                }
                throw "Extracted runtime is not usable."
            }
            catch {
                Write-Warning "$RuntimeVersion $($Source.Name) failed: $($_.Exception.Message)"
            }
        }
    }

    throw "Unable to prepare .NET 8 runtime. Please check your network and run again."
}

function Ensure-DotNet8Runtime {
    param([string]$RepoRoot)

    $Dotnet = Get-UsableDotNet8 -RepoRoot $RepoRoot
    if (-not [string]::IsNullOrWhiteSpace($Dotnet)) {
        return $Dotnet
    }

    if (Test-Poe2ReleaseMode) {
        Write-Host ""
        Write-Host "==> 内置 .NET 运行时不可用，正在自动修复" -ForegroundColor Cyan
        return Install-LocalDotNet8Runtime -RepoRoot $RepoRoot
    }

    Write-Host ""
    Write-Host "==> Prepare .NET 8 runtime" -ForegroundColor Cyan
    return Install-LocalDotNet8Runtime -RepoRoot $RepoRoot
}

function Invoke-DotNet8 {
    param(
        [Parameter(Mandatory = $true)][string]$Dotnet,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [AllowNull()][string]$InputText = $null,
        [switch]$Quiet
    )

    if ([string]::IsNullOrWhiteSpace($Dotnet) -or -not (Test-Path -LiteralPath $Dotnet -PathType Leaf)) {
        throw "Missing dotnet executable: $Dotnet"
    }

    $DotnetPath = (Resolve-Path -LiteralPath $Dotnet).Path
    $DotnetRoot = Split-Path -Parent $DotnetPath
    $OldDotnetRoot = $env:DOTNET_ROOT
    $OldDotnetMultilevelLookup = $env:DOTNET_MULTILEVEL_LOOKUP
    $OldErrorActionPreference = $ErrorActionPreference
    $PushedLocation = $false

    try {
        $env:DOTNET_ROOT = $DotnetRoot
        $env:DOTNET_MULTILEVEL_LOOKUP = "0"
        $ErrorActionPreference = "Continue"

        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
            Push-Location -LiteralPath $WorkingDirectory
            $PushedLocation = $true
        }

        if ($PSBoundParameters.ContainsKey("InputText")) {
            $Output = $InputText | & $DotnetPath @ArgumentList 2>&1
        }
        else {
            $Output = & $DotnetPath @ArgumentList 2>&1
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        if ($PushedLocation) {
            Pop-Location
        }
        $env:DOTNET_ROOT = $OldDotnetRoot
        $env:DOTNET_MULTILEVEL_LOOKUP = $OldDotnetMultilevelLookup
        $ErrorActionPreference = $OldErrorActionPreference
    }

    $Lines = @($Output | ForEach-Object { [string]$_ })
    if (-not $Quiet) {
        foreach ($Line in $Lines) {
            Write-Host $Line
        }
    }

    return [pscustomobject]@{
        ExitCode = $ExitCode
        Lines    = $Lines
        Text     = ($Lines -join "`n")
    }
}

function Set-Poe2PythonEnvironment {
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
}

function Invoke-Poe2Python {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [string[]]$ArgumentList = @(),
        [switch]$Quiet
    )

    Set-Poe2PythonEnvironment
    $OldErrorActionPreference = $ErrorActionPreference
    $Lines = New-Object System.Collections.Generic.List[string]
    try {
        $ErrorActionPreference = "Continue"
        & $Python @ArgumentList 2>&1 | ForEach-Object {
            $Line = [string]$_
            $Lines.Add($Line)
            if (-not $Quiet) {
                Write-Host $Line
            }
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $OldErrorActionPreference
    }

    $LineArray = @($Lines.ToArray())

    return [pscustomobject]@{
        ExitCode = $ExitCode
        Lines    = $LineArray
        Text     = ($LineArray -join "`n")
    }
}

function Test-Poe2PythonPackages {
    param([Parameter(Mandatory = $true)][string]$Python)

    $CheckCode = @"
import csv
import decimal
import html
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
"@

    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @("-c", $CheckCode) -Quiet
    return ($Result.ExitCode -eq 0)
}

function Install-LocalPythonRuntime {
    param([string]$RepoRoot)

    $PythonVersion = "3.10.6"
    $PythonZipName = "python-$PythonVersion-embed-amd64.zip"
    $DownloadDir = Join-Path $RepoRoot "tools\downloads"
    $PythonDir = Join-Path $RepoRoot "tools\python"
    $ZipPath = Join-Path $DownloadDir $PythonZipName

    New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

    $Sources = @(
        @{
            Name = "Python official"
            Url = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"
        }
    )

    foreach ($Source in $Sources) {
        try {
            Write-Host "Download Python runtime: $($Source.Name)"
            Invoke-DownloadWithRetry -Url $Source.Url -OutFile $ZipPath

            if (Test-Path -LiteralPath $PythonDir -PathType Container) {
                Remove-Item -LiteralPath $PythonDir -Recurse -Force
            }
            New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
            Expand-Archive -LiteralPath $ZipPath -DestinationPath $PythonDir -Force
            Set-Content -LiteralPath (Join-Path $PythonDir "python310._pth") -Encoding ASCII -Value @(
                "python310.zip",
                "."
            )

            $LocalPython = Join-Path $PythonDir "python.exe"
            if (Test-Poe2PythonPackages $LocalPython) {
                Write-Host "Python runtime ready: $LocalPython" -ForegroundColor Green
                return $LocalPython
            }
            throw "Extracted Python runtime is not usable."
        }
        catch {
            Write-Warning "$($Source.Name) failed: $($_.Exception.Message)"
        }
    }

    throw "Unable to prepare Python runtime. Please check your network and run again."
}

function Ensure-PythonRequests {
    param([string]$RepoRoot = "")

    Set-Poe2PythonEnvironment

    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $LocalPython = Join-Path $RepoRoot "tools\python\python.exe"
        if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
            if (Test-Poe2PythonPackages $LocalPython) {
                return $LocalPython
            }
        }
    }

    if (Test-Poe2ReleaseMode) {
        Write-Host ""
        Write-Host "==> 内置 Python 不可用，正在自动修复" -ForegroundColor Cyan
        return Install-LocalPythonRuntime -RepoRoot $RepoRoot
    }

    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $PythonCommand) {
        $Python = $PythonCommand.Source
        if (Test-Poe2PythonPackages $Python) {
            return $Python
        }
    }

    Write-Host ""
    Write-Host "==> Prepare local Python runtime" -ForegroundColor Cyan
    return Install-LocalPythonRuntime -RepoRoot $RepoRoot
}

