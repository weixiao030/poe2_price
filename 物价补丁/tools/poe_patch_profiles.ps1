function Get-PoePatchSettingsPath {
    param([string]$SettingsPath = "")

    if (-not [string]::IsNullOrWhiteSpace($SettingsPath)) {
        return [System.IO.Path]::GetFullPath(
            [Environment]::ExpandEnvironmentVariables($SettingsPath.Trim().Trim('"'))
        )
    }

    $LocalAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
        return $null
    }
    return (Join-Path $LocalAppData "PoePricePatch\settings.json")
}

function Get-PoePatchSettingsState {
    param([string]$SettingsPath = "")

    $State = [ordered]@{
        version = 1
        poe1_game_directory = ""
        poe2_game_directory = ""
        poe1_language_mode = "auto"
        last_game_version = ""
        saved_at_utc = ""
    }
    try {
        $StatePath = Get-PoePatchSettingsPath -SettingsPath $SettingsPath
        if ([string]::IsNullOrWhiteSpace($StatePath) -or
            -not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
            return $State
        }
        $Previous = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($Property in @($Previous.PSObject.Properties)) {
            $State[$Property.Name] = $Property.Value
        }
    }
    catch {
        # A corrupt optional preference file must not block an update.
    }
    return $State
}

function Save-PoePatchSettingsState {
    param(
        [Parameter(Mandatory = $true)]$State,
        [string]$SettingsPath = ""
    )

    $StatePath = Get-PoePatchSettingsPath -SettingsPath $SettingsPath
    if ([string]::IsNullOrWhiteSpace($StatePath)) {
        return
    }
    $StateDir = Split-Path -Parent $StatePath
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $TempPath = Join-Path $StateDir ([string]::Concat("settings-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Json = $State | ConvertTo-Json -Depth 8
        [System.IO.File]::WriteAllText($TempPath, $Json, (New-Object System.Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
            try {
                [System.IO.File]::Replace($TempPath, $StatePath, $null)
            }
            catch {
                Move-Item -LiteralPath $TempPath -Destination $StatePath -Force
            }
        }
        else {
            [System.IO.File]::Move($TempPath, $StatePath)
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempPath -PathType Leaf) {
            Remove-Item -LiteralPath $TempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-PoePatchSavedGameDirectory {
    param(
        [ValidateSet("poe1", "poe2")]
        [string]$GameVersion,
        [string]$SettingsPath = ""
    )

    try {
        $State = Get-PoePatchSettingsState -SettingsPath $SettingsPath
        $PropertyName = "${GameVersion}_game_directory"
        $Value = [string]$State.$PropertyName
        if ([string]::IsNullOrWhiteSpace($Value)) {
            if ($GameVersion -eq "poe2") {
                return (Get-Poe2SavedGameDirectory)
            }
            return $null
        }

        $Resolved = ConvertTo-PoeGameDirectoryPath -Path $Value
        if ([string]::IsNullOrWhiteSpace($Resolved)) {
            return $null
        }
        $DetectedVersion = Get-PoeDetectedGameVersion -GameDirectory $Resolved
        if (-not [string]::IsNullOrWhiteSpace($DetectedVersion) -and $DetectedVersion -ne $GameVersion) {
            return $null
        }
        return $Resolved
    }
    catch {
        if ($GameVersion -eq "poe2") {
            return (Get-Poe2SavedGameDirectory)
        }
        return $null
    }
}

function Save-PoePatchGameDirectory {
    param(
        [ValidateSet("poe1", "poe2")]
        [string]$GameVersion,
        [Parameter(Mandatory = $true)][string]$GameDirectory,
        [string]$SettingsPath = ""
    )

    $Resolved = ConvertTo-PoeGameDirectoryPath -Path $GameDirectory
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        throw "无法保存无效的游戏目录：$GameDirectory"
    }

    $DetectedVersion = Get-PoeDetectedGameVersion -GameDirectory $Resolved
    if (-not [string]::IsNullOrWhiteSpace($DetectedVersion) -and $DetectedVersion -ne $GameVersion) {
        throw "所选目录属于 $($DetectedVersion.ToUpperInvariant())，不能保存为 $($GameVersion.ToUpperInvariant())。"
    }

    $State = Get-PoePatchSettingsState -SettingsPath $SettingsPath
    $State["version"] = 1
    $State["${GameVersion}_game_directory"] = $Resolved
    $State["last_game_version"] = $GameVersion
    $State["saved_at_utc"] = (Get-Date).ToUniversalTime().ToString("o")
    Save-PoePatchSettingsState -State $State -SettingsPath $SettingsPath
    return $Resolved
}

function Resolve-Poe1LanguageMode {
    param([string]$LanguageMode = "auto")

    $Normalized = if ([string]::IsNullOrWhiteSpace($LanguageMode)) {
        "auto"
    }
    else {
        $LanguageMode.Trim().ToLowerInvariant()
    }
    switch ($Normalized) {
        "auto" { return "auto" }
        "localization" { return "localization" }
        "zh-cn" { return "zh-CN" }
        "zh-tw" { return "zh-TW" }
        "config" { return "config" }
        default { return "auto" }
    }
}

function Get-Poe1SavedLanguageMode {
    param([string]$SettingsPath = "")

    $State = Get-PoePatchSettingsState -SettingsPath $SettingsPath
    return (Resolve-Poe1LanguageMode -LanguageMode ([string]$State.poe1_language_mode))
}

function Save-Poe1LanguageMode {
    param(
        [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
        [string]$LanguageMode = "auto",
        [string]$SettingsPath = ""
    )

    $State = Get-PoePatchSettingsState -SettingsPath $SettingsPath
    $State["version"] = 1
    $State["poe1_language_mode"] = Resolve-Poe1LanguageMode -LanguageMode $LanguageMode
    $State["saved_at_utc"] = (Get-Date).ToUniversalTime().ToString("o")
    Save-PoePatchSettingsState -State $State -SettingsPath $SettingsPath
    return [string]$State["poe1_language_mode"]
}

function Test-PoeGameDirectory {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    try {
        $Resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
        return (
            (Test-Path -LiteralPath (Join-Path $Resolved "Content.ggpk") -PathType Leaf) -or
            (Test-Path -LiteralPath (Join-Path $Resolved "Bundles2\_.index.bin") -PathType Leaf)
        )
    }
    catch {
        return $false
    }
}

function ConvertTo-PoeGameDirectoryPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    try {
        $Candidate = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $Candidate = Split-Path -Parent (Resolve-Path -LiteralPath $Candidate).Path
        }
        if ((Split-Path -Leaf $Candidate) -ieq "Bundles2") {
            $Candidate = Split-Path -Parent $Candidate
        }
        for ($Depth = 0; $Depth -lt 3 -and -not [string]::IsNullOrWhiteSpace($Candidate); $Depth += 1) {
            if (Test-PoeGameDirectory -Path $Candidate) {
                return (Resolve-Path -LiteralPath $Candidate).Path
            }
            $Parent = Split-Path -Parent $Candidate
            if ([string]::IsNullOrWhiteSpace($Parent) -or $Parent -eq $Candidate) {
                break
            }
            $Candidate = $Parent
        }
    }
    catch {
        return $null
    }
    return $null
}

function Get-PoeExecutableMajorVersion {
    param([Parameter(Mandatory = $true)][string]$GameDirectory)

    foreach ($Name in @(
            "PathOfExile_x64Steam.exe",
            "PathOfExileSteam.exe",
            "PathOfExile_x64.exe",
            "PathOfExile.exe",
            "Client.exe"
        )) {
        $Path = Join-Path $GameDirectory $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            continue
        }
        try {
            $Version = (Get-Item -LiteralPath $Path).VersionInfo.FileVersion
            if (-not [string]::IsNullOrWhiteSpace($Version) -and $Version -match '^(\d+)\.') {
                return [int]$Matches[1]
            }
        }
        catch {
            continue
        }
    }
    return 0
}

function Get-PoeDetectedGameVersion {
    param([Parameter(Mandatory = $true)][string]$GameDirectory)

    $Resolved = ConvertTo-PoeGameDirectoryPath -Path $GameDirectory
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        return $null
    }

    $Leaf = Split-Path -Leaf $Resolved
    if ($Leaf -match '(?i)(?:Path\s+of\s+Exile\s*(?:2|II)|流放之路\s*(?:2|[:：]?\s*降临)|(?:^|[^A-Z0-9])POE\s*2(?:[^A-Z0-9]|$))') {
        return "poe2"
    }
    if ($Leaf -match '(?i)(?:^Path\s+of\s+Exile(?:\s*\(\d+\))?$|^流放之路(?:\(\d+\))?$|^POE\s*1$)') {
        return "poe1"
    }
    if (Test-Path -LiteralPath (Join-Path $Resolved "poe2_helper_sdk.dll") -PathType Leaf) {
        return "poe2"
    }

    $MajorVersion = Get-PoeExecutableMajorVersion -GameDirectory $Resolved
    if ($MajorVersion -eq 3) {
        return "poe1"
    }
    if ($MajorVersion -ge 4) {
        return "poe2"
    }

    $IndexPath = Join-Path $Resolved "Bundles2\_.index.bin"
    $Detector = Join-Path $PSScriptRoot "BundleExtractor\BundleExtractor.exe"
    if ((Test-Path -LiteralPath $IndexPath -PathType Leaf) -and
        (Test-Path -LiteralPath $Detector -PathType Leaf)) {
        try {
            $Output = @(& $Detector --detect-game $IndexPath 2>$null)
            if ($LASTEXITCODE -eq 0) {
                $Detected = [string]($Output | Select-Object -Last 1)
                $Detected = $Detected.Trim().ToLowerInvariant()
                if ($Detected -in @("poe1", "poe2")) {
                    return $Detected
                }
            }
        }
        catch {
            # Older extractors do not expose --detect-game; name/version checks remain valid.
        }
    }
    return $null
}

function Get-Poe1LanguageInfoFromCode {
    param(
        [string]$LanguageCode,
        [string]$DefaultLanguageCode = "zh-TW"
    )

    $CodeText = if ([string]::IsNullOrWhiteSpace($LanguageCode)) { $DefaultLanguageCode } else { $LanguageCode.Trim() }
    $Code = $CodeText.ToLowerInvariant().Replace("_", "-")
    $Info = $null
    if ($Code -in @("en", "en-us", "en-gb", "english")) {
        $Info = @("English", "data/baseitemtypes.datc64", "en")
    }
    elseif ($Code -in @("zh-tw", "zh-hant", "traditional chinese", "traditional-chinese", "tc")) {
        $Info = @("Traditional Chinese", "data/traditional chinese/baseitemtypes.datc64", "zh-TW")
    }
    elseif ($Code -in @("zh-cn", "zh-hans", "simplified chinese", "simplified-chinese", "sc")) {
        $Info = @("Simplified Chinese", "data/simplified chinese/baseitemtypes.datc64", "zh-CN")
    }
    elseif ($Code -like "ja*") { $Info = @("Japanese", "data/japanese/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "ko*") { $Info = @("Korean", "data/korean/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "ru*") { $Info = @("Russian", "data/russian/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "fr*") { $Info = @("French", "data/french/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "de*") { $Info = @("German", "data/german/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "es*") { $Info = @("Spanish", "data/spanish/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "pt*") { $Info = @("Portuguese", "data/portuguese/baseitemtypes.datc64", $CodeText) }
    elseif ($Code -like "th*") { $Info = @("Thai", "data/thai/baseitemtypes.datc64", $CodeText) }

    if ($null -eq $Info) {
        $Fallback = Get-Poe1LanguageInfoFromCode -LanguageCode $DefaultLanguageCode -DefaultLanguageCode "en"
        $Fallback.Defaulted = $true
        $Fallback.DefaultReason = "无法识别 POE1 语言代码 '$CodeText'，已回退到 $($Fallback.Name)。可通过 POE1_PATCH_LANGUAGE 手动指定语言。"
        return $Fallback
    }
    return [pscustomobject]@{
        Name = $Info[0]
        Path = $Info[1]
        Code = $Info[2]
        Defaulted = [string]::IsNullOrWhiteSpace($LanguageCode)
        DefaultReason = $(if ([string]::IsNullOrWhiteSpace($LanguageCode)) { "未读取到 POE1 语言配置，已回退到 $($Info[0])。可通过 POE1_PATCH_LANGUAGE 手动指定语言。" } else { "" })
    }
}

function Get-Poe1ConfigLanguage {
    param(
        [string]$GameDirectory = "",
        [string]$ConfigDirectory = ""
    )

    $MyGames = if ([string]::IsNullOrWhiteSpace($ConfigDirectory)) {
        Join-Path ([Environment]::GetFolderPath("MyDocuments")) "My Games\Path of Exile"
    }
    else {
        $ConfigDirectory
    }
    if (-not (Test-Path -LiteralPath $MyGames -PathType Container)) {
        return $null
    }
    $ConfigFiles = @(Get-ChildItem -LiteralPath $MyGames -File -Filter "production*_Config.ini" -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending)
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

function Test-Poe1ChineseLanguageCode {
    param([string]$LanguageCode)

    if ([string]::IsNullOrWhiteSpace($LanguageCode)) { return $false }
    $Code = $LanguageCode.Trim().ToLowerInvariant().Replace("_", "-")
    return ($Code -in @(
            "zh-cn", "zh-hans", "simplified chinese", "simplified-chinese", "sc",
            "zh-tw", "zh-hant", "traditional chinese", "traditional-chinese", "tc"
        ))
}

function Get-Poe1LocalizationLogEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$GameDirectory,
        [int]$TailLines = 4000
    )

    $LogDirectory = Join-Path $GameDirectory "logs"
    $Candidates = New-Object System.Collections.ArrayList
    $Priority = 0
    foreach ($Name in @("LatestClient.txt", "Client.txt")) {
        $Path = Join-Path $LogDirectory $Name
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            $File = Get-Item -LiteralPath $Path
            [void]$Candidates.Add([pscustomobject]@{
                    Path = $File.FullName
                    LastWriteTimeUtc = $File.LastWriteTimeUtc
                    Priority = $Priority
                })
        }
        $Priority += 1
    }
    $Candidates = @($Candidates | Sort-Object `
            @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true }, `
            @{ Expression = { $_.Priority }; Ascending = $true })

    foreach ($Candidate in $Candidates) {
        try {
            $Lines = @(Get-Content -LiteralPath $Candidate.Path -Encoding UTF8 -Tail $TailLines -ErrorAction Stop)
            for ($Index = $Lines.Count - 1; $Index -ge 0; $Index -= 1) {
                $Line = [string]$Lines[$Index]
                $Area = ""
                if ($Line -match '\[SCENE\]\s+Set Source \[(?<area>[^\]]+)\]') {
                    $Area = $Matches.area.Trim()
                }
                elseif ($Line -match '\[LOADING SCREEN\]\s+\((?<area>[^\)]+)\)') {
                    $Area = $Matches.area.Trim()
                }
                if ([string]::IsNullOrWhiteSpace($Area) -or
                    $Area -in @("(null)", "(unknown)", "null", "unknown")) {
                    continue
                }
                $HasCjk = [bool]($Area -match '[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]')
                return [pscustomobject]@{
                    Detected = $HasCjk
                    AreaName = $Area
                    LogPath = [string]$Candidate.Path
                    LogLastWriteTimeUtc = $Candidate.LastWriteTimeUtc
                }
            }
        }
        catch {
            continue
        }
    }
    return [pscustomobject]@{
        Detected = $false
        AreaName = ""
        LogPath = ""
        LogLastWriteTimeUtc = $null
    }
}

function Get-Poe1InstallInfo {
    param(
        [Parameter(Mandatory = $true)][string]$GameDirectory,
        [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
        [string]$LanguageMode = "auto"
    )

    $Resolved = ConvertTo-PoeGameDirectoryPath -Path $GameDirectory
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        throw "无法检测 POE1 游戏目录：请选择直接包含 Content.ggpk 或 Bundles2\_.index.bin 的游戏根目录。"
    }
    $DetectedVersion = Get-PoeDetectedGameVersion -GameDirectory $Resolved
    if (-not [string]::IsNullOrWhiteSpace($DetectedVersion) -and $DetectedVersion -ne "poe1") {
        throw "所选目录是 POE2 客户端，不是 POE1：$Resolved"
    }

    $Mode = Get-Poe2GameMode -Poe2Dir $Resolved
    $IsChina = Test-Poe2ChinaClient -Poe2Dir $Resolved
    $LanguageMode = Resolve-Poe1LanguageMode -LanguageMode $LanguageMode
    $ConfiguredLanguage = Get-Poe1ConfigLanguage -GameDirectory $Resolved
    $DefaultLanguageCode = if ($IsChina) { "zh-CN" } else { "zh-TW" }
    $TargetLanguageCode = $ConfiguredLanguage
    $LanguageSelectionReason = "跟随游戏配置。"
    $LocalizationEvidence = [pscustomobject]@{
        Detected = $false
        AreaName = ""
        LogPath = ""
        LogLastWriteTimeUtc = $null
    }

    switch ($LanguageMode) {
        "localization" {
            $TargetLanguageCode = "zh-TW"
            $LanguageSelectionReason = "已选择汉化补丁，固定写入繁体中文资源表。"
        }
        "zh-CN" {
            $TargetLanguageCode = "zh-CN"
            $LanguageSelectionReason = "已固定写入简体中文资源表。"
        }
        "zh-TW" {
            $TargetLanguageCode = "zh-TW"
            $LanguageSelectionReason = "已固定写入繁体中文资源表。"
        }
        "config" {
            $LanguageSelectionReason = "严格跟随 production_Config.ini。"
        }
        default {
            if ($IsChina) {
                $TargetLanguageCode = "zh-CN"
                $LanguageSelectionReason = "自动识别为国服，固定写入简体中文资源表。"
            }
            elseif (-not [string]::IsNullOrWhiteSpace($env:POE1_PATCH_LANGUAGE)) {
                $TargetLanguageCode = $env:POE1_PATCH_LANGUAGE
                $LanguageSelectionReason = "自动模式使用 POE1_PATCH_LANGUAGE 环境变量。"
            }
            elseif (Test-Poe1ChineseLanguageCode -LanguageCode $ConfiguredLanguage) {
                $LanguageSelectionReason = "游戏配置已是中文，直接使用对应中文资源表。"
            }
            else {
                $LocalizationEvidence = Get-Poe1LocalizationLogEvidence -GameDirectory $Resolved
                if ($LocalizationEvidence.Detected) {
                    $TargetLanguageCode = "zh-TW"
                    $LanguageSelectionReason = "客户端配置为非中文，但最新日志显示中文区域：$($LocalizationEvidence.AreaName)。已按汉化补丁写入繁体中文资源表。"
                }
                else {
                    $LanguageSelectionReason = "未检测到汉化补丁，跟随游戏配置。"
                }
            }
        }
    }
    $LanguageInfo = Get-Poe1LanguageInfoFromCode -LanguageCode $TargetLanguageCode -DefaultLanguageCode $DefaultLanguageCode

    $InstallKind = "POE1-Intl-Bundles2"
    $DisplayName = "POE1 国际服 Steam Bundles2"
    if ($Mode -eq "GGPK") {
        $InstallKind = "POE1-Intl-Standalone-GGPK"
        $DisplayName = "POE1 国际服官方 GGPK"
    }
    elseif ($IsChina) {
        $InstallKind = "POE1-CN-WeGame-Bundles2"
        $DisplayName = "POE1 国服 WeGame Bundles2"
    }

    $WordsPath = $LanguageInfo.Path -replace 'baseitemtypes\.datc64$', 'words.datc64'
    return [pscustomobject]@{
        GameVersion = "poe1"
        GameName = "Path of Exile 1"
        Mode = $Mode
        InstallKind = $InstallKind
        DisplayName = $DisplayName
        IsChina = $IsChina
        ConfigLanguage = $(if ([string]::IsNullOrWhiteSpace($ConfiguredLanguage)) { "" } else { $ConfiguredLanguage })
        ConfiguredLanguage = $(if ([string]::IsNullOrWhiteSpace($ConfiguredLanguage)) { "" } else { $ConfiguredLanguage })
        EffectiveLanguageCode = [string]$LanguageInfo.Code
        LanguageMode = $LanguageMode
        LanguageSelectionReason = $LanguageSelectionReason
        LocalizationDetected = [bool]$LocalizationEvidence.Detected
        LocalizationAreaName = [string]$LocalizationEvidence.AreaName
        LocalizationLogPath = [string]$LocalizationEvidence.LogPath
        EnBaseItemsPath = "data/baseitemtypes.datc64"
        TcBaseItemsPath = $LanguageInfo.Path
        EnWordsPath = "data/words.datc64"
        TcWordsPath = $WordsPath
        TcEndgameMapsPath = ""
        UniqueNameIndexPath = ""
        LanguageName = $LanguageInfo.Name
        LanguageFileSlug = ($LanguageInfo.Path -replace '/', '_')
        WordsFileSlug = ($WordsPath -replace '/', '_')
        EndgameMapsFileSlug = ""
        LanguageDefaulted = [bool]$LanguageInfo.Defaulted
        LanguageDefaultReason = [string]$LanguageInfo.DefaultReason
        SupportsEndgameMaps = $false
        PersistentStateDirectoryName = ".poe1-price-patch"
        OutputDirectoryName = "poe1_price_patch_latest"
    }
}

function Get-PoePatchInstallInfo {
    param(
        [ValidateSet("poe1", "poe2")]
        [string]$GameVersion,
        [Parameter(Mandatory = $true)][string]$GameDirectory,
        [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
        [string]$Poe1LanguageMode = "auto"
    )

    if ($GameVersion -eq "poe1") {
        return (Get-Poe1InstallInfo -GameDirectory $GameDirectory -LanguageMode $Poe1LanguageMode)
    }
    $Info = Get-Poe2InstallInfo -Poe2Dir $GameDirectory
    Add-Member -InputObject $Info -NotePropertyName GameVersion -NotePropertyValue "poe2" -Force
    Add-Member -InputObject $Info -NotePropertyName GameName -NotePropertyValue "Path of Exile 2" -Force
    Add-Member -InputObject $Info -NotePropertyName EnWordsPath -NotePropertyValue "data/balance/words.datc64" -Force
    Add-Member -InputObject $Info -NotePropertyName UniqueNameIndexPath -NotePropertyValue "data/balance/uniquegoldprices.datc64" -Force
    Add-Member -InputObject $Info -NotePropertyName SupportsEndgameMaps -NotePropertyValue $true -Force
    Add-Member -InputObject $Info -NotePropertyName PersistentStateDirectoryName -NotePropertyValue ".poe2-price-patch" -Force
    Add-Member -InputObject $Info -NotePropertyName OutputDirectoryName -NotePropertyValue "poe2_price_patch_latest" -Force
    return $Info
}

function Get-Poe1GameDirectoryCandidates {
    param(
        [string]$PreferredRoot = "",
        [string[]]$AdditionalPaths = @(),
        [string]$SettingsPath = "",
        [switch]$IgnoreSavedDirectory,
        [switch]$SkipSystemGameDiscovery
    )

    $Results = New-Object System.Collections.ArrayList
    $Seen = @{}
    function Add-Poe1Candidate {
        param([string]$Path, [string]$Source, [int]$Priority)

        $Resolved = ConvertTo-PoeGameDirectoryPath -Path $Path
        if ([string]::IsNullOrWhiteSpace($Resolved)) { return }
        $Detected = Get-PoeDetectedGameVersion -GameDirectory $Resolved
        if (-not [string]::IsNullOrWhiteSpace($Detected) -and $Detected -ne "poe1") { return }
        $Key = $Resolved.ToUpperInvariant()
        if ($Seen.ContainsKey($Key)) { return }
        try { $Info = Get-Poe1InstallInfo -GameDirectory $Resolved } catch { return }
        $Seen[$Key] = $true
        [void]$Results.Add([pscustomobject]@{
                GameVersion = "poe1"
                Path = $Resolved
                Source = $Source
                Priority = $Priority
                InstallInfo = $Info
            })
    }

    Add-Poe1Candidate -Path $PreferredRoot -Source "补丁文件夹上一级" -Priority 0
    foreach ($Path in @($AdditionalPaths)) {
        Add-Poe1Candidate -Path $Path -Source "附加候选路径" -Priority 5
    }
    if (-not $IgnoreSavedDirectory) {
        Add-Poe1Candidate -Path (Get-PoePatchSavedGameDirectory -GameVersion poe1 -SettingsPath $SettingsPath) -Source "最近使用的 POE1 目录" -Priority 8
    }
    foreach ($Name in @("POE1_GAME_DIR", "POE1_DIR")) {
        Add-Poe1Candidate -Path ([Environment]::GetEnvironmentVariable($Name)) -Source "环境变量 $Name" -Priority 6
    }
    if ($SkipSystemGameDiscovery) {
        return @($Results | Sort-Object Priority, Path)
    }

    $UninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($Root in $UninstallRoots) {
        foreach ($Entry in @(Get-ItemProperty -Path $Root -ErrorAction SilentlyContinue)) {
            $Name = [string]$Entry.DisplayName
            if ($Name -notmatch '(?i)(?:^Path\s+of\s+Exile(?:\s+Steam)?$|^流放之路(?:\s*\(\d+\))?$)') { continue }
            foreach ($Property in @("InstallLocation", "DisplayIcon", "InstallSource")) {
                Add-Poe1Candidate -Path ([string]$Entry.$Property) -Source "已安装程序：$Name" -Priority 20
            }
        }
    }

    foreach ($Drive in @([System.IO.DriveInfo]::GetDrives())) {
        try {
            if (-not $Drive.IsReady -or $Drive.DriveType -notin @([System.IO.DriveType]::Fixed, [System.IO.DriveType]::Removable)) { continue }
            foreach ($Relative in @(
                    "SteamLibrary\steamapps\common\Path of Exile",
                    "Program Files (x86)\Steam\steamapps\common\Path of Exile",
                    "Program Files\Steam\steamapps\common\Path of Exile",
                    "WeGameApps\rail_apps\流放之路(511)",
                    "Grinding Gear Games\Path of Exile"
                )) {
                Add-Poe1Candidate -Path (Join-Path $Drive.Root $Relative) -Source "常见游戏目录" -Priority 30
            }
            $RailRoot = Join-Path $Drive.Root "WeGameApps\rail_apps"
            if (Test-Path -LiteralPath $RailRoot -PathType Container) {
                foreach ($Directory in @(Get-ChildItem -LiteralPath $RailRoot -Directory -ErrorAction SilentlyContinue)) {
                    if ($Directory.Name -match '^流放之路(?:\(\d+\))?$') {
                        Add-Poe1Candidate -Path $Directory.FullName -Source "WeGame 游戏库" -Priority 25
                    }
                }
            }
        }
        catch {
            continue
        }
    }
    return @($Results | Sort-Object Priority, Path)
}

function Get-PoePatchGameDirectoryCandidates {
    param(
        [ValidateSet("auto", "poe1", "poe2")]
        [string]$GameVersion = "auto",
        [string]$PreferredRoot = "",
        [string[]]$AdditionalPaths = @(),
        [switch]$SkipSystemGameDiscovery
    )

    $Results = New-Object System.Collections.ArrayList
    if ($GameVersion -in @("auto", "poe1")) {
        foreach ($Candidate in @(Get-Poe1GameDirectoryCandidates -PreferredRoot $PreferredRoot -AdditionalPaths $AdditionalPaths -SkipSystemGameDiscovery:$SkipSystemGameDiscovery)) {
            [void]$Results.Add($Candidate)
        }
    }
    if ($GameVersion -in @("auto", "poe2")) {
        foreach ($Candidate in @(Get-Poe2GameDirectoryCandidates -PreferredRoot $PreferredRoot -AdditionalPaths $AdditionalPaths -SkipSystemGameDiscovery:$SkipSystemGameDiscovery)) {
            try {
                # The generic POE2 Bundles2 scanner also sees POE1 clients.
                # Re-check the index before merging so one physical directory
                # cannot appear once as POE1 and again as POE2.
                $DetectedVersion = Get-PoeDetectedGameVersion -GameDirectory $Candidate.Path
                if ($DetectedVersion -eq "poe1") {
                    continue
                }
                $Info = Get-PoePatchInstallInfo -GameVersion poe2 -GameDirectory $Candidate.Path
                [void]$Results.Add([pscustomobject]@{
                        GameVersion = "poe2"
                        Path = $Candidate.Path
                        Source = $Candidate.Source
                        Priority = $Candidate.Priority
                        InstallInfo = $Info
                    })
            }
            catch {
                continue
            }
        }
    }

    $Seen = @{}
    return @($Results | Sort-Object Priority, GameVersion, Path | Where-Object {
            $Key = "$($_.GameVersion)|$($_.Path.ToUpperInvariant())"
            if ($Seen.ContainsKey($Key)) { return $false }
            $Seen[$Key] = $true
            return $true
        })
}

function Resolve-PoePatchManualSelection {
    param(
        [ValidateSet("auto", "poe1", "poe2")]
        [string]$RequestedGameVersion,
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet("auto", "localization", "zh-CN", "zh-TW", "config")]
        [string]$Poe1LanguageMode = "auto"
    )

    $Resolved = ConvertTo-PoeGameDirectoryPath -Path $Path
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        throw "请选择直接包含 Content.ggpk 或 Bundles2\_.index.bin 的游戏根目录。"
    }
    $Detected = Get-PoeDetectedGameVersion -GameDirectory $Resolved
    $GameVersion = if ($RequestedGameVersion -eq "auto") { $Detected } else { $RequestedGameVersion }
    if ([string]::IsNullOrWhiteSpace($GameVersion)) {
        throw "无法自动判断这是 POE1 还是 POE2，请在顶部明确选择游戏版本。"
    }
    if (-not [string]::IsNullOrWhiteSpace($Detected) -and $Detected -ne $GameVersion) {
        throw "所选目录属于 $($Detected.ToUpperInvariant())，与当前 $($GameVersion.ToUpperInvariant()) 选择不一致。"
    }
    $Info = Get-PoePatchInstallInfo -GameVersion $GameVersion -GameDirectory $Resolved `
        -Poe1LanguageMode $Poe1LanguageMode
    return [pscustomobject]@{
        GameVersion = $GameVersion
        Path = $Resolved
        Source = "手动选择"
        Priority = 0
        InstallInfo = $Info
    }
}
