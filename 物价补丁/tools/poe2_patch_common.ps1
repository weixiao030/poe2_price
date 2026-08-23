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

    $Kind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    $LanguageCode = [string]$InstallInfo.ConfigLanguage
    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        $LanguageCode = [string]$InstallInfo.LanguageName
    }
    $Language = ($LanguageCode -replace '[^A-Za-z0-9_-]+', '_')
    return "POE2还原补丁_${Kind}_${Language}.zip"
}

function Get-Poe2RestorePatchZipCandidateNames {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    $LegacyName = if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") {
        Get-Poe2PatchName "ChinaRestorePatchZip"
    }
    else {
        Get-Poe2PatchName "IntlRestorePatchZip"
    }
    return @(
        (Get-Poe2FixedRestorePatchZipName -InstallInfo $InstallInfo),
        $LegacyName
    ) | Select-Object -Unique
}

function Test-Poe2LegacyRestorePatchZipName {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Name = Split-Path -Leaf $Path
    return $Name -in @(
        (Get-Poe2PatchName "ChinaRestorePatchZip"),
        (Get-Poe2PatchName "IntlRestorePatchZip"),
        (Get-Poe2PatchName "RestorePatchZip")
    )
}

function Get-Poe2FixedPhysicalRestorePatchZipName {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    $Kind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    $LanguageCode = [string]$InstallInfo.ConfigLanguage
    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        $LanguageCode = [string]$InstallInfo.LanguageName
    }
    $Language = ($LanguageCode -replace '[^A-Za-z0-9_-]+', '_')
    return "POE2真实还原补丁_${Kind}_${Language}.zip"
}

function Get-Poe2PhysicalRestorePatchZipCandidateNames {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    return @(
        (Get-Poe2FixedPhysicalRestorePatchZipName -InstallInfo $InstallInfo),
        (Get-Poe2PatchName "PhysicalRestorePatchZip")
    ) | Select-Object -Unique
}

function Get-Poe2PatchOutputKey {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $Normalized = [System.IO.Path]::GetFullPath($Poe2Dir).TrimEnd('\', '/').ToUpperInvariant()
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Normalized)
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Hash = [System.BitConverter]::ToString($Sha256.ComputeHash($Bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Sha256.Dispose()
    }
    return $Hash.Substring(0, 16)
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
        throw "无法检测 POE2 游戏目录：请选择直接包含 Content.ggpk 或 Bundles2\_.index.bin 的游戏根目录。"
    }
}

function Test-Poe2GameDirectory {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    try {
        $Candidate = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
        if (-not (Test-Path -LiteralPath $Candidate -PathType Container -ErrorAction Stop)) {
            return $false
        }

        $Resolved = (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
        return (
            (Test-Path -LiteralPath (Join-Path $Resolved "Content.ggpk") -PathType Leaf -ErrorAction Stop) -or
            (Test-Path -LiteralPath (Join-Path $Resolved "Bundles2\_.index.bin") -PathType Leaf -ErrorAction Stop)
        )
    }
    catch {
        return $false
    }
}

function Get-PoeGggRegistryInstallLocations {
    param(
        [ValidateSet("poe1", "poe2")]
        [string]$GameVersion
    )

    $SubKey = if ($GameVersion -eq "poe1") { "Path of Exile" } else { "Path of Exile 2" }
    $RegistryPaths = @(
        "HKCU:\Software\GrindingGearGames\$SubKey",
        "HKLM:\SOFTWARE\GrindingGearGames\$SubKey",
        "HKLM:\SOFTWARE\WOW6432Node\GrindingGearGames\$SubKey"
    )
    $Results = New-Object System.Collections.ArrayList

    foreach ($RegistryPath in $RegistryPaths) {
        $Entry = Get-ItemProperty -LiteralPath $RegistryPath -ErrorAction SilentlyContinue
        if ($null -eq $Entry) {
            continue
        }
        foreach ($PropertyName in @("InstallLocation", "InstallPath", "Path", "GamePath")) {
            $Value = [string]$Entry.$PropertyName
            if ([string]::IsNullOrWhiteSpace($Value)) {
                continue
            }
            [void]$Results.Add([pscustomobject]@{
                    Path         = $Value
                    RegistryPath = $RegistryPath
                    PropertyName = $PropertyName
                })
        }
    }

    return @($Results)
}

function ConvertTo-Poe2GameDirectoryPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    try {
        $Candidate = [Environment]::ExpandEnvironmentVariables($Path.Trim())
        if ($Candidate -match '^\s*"([^"]+)"(?:,\s*-?\d+)?\s*$') {
            $Candidate = $Matches[1]
        }
        else {
            $Candidate = ($Candidate -replace ',\s*-?\d+\s*$', '').Trim().Trim('"')
        }

        if (Test-Path -LiteralPath $Candidate -PathType Leaf -ErrorAction Stop) {
            $Candidate = Split-Path -Parent (Resolve-Path -LiteralPath $Candidate).Path
        }

        for ($Depth = 0; $Depth -lt 3 -and -not [string]::IsNullOrWhiteSpace($Candidate); $Depth += 1) {
            if (Test-Poe2GameDirectory -Path $Candidate) {
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

function Test-Poe2GameDisplayName {
    param([string]$Name)

    if ([string]::IsNullOrWhiteSpace($Name)) {
        return $false
    }

    return ($Name.Trim() -match '(?i)(?:Path\s+of\s+Exile\s*(?:2|II)|流放之路\s*(?:2|[:：]?\s*降临)|(?:^|[^A-Z0-9])POE\s*2(?:[^A-Z0-9]|$))')
}

function Get-Poe2SettingsPath {
    param([string]$SettingsPath = "")

    if (-not [string]::IsNullOrWhiteSpace($SettingsPath)) {
        return [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($SettingsPath.Trim().Trim('"')))
    }

    $LocalAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
        return $null
    }
    return (Join-Path $LocalAppData "Poe2PricePatch\settings.json")
}

function Get-Poe2SavedGameDirectory {
    param([string]$SettingsPath = "")

    try {
        $StatePath = Get-Poe2SettingsPath -SettingsPath $SettingsPath
        if ([string]::IsNullOrWhiteSpace($StatePath) -or -not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
            return $null
        }

        $State = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        return (ConvertTo-Poe2GameDirectoryPath -Path ([string]$State.game_directory))
    }
    catch {
        return $null
    }
}

function Save-Poe2GameDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Poe2Dir,
        [string]$SettingsPath = ""
    )

    $Resolved = ConvertTo-Poe2GameDirectoryPath -Path $Poe2Dir
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        throw "无法保存无效的 POE2 游戏目录：$Poe2Dir"
    }

    $StatePath = Get-Poe2SettingsPath -SettingsPath $SettingsPath
    if ([string]::IsNullOrWhiteSpace($StatePath)) {
        return $Resolved
    }

    $StateDir = Split-Path -Parent $StatePath
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $TempPath = Join-Path $StateDir ([string]::Concat("settings-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    $Json = [pscustomobject]@{
        version        = 1
        game_directory = $Resolved
        saved_at_utc   = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json

    try {
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

    return $Resolved
}

function Enter-Poe2GameDirectoryMutex {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $Resolved = ConvertTo-Poe2GameDirectoryPath -Path $Poe2Dir
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        throw "无法为无效的 POE2 游戏目录创建运行锁：$Poe2Dir"
    }

    $Normalized = $Resolved.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar).ToUpperInvariant()
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Normalized))
    }
    finally {
        $Sha256.Dispose()
    }
    $Token = [string]::Concat(($Digest | ForEach-Object { $_.ToString("X2") }))
    $Mutex = New-Object System.Threading.Mutex($false, ("Local\Poe2PricePatch-Game-" + $Token))
    $Taken = $false
    try {
        $Taken = $Mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $Taken = $true
    }

    if (-not $Taken) {
        $Mutex.Dispose()
        throw "同一游戏目录的物价补丁正在运行，请等待当前更新或还原完成后再试：$Resolved"
    }
    return $Mutex
}

function Get-Poe2GameDirectoryCandidates {
    param(
        [string]$PreferredRoot = "",
        [string[]]$AdditionalPaths = @(),
        [string[]]$AdditionalWeGameRoots = @(),
        [string]$SettingsPath = "",
        [switch]$IgnoreSavedDirectory,
        [switch]$SkipSystemGameDiscovery
    )

    $Results = New-Object System.Collections.ArrayList
    $SeenPaths = @{}

    function Add-Poe2GameDirectoryCandidate {
        param(
            [string]$Path,
            [string]$Source,
            [int]$Priority
        )

        $Resolved = ConvertTo-Poe2GameDirectoryPath -Path $Path
        if ([string]::IsNullOrWhiteSpace($Resolved)) {
            return
        }

        $Key = $Resolved.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar).ToUpperInvariant()
        if ([string]::IsNullOrWhiteSpace($Key)) {
            $Key = $Resolved.ToUpperInvariant()
        }
        if ($SeenPaths.ContainsKey($Key)) {
            return
        }
        $SeenPaths[$Key] = $true
        try {
            $GameMode = Get-Poe2GameMode -Poe2Dir $Resolved
        }
        catch {
            return
        }
        [void]$Results.Add([pscustomobject]@{
                Path     = $Resolved
                Source   = $Source
                Mode     = $GameMode
                Priority = $Priority
            })
    }

    Add-Poe2GameDirectoryCandidate -Path $PreferredRoot -Source "补丁文件夹上一级" -Priority 0
    foreach ($Path in @($AdditionalPaths)) {
        Add-Poe2GameDirectoryCandidate -Path $Path -Source "附加候选路径" -Priority 5
    }
    if (-not $IgnoreSavedDirectory) {
        Add-Poe2GameDirectoryCandidate `
            -Path (Get-Poe2SavedGameDirectory -SettingsPath $SettingsPath) `
            -Source "最近使用的游戏目录" `
            -Priority 8
    }
    foreach ($VariableName in @("POE2_GAME_DIR", "POE2_DIR")) {
        Add-Poe2GameDirectoryCandidate `
            -Path ([Environment]::GetEnvironmentVariable($VariableName)) `
            -Source "环境变量 $VariableName" `
            -Priority 6
    }

    if (-not $SkipSystemGameDiscovery) {
        foreach ($Entry in @(Get-PoeGggRegistryInstallLocations -GameVersion poe2)) {
            Add-Poe2GameDirectoryCandidate `
                -Path ([string]$Entry.Path) `
                -Source "GGG 官服注册表" `
                -Priority 15
        }
    }

    $UninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    if (-not $SkipSystemGameDiscovery) {
        foreach ($Root in $UninstallRoots) {
            foreach ($Entry in @(Get-ItemProperty -Path $Root -ErrorAction SilentlyContinue)) {
                $DisplayName = [string]$Entry.DisplayName
                if (-not (Test-Poe2GameDisplayName -Name $DisplayName)) {
                    continue
                }
                foreach ($PropertyName in @("InstallLocation", "DisplayIcon", "InstallSource")) {
                    Add-Poe2GameDirectoryCandidate `
                        -Path ([string]$Entry.$PropertyName) `
                        -Source "已安装程序：$DisplayName" `
                        -Priority 20
                }
            }
        }
    }

    $WeGameLibraries = New-Object System.Collections.ArrayList
    $SeenWeGameLibraries = @{}
    function Add-WeGameLibrary {
        param([string]$Path)

        if ([string]::IsNullOrWhiteSpace($Path)) {
            return
        }

        try {
            $Expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
            if (Test-Path -LiteralPath $Expanded -PathType Leaf -ErrorAction Stop) {
                $Expanded = Split-Path -Parent (Resolve-Path -LiteralPath $Expanded -ErrorAction Stop).Path
            }
            $Parent = Split-Path -Parent $Expanded
            $Candidates = New-Object System.Collections.ArrayList
            [void]$Candidates.Add($Expanded)
            [void]$Candidates.Add((Join-Path $Expanded "rail_apps"))
            [void]$Candidates.Add((Join-Path $Expanded "WeGameApps\rail_apps"))
            if (-not [string]::IsNullOrWhiteSpace($Parent)) {
                [void]$Candidates.Add((Join-Path $Parent "WeGameApps\rail_apps"))
            }
            foreach ($Candidate in $Candidates) {
                if ([string]::IsNullOrWhiteSpace($Candidate) -or
                    -not (Test-Path -LiteralPath $Candidate -PathType Container -ErrorAction Stop)) {
                    continue
                }
                $Resolved = (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
                $Key = $Resolved.ToUpperInvariant()
                if (-not $SeenWeGameLibraries.ContainsKey($Key)) {
                    $SeenWeGameLibraries[$Key] = $true
                    [void]$WeGameLibraries.Add($Resolved)
                }
            }
        }
        catch {
            return
        }
    }

    foreach ($Path in @($AdditionalWeGameRoots)) {
        Add-WeGameLibrary -Path $Path
    }
    if (-not $SkipSystemGameDiscovery) {
        foreach ($VariableName in @("WEGAME_GAME_ROOT", "WEGAME_APPS_ROOT", "TENCENT_GAME_ROOT")) {
            Add-WeGameLibrary -Path ([Environment]::GetEnvironmentVariable($VariableName))
        }
        foreach ($WeGameRegistryPath in @(
                "HKCU:\Software\Tencent\WeGame",
                "HKLM:\SOFTWARE\Tencent\WeGame",
                "HKLM:\SOFTWARE\WOW6432Node\Tencent\WeGame"
            )) {
            $WeGameEntry = Get-ItemProperty -Path $WeGameRegistryPath -ErrorAction SilentlyContinue
            if ($null -eq $WeGameEntry) {
                continue
            }
            foreach ($PropertyName in @("InstallPath", "InstallLocation", "Path", "RootPath", "GamePath", "GameRoot")) {
                Add-WeGameLibrary -Path ([string]$WeGameEntry.$PropertyName)
            }
        }
        foreach ($Root in $UninstallRoots) {
            foreach ($Entry in @(Get-ItemProperty -Path $Root -ErrorAction SilentlyContinue)) {
                if ([string]$Entry.DisplayName -notmatch '(?i)(?:WeGame|腾讯游戏平台)') {
                    continue
                }
                foreach ($PropertyName in @("InstallLocation", "DisplayIcon", "InstallSource")) {
                    Add-WeGameLibrary -Path ([string]$Entry.$PropertyName)
                }
            }
        }
        foreach ($Drive in @([System.IO.DriveInfo]::GetDrives())) {
            try {
                if (-not $Drive.IsReady -or $Drive.DriveType -notin @([System.IO.DriveType]::Fixed, [System.IO.DriveType]::Removable)) {
                    continue
                }
                foreach ($Relative in @(
                        "WeGameApps\rail_apps",
                        "Program Files\WeGameApps\rail_apps",
                        "Program Files (x86)\WeGameApps\rail_apps",
                        "Tencent Games",
                        "腾讯游戏"
                    )) {
                    Add-WeGameLibrary -Path (Join-Path $Drive.Root $Relative)
                }
            }
            catch {
                continue
            }
        }
    }

    foreach ($Library in @($WeGameLibraries)) {
        if (Test-Poe2GameDisplayName -Name (Split-Path -Leaf $Library)) {
            Add-Poe2GameDirectoryCandidate -Path $Library -Source "WeGame 游戏库" -Priority 25
        }
        foreach ($Directory in @(Get-ChildItem -LiteralPath $Library -Directory -ErrorAction SilentlyContinue)) {
            if (Test-Poe2GameDisplayName -Name $Directory.Name) {
                Add-Poe2GameDirectoryCandidate -Path $Directory.FullName -Source "WeGame 游戏库" -Priority 25
            }
        }
    }

    if ($SkipSystemGameDiscovery) {
        return @($Results | Sort-Object Priority, Path)
    }

    $SteamRoots = New-Object System.Collections.ArrayList
    $SeenSteamRoots = @{}
    function Add-SteamRoot {
        param([string]$Path)

        if ([string]::IsNullOrWhiteSpace($Path)) {
            return
        }
        try {
            $Resolved = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"')))
            if (-not (Test-Path -LiteralPath $Resolved -PathType Container)) {
                return
            }
            $Key = $Resolved.ToUpperInvariant()
            if (-not $SeenSteamRoots.ContainsKey($Key)) {
                $SeenSteamRoots[$Key] = $true
                [void]$SteamRoots.Add($Resolved)
            }
        }
        catch {
            return
        }
    }

    Add-SteamRoot -Path (Join-Path ${env:ProgramFiles(x86)} "Steam" -ErrorAction SilentlyContinue)
    Add-SteamRoot -Path (Join-Path $env:ProgramFiles "Steam" -ErrorAction SilentlyContinue)
    foreach ($SteamRegistry in @(
            @{ Path = "HKCU:\Software\Valve\Steam"; Name = "SteamPath" },
            @{ Path = "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam"; Name = "InstallPath" },
            @{ Path = "HKLM:\SOFTWARE\Valve\Steam"; Name = "InstallPath" }
        )) {
        $SteamEntry = Get-ItemProperty -Path $SteamRegistry.Path -ErrorAction SilentlyContinue
        if ($null -ne $SteamEntry) {
            Add-SteamRoot -Path ([string]$SteamEntry.($SteamRegistry.Name))
        }
    }

    $SteamLibraries = New-Object System.Collections.ArrayList
    $SeenSteamLibraries = @{}
    function Add-SteamLibrary {
        param([string]$Path)

        if ([string]::IsNullOrWhiteSpace($Path)) {
            return
        }
        try {
            $Resolved = [System.IO.Path]::GetFullPath($Path)
            $Key = $Resolved.ToUpperInvariant()
            if (-not $SeenSteamLibraries.ContainsKey($Key)) {
                $SeenSteamLibraries[$Key] = $true
                [void]$SteamLibraries.Add($Resolved)
            }
        }
        catch {
            return
        }
    }

    foreach ($SteamRoot in @($SteamRoots)) {
        Add-SteamLibrary -Path $SteamRoot
        $LibraryConfig = Join-Path $SteamRoot "steamapps\libraryfolders.vdf"
        if (Test-Path -LiteralPath $LibraryConfig -PathType Leaf) {
            foreach ($Line in @(Get-Content -LiteralPath $LibraryConfig -Encoding UTF8 -ErrorAction SilentlyContinue)) {
                if ($Line -match '^\s*"(?:path|\d+)"\s+"([^"]+)"') {
                    Add-SteamLibrary -Path $Matches[1].Replace('\\', '\')
                }
            }
        }
    }

    foreach ($Library in @($SteamLibraries)) {
        $SteamApps = Join-Path $Library "steamapps"
        Add-Poe2GameDirectoryCandidate `
            -Path (Join-Path $SteamApps "common\Path of Exile 2") `
            -Source "Steam 游戏库" `
            -Priority 30

        foreach ($Manifest in @(Get-ChildItem -LiteralPath $SteamApps -Filter "appmanifest_*.acf" -File -ErrorAction SilentlyContinue)) {
            $ManifestText = Get-Content -LiteralPath $Manifest.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
            $ManifestName = ""
            if ($ManifestText -match '(?im)^\s*"name"\s+"([^"]+)"') {
                $ManifestName = $Matches[1]
            }
            if ((Test-Poe2GameDisplayName -Name $ManifestName) -and
                $ManifestText -match '(?im)^\s*"installdir"\s+"([^"]+)"') {
                Add-Poe2GameDirectoryCandidate `
                    -Path (Join-Path $SteamApps ("common\" + $Matches[1])) `
                    -Source "Steam 清单" `
                    -Priority 30
            }
        }
    }

    $ProgramDataRoot = $env:ProgramData
    if ([string]::IsNullOrWhiteSpace($ProgramDataRoot)) {
        $ProgramDataRoot = [Environment]::GetFolderPath("CommonApplicationData")
    }
    $EpicManifestRoot = Join-Path $ProgramDataRoot "Epic\EpicGamesLauncher\Data\Manifests" -ErrorAction SilentlyContinue
    foreach ($Manifest in @(Get-ChildItem -LiteralPath $EpicManifestRoot -Filter "*.item" -File -ErrorAction SilentlyContinue)) {
        try {
            $Item = Get-Content -LiteralPath $Manifest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if (Test-Poe2GameDisplayName -Name ([string]$Item.DisplayName)) {
                Add-Poe2GameDirectoryCandidate `
                    -Path ([string]$Item.InstallLocation) `
                    -Source "Epic 游戏清单" `
                    -Priority 40
            }
        }
        catch {
            continue
        }
    }

    foreach ($StandardPath in @(
            (Join-Path $env:ProgramFiles "Grinding Gear Games\Path of Exile 2" -ErrorAction SilentlyContinue),
            (Join-Path ${env:ProgramFiles(x86)} "Grinding Gear Games\Path of Exile 2" -ErrorAction SilentlyContinue),
            (Join-Path $env:LocalAppData "Programs\Path of Exile 2" -ErrorAction SilentlyContinue)
        )) {
        Add-Poe2GameDirectoryCandidate -Path $StandardPath -Source "常见安装位置" -Priority 50
    }

    return @($Results | Sort-Object Priority, Path)
}

function Resolve-Poe2GameDirectorySelection {
    param(
        [ValidateSet("auto", "manual")]
        [string]$Mode = "auto",
        [string]$ManualPath = "",
        [string]$PreferredRoot = "",
        [string[]]$AdditionalPaths = @(),
        [string[]]$AdditionalWeGameRoots = @(),
        [string]$SettingsPath = "",
        [switch]$IgnoreSavedDirectory,
        [switch]$SkipSystemGameDiscovery
    )

    if ($Mode -eq "manual") {
        $Resolved = ConvertTo-Poe2GameDirectoryPath -Path $ManualPath
        if ([string]::IsNullOrWhiteSpace($Resolved)) {
            throw "手动选择的文件夹不是有效的 POE2 游戏根目录。请选择包含 Content.ggpk 或 Bundles2\_.index.bin 的文件夹。"
        }
        return $Resolved
    }

    $Candidates = @(Get-Poe2GameDirectoryCandidates `
            -PreferredRoot $PreferredRoot `
            -AdditionalPaths $AdditionalPaths `
            -AdditionalWeGameRoots $AdditionalWeGameRoots `
            -SettingsPath $SettingsPath `
            -IgnoreSavedDirectory:$IgnoreSavedDirectory `
            -SkipSystemGameDiscovery:$SkipSystemGameDiscovery)
    if ($Candidates.Count -eq 0) {
        throw "自动识别失败。请切换到手动选择，并选择包含 Content.ggpk 或 Bundles2\_.index.bin 的 POE2 游戏根目录。"
    }

    $ExplicitCandidates = @($Candidates | Where-Object { [int]$_.Priority -lt 20 })
    if ($ExplicitCandidates.Count -gt 0) {
        return [string]$ExplicitCandidates[0].Path
    }
    if ($Candidates.Count -gt 1) {
        $CandidateText = [string]::Join("；", @($Candidates | ForEach-Object { [string]$_.Path }))
        throw "自动识别到多个 POE2 客户端，无法安全判断要操作哪一个。请切换到手动选择：$CandidateText"
    }
    return [string]$Candidates[0].Path
}

function Show-Poe2GameDirectorySelectionDialog {
    param(
        [string]$Title = "POE2 物价补丁",
        [string]$PreferredRoot = "",
        [string]$InitialPoe2Dir = "",
        [string]$ActionText = "请选择要操作的 POE2 游戏目录。"
    )

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $Form = New-Object System.Windows.Forms.Form
    $Form.Text = $Title
    $Form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $Form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $Form.MaximizeBox = $false
    $Form.MinimizeBox = $false
    $Form.ClientSize = New-Object System.Drawing.Size(620, 272)

    $ActionLabel = New-Object System.Windows.Forms.Label
    $ActionLabel.Text = $ActionText
    $ActionLabel.Location = New-Object System.Drawing.Point(22, 18)
    $ActionLabel.Size = New-Object System.Drawing.Size(576, 22)
    $Form.Controls.Add($ActionLabel)

    $AutoRadio = New-Object System.Windows.Forms.RadioButton
    $AutoRadio.Text = "自动识别游戏文件夹（推荐）"
    $AutoRadio.Location = New-Object System.Drawing.Point(24, 52)
    $AutoRadio.AutoSize = $true
    $Form.Controls.Add($AutoRadio)

    $ManualRadio = New-Object System.Windows.Forms.RadioButton
    $ManualRadio.Text = "手动选择游戏文件夹"
    $ManualRadio.Location = New-Object System.Drawing.Point(266, 52)
    $ManualRadio.AutoSize = $true
    $Form.Controls.Add($ManualRadio)

    $PathTextBox = New-Object System.Windows.Forms.TextBox
    $PathTextBox.Location = New-Object System.Drawing.Point(24, 84)
    $PathTextBox.Size = New-Object System.Drawing.Size(462, 25)
    $PathTextBox.Text = $InitialPoe2Dir
    $Form.Controls.Add($PathTextBox)

    $BrowseButton = New-Object System.Windows.Forms.Button
    $BrowseButton.Text = "浏览..."
    $BrowseButton.Location = New-Object System.Drawing.Point(500, 82)
    $BrowseButton.Size = New-Object System.Drawing.Size(96, 28)
    $Form.Controls.Add($BrowseButton)

    $StatusLabel = New-Object System.Windows.Forms.Label
    $StatusLabel.Location = New-Object System.Drawing.Point(24, 120)
    $StatusLabel.Size = New-Object System.Drawing.Size(572, 44)
    $StatusLabel.AutoEllipsis = $true
    $Form.Controls.Add($StatusLabel)

    $WarningLabel = New-Object System.Windows.Forms.Label
    $WarningLabel.Text = "电脑上有多个客户端时，请使用手动选择，避免更新或还原到错误目录。"
    $WarningLabel.Location = New-Object System.Drawing.Point(24, 170)
    $WarningLabel.Size = New-Object System.Drawing.Size(572, 22)
    $WarningLabel.ForeColor = [System.Drawing.Color]::DarkOrange
    $Form.Controls.Add($WarningLabel)

    $ConfirmButton = New-Object System.Windows.Forms.Button
    $ConfirmButton.Text = "确定"
    $ConfirmButton.Location = New-Object System.Drawing.Point(396, 218)
    $ConfirmButton.Size = New-Object System.Drawing.Size(96, 30)
    $Form.Controls.Add($ConfirmButton)

    $CancelButton = New-Object System.Windows.Forms.Button
    $CancelButton.Text = "取消"
    $CancelButton.Location = New-Object System.Drawing.Point(500, 218)
    $CancelButton.Size = New-Object System.Drawing.Size(96, 30)
    $CancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $Form.Controls.Add($CancelButton)
    $Form.AcceptButton = $ConfirmButton
    $Form.CancelButton = $CancelButton

    $SetStatus = {
        param([string]$Text, [bool]$IsError)
        $StatusLabel.Text = $Text
        $StatusLabel.ForeColor = if ($IsError) { [System.Drawing.Color]::Firebrick } else { [System.Drawing.Color]::DarkGreen }
    }

    $RefreshAuto = {
        try {
            $DetectedPath = Resolve-Poe2GameDirectorySelection -Mode "auto" -PreferredRoot $PreferredRoot
            $AutoRadio.Tag = $DetectedPath
            $PathTextBox.Text = $DetectedPath
            $InstallInfo = Get-Poe2InstallInfo -Poe2Dir $DetectedPath
            & $SetStatus "已自动识别：$($InstallInfo.DisplayName)" $false
        }
        catch {
            $AutoRadio.Tag = $null
            $PathTextBox.Text = ""
            & $SetStatus $_.Exception.Message $true
        }
    }

    $RefreshManual = {
        $ResolvedPath = ConvertTo-Poe2GameDirectoryPath -Path $PathTextBox.Text
        if ([string]::IsNullOrWhiteSpace($ResolvedPath)) {
            & $SetStatus "请选择包含 Content.ggpk 或 Bundles2\_.index.bin 的游戏根目录。" $true
        }
        else {
            $InstallInfo = Get-Poe2InstallInfo -Poe2Dir $ResolvedPath
            & $SetStatus "有效游戏目录：$($InstallInfo.DisplayName)" $false
        }
    }

    $RefreshMode = {
        $IsManual = [bool]$ManualRadio.Checked
        $PathTextBox.Enabled = $IsManual
        $BrowseButton.Enabled = $IsManual
        if ($IsManual) {
            & $RefreshManual
        }
        else {
            & $RefreshAuto
        }
    }

    $AutoRadio.Add_CheckedChanged({
            if ($AutoRadio.Checked) {
                & $RefreshMode
            }
        })
    $ManualRadio.Add_CheckedChanged({
            if ($ManualRadio.Checked) {
                & $RefreshMode
            }
        })
    $PathTextBox.Add_TextChanged({
            if ($ManualRadio.Checked) {
                & $RefreshManual
            }
        })
    $BrowseButton.Add_Click({
            $FolderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $FolderDialog.Description = "选择 POE2 游戏根目录"
            $FolderDialog.ShowNewFolderButton = $false
            if (-not [string]::IsNullOrWhiteSpace($PathTextBox.Text) -and
                (Test-Path -LiteralPath $PathTextBox.Text -PathType Container)) {
                $FolderDialog.SelectedPath = $PathTextBox.Text
            }
            elseif (Test-Path -LiteralPath $PreferredRoot -PathType Container) {
                $FolderDialog.SelectedPath = $PreferredRoot
            }
            try {
                if ($FolderDialog.ShowDialog($Form) -eq [System.Windows.Forms.DialogResult]::OK) {
                    $ManualRadio.Checked = $true
                    $PathTextBox.Text = $FolderDialog.SelectedPath
                }
            }
            finally {
                $FolderDialog.Dispose()
            }
        })
    $ConfirmButton.Add_Click({
            try {
                $PathMode = if ($ManualRadio.Checked) { "manual" } else { "auto" }
                $SelectedPath = if ($PathMode -eq "manual") {
                    Resolve-Poe2GameDirectorySelection -Mode "manual" -ManualPath $PathTextBox.Text
                }
                else {
                    Resolve-Poe2GameDirectorySelection -Mode "auto" -PreferredRoot $PreferredRoot
                }
                $Form.Tag = [pscustomobject]@{
                    Poe2Dir  = $SelectedPath
                    PathMode = $PathMode
                }
                $Form.DialogResult = [System.Windows.Forms.DialogResult]::OK
                $Form.Close()
            }
            catch {
                [System.Windows.Forms.MessageBox]::Show(
                    $Form,
                    $_.Exception.Message,
                    "游戏目录无效",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                ) | Out-Null
            }
        })

    $AutoRadio.Checked = $true
    try {
        $Result = $Form.ShowDialog()
        $Selection = $Form.Tag
    }
    finally {
        $Form.Dispose()
    }
    if ($Result -ne [System.Windows.Forms.DialogResult]::OK -or $null -eq $Selection) {
        throw "已取消游戏目录选择。"
    }
    return $Selection
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

function Get-Poe2LanguageDisplayName {
    param([string]$Name)

    switch ($Name) {
        "English" { return "English" }
        "Traditional Chinese" { return "繁体中文" }
        "Simplified Chinese" { return "简体中文" }
        default { return $Name }
    }
}

function Get-Poe2DefaultLanguageInfo {
    param(
        [string]$LanguageCode = "zh-TW",
        [Parameter(Mandatory = $true)][string]$ReasonPrefix
    )

    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        $LanguageCode = "zh-TW"
    }

    $Fallback = Get-Poe2LanguageInfoFromCode -LanguageCode $LanguageCode
    $DisplayName = Get-Poe2LanguageDisplayName $Fallback.Name

    return [pscustomobject]@{
        Code          = $Fallback.Code
        Name          = $Fallback.Name
        Path          = $Fallback.Path
        Defaulted     = $true
        DefaultReason = "$ReasonPrefix，已回退到 $DisplayName。可通过 POE2_PATCH_LANGUAGE 手动指定语言。"
    }
}

function Get-Poe2LanguageInfoFromCode {
    param(
        [string]$LanguageCode,
        [string]$DefaultLanguageCode = "zh-TW"
    )

    $CodeText = ""
    if (-not [string]::IsNullOrWhiteSpace($LanguageCode)) {
        $CodeText = $LanguageCode.Trim()
    }
    $Code = $CodeText.ToLowerInvariant().Replace("_", "-")

    if ([string]::IsNullOrWhiteSpace($CodeText)) {
        return Get-Poe2DefaultLanguageInfo -LanguageCode $DefaultLanguageCode -ReasonPrefix "未读取到 POE2 语言配置"
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

    return Get-Poe2DefaultLanguageInfo -LanguageCode $DefaultLanguageCode -ReasonPrefix "无法识别 POE2 语言代码 '$CodeText'"
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

    $ConfigFiles = @(Get-ChildItem -LiteralPath $MyGames -File -Filter "poe2_production*_Config.ini" -ErrorAction SilentlyContinue)
    if (-not [string]::IsNullOrWhiteSpace($Poe2Dir) -and (Test-Path -LiteralPath $Poe2Dir -PathType Container)) {
        # A machine can have both the international and WeGame clients.  Do not
        # let a recently used China-client config select the language for an
        # international installation.  China installs force zh-CN later in
        # Get-Poe2InstallInfo, so preferring their matching config is harmless.
        $IsChinaInstall = Test-Poe2ChinaClient -Poe2Dir $Poe2Dir
        $ConfigFiles = @($ConfigFiles | Sort-Object @{
                    Expression = {
                        $LooksChina = $_.Name -match '(?i)(?:china|wegame|tencent|(?:^|[_-])cn(?:[_-]|$))'
                        if ($LooksChina -eq $IsChinaInstall) { 0 } else { 1 }
                    }
                }, @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true })
    }
    else {
        $ConfigFiles = @($ConfigFiles | Sort-Object LastWriteTimeUtc -Descending)
    }

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
    $DefaultLanguageCode = if ($IsChina) { "zh-CN" } else { "zh-TW" }
    $LanguageInfo = Get-Poe2LanguageInfoFromCode -LanguageCode $ConfigLanguage -DefaultLanguageCode $DefaultLanguageCode
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
    $InstallInfo = Get-Poe2InstallInfo -Poe2Dir $Poe2Dir

    return @{
        Bundles2Dir  = $Bundles2Dir
        IndexBin     = $IndexBin
        EnBaseItems  = "data/balance/baseitemtypes.datc64"
        TcBaseItems  = $InstallInfo.TcBaseItemsPath
        TcEndgameMaps = $InstallInfo.TcEndgameMapsPath
    }
}

function Get-Poe2Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $Sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($Sha.ComputeHash($Stream)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Sha.Dispose()
        $Stream.Dispose()
    }
}

function Get-Poe2TextSha256Hex {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return [System.BitConverter]::ToString($Sha.ComputeHash($Bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Sha.Dispose()
    }
}

function Initialize-Poe2ZipIntegrityType {
    if ($null -ne ("Poe2ZipIntegrity" -as [type])) {
        return
    }

    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;

public static class Poe2ZipIntegrity
{
    private const uint CentralDirectorySignature = 0x02014b50u;
    private const uint EndOfCentralDirectorySignature = 0x06054b50u;
    private const uint Zip64EndOfCentralDirectorySignature = 0x06064b50u;
    private const uint Zip64LocatorSignature = 0x07064b50u;
    private static readonly uint[] CrcTable = BuildCrcTable();

    private static uint[] BuildCrcTable()
    {
        uint[] table = new uint[256];
        for (uint i = 0; i < table.Length; i++)
        {
            uint value = i;
            for (int bit = 0; bit < 8; bit++)
                value = (value & 1u) != 0u ? 0xedb88320u ^ (value >> 1) : value >> 1;
            table[i] = value;
        }
        return table;
    }

    public static string ComputeFileCrc32(string path)
    {
        uint crc = 0xffffffffu;
        byte[] buffer = new byte[1024 * 1024];
        using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
            {
                for (int i = 0; i < read; i++)
                    crc = CrcTable[(crc ^ buffer[i]) & 0xffu] ^ (crc >> 8);
            }
        }
        return (~crc).ToString("x8");
    }

    public static string ComputeStreamIntegrity(Stream stream)
    {
        uint crc = 0xffffffffu;
        long length = 0;
        byte[] buffer = new byte[1024 * 1024];
        using (SHA256 sha = SHA256.Create())
        {
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
            {
                sha.TransformBlock(buffer, 0, read, buffer, 0);
                for (int i = 0; i < read; i++)
                    crc = CrcTable[(crc ^ buffer[i]) & 0xffu] ^ (crc >> 8);
                length += read;
            }
            sha.TransformFinalBlock(new byte[0], 0, 0);
            string hash = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            return (~crc).ToString("x8") + "|" + hash + "|" + length.ToString();
        }
    }

    public static Dictionary<string, string> ReadCentralDirectoryCrc32(string zipPath)
    {
        using (FileStream stream = new FileStream(zipPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (BinaryReader reader = new BinaryReader(stream, Encoding.UTF8, true))
        {
            long eocdOffset = FindEndOfCentralDirectory(stream);
            stream.Position = eocdOffset + 4;
            ushort diskNumber = reader.ReadUInt16();
            ushort centralDirectoryDisk = reader.ReadUInt16();
            reader.ReadUInt16();
            ulong entryCount = reader.ReadUInt16();
            uint centralDirectorySize32 = reader.ReadUInt32();
            ulong centralDirectoryOffset = reader.ReadUInt32();
            if (diskNumber != 0 || centralDirectoryDisk != 0)
                throw new InvalidDataException("Multi-disk ZIP archives are not supported.");

            if (entryCount == ushort.MaxValue || centralDirectorySize32 == uint.MaxValue || centralDirectoryOffset == uint.MaxValue)
            {
                if (eocdOffset < 20)
                    throw new InvalidDataException("ZIP64 locator is missing.");
                stream.Position = eocdOffset - 20;
                if (reader.ReadUInt32() != Zip64LocatorSignature)
                    throw new InvalidDataException("ZIP64 locator is invalid.");
                uint zip64Disk = reader.ReadUInt32();
                long zip64Offset = reader.ReadInt64();
                uint totalDisks = reader.ReadUInt32();
                if (zip64Disk != 0 || totalDisks != 1 || zip64Offset < 0)
                    throw new InvalidDataException("Multi-disk ZIP64 archives are not supported.");

                stream.Position = zip64Offset;
                if (reader.ReadUInt32() != Zip64EndOfCentralDirectorySignature)
                    throw new InvalidDataException("ZIP64 end-of-central-directory record is invalid.");
                reader.ReadUInt64();
                reader.ReadUInt16();
                reader.ReadUInt16();
                uint zip64DiskNumber = reader.ReadUInt32();
                uint zip64CentralDisk = reader.ReadUInt32();
                reader.ReadUInt64();
                entryCount = reader.ReadUInt64();
                reader.ReadUInt64();
                centralDirectoryOffset = reader.ReadUInt64();
                if (zip64DiskNumber != 0 || zip64CentralDisk != 0)
                    throw new InvalidDataException("Multi-disk ZIP64 archives are not supported.");
            }

            if (centralDirectoryOffset > (ulong)stream.Length || entryCount > int.MaxValue)
                throw new InvalidDataException("ZIP central directory points outside the archive.");
            stream.Position = (long)centralDirectoryOffset;
            Dictionary<string, string> result = new Dictionary<string, string>(StringComparer.Ordinal);
            for (ulong index = 0; index < entryCount; index++)
            {
                if (reader.ReadUInt32() != CentralDirectorySignature)
                    throw new InvalidDataException("ZIP central directory entry is invalid.");
                reader.ReadUInt16();
                reader.ReadUInt16();
                ushort flags = reader.ReadUInt16();
                reader.ReadUInt16();
                reader.ReadUInt16();
                reader.ReadUInt16();
                uint crc = reader.ReadUInt32();
                reader.ReadUInt32();
                reader.ReadUInt32();
                ushort nameLength = reader.ReadUInt16();
                ushort extraLength = reader.ReadUInt16();
                ushort commentLength = reader.ReadUInt16();
                reader.ReadUInt16();
                reader.ReadUInt16();
                reader.ReadUInt32();
                reader.ReadUInt32();
                byte[] nameBytes = reader.ReadBytes(nameLength);
                if (nameBytes.Length != nameLength)
                    throw new EndOfStreamException("ZIP entry name is truncated.");
                string name = ((flags & 0x0800) != 0 ? Encoding.UTF8 : Encoding.ASCII).GetString(nameBytes);
                if (result.ContainsKey(name))
                    throw new InvalidDataException("ZIP contains a duplicate entry: " + name);
                result.Add(name, crc.ToString("x8"));
                if (stream.Seek((long)extraLength + commentLength, SeekOrigin.Current) < 0)
                    throw new InvalidDataException("ZIP central directory entry is truncated.");
            }
            return result;
        }
    }

    private static long FindEndOfCentralDirectory(FileStream stream)
    {
        int searchLength = (int)Math.Min(stream.Length, 65557L);
        byte[] tail = new byte[searchLength];
        stream.Position = stream.Length - searchLength;
        int offset = 0;
        while (offset < tail.Length)
        {
            int read = stream.Read(tail, offset, tail.Length - offset);
            if (read == 0)
                throw new EndOfStreamException("ZIP end-of-central-directory search was truncated.");
            offset += read;
        }
        for (int i = tail.Length - 22; i >= 0; i--)
        {
            if (tail[i] == 0x50 && tail[i + 1] == 0x4b && tail[i + 2] == 0x05 && tail[i + 3] == 0x06)
                return stream.Length - searchLength + i;
        }
        throw new InvalidDataException("ZIP end-of-central-directory record was not found.");
    }
}
'@
}

function Get-Poe2ZipEntryCrc32Map {
    param([Parameter(Mandatory = $true)][string]$Path)

    Initialize-Poe2ZipIntegrityType
    return ,([Poe2ZipIntegrity]::ReadCentralDirectoryCrc32($Path))
}

function Get-Poe2FileCrc32Hex {
    param([Parameter(Mandatory = $true)][string]$Path)

    Initialize-Poe2ZipIntegrityType
    return [Poe2ZipIntegrity]::ComputeFileCrc32($Path)
}

function Get-Poe2ZipEntryStreamIntegrity {
    param([Parameter(Mandatory = $true)]$Entry)

    Initialize-Poe2ZipIntegrityType
    $Stream = $Entry.Open()
    try {
        $Parts = [Poe2ZipIntegrity]::ComputeStreamIntegrity($Stream).Split('|')
    }
    finally {
        $Stream.Dispose()
    }
    if ($Parts.Count -ne 3) {
        throw "无法计算 ZIP 条目完整性：$($Entry.FullName)"
    }
    return [pscustomobject]@{
        Crc32 = $Parts[0]
        Sha256 = $Parts[1]
        Length = [long]$Parts[2]
    }
}

function Set-Poe2LogicalRestoreManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)]$BaseItemsSignature,
        [string]$BaselineKind = "clean-game-files"
    )

    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
        throw "POE2 逻辑还原包不存在：$ZipPath"
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $ExpectedPaths = @(
        [string]$InstallInfo.TcBaseItemsPath,
        [string]$InstallInfo.TcWordsPath,
        [string]$InstallInfo.TcEndgameMapsPath
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Replace('\', '/') } | Select-Object -Unique

    $RestoreFiles = New-Object System.Collections.Generic.List[object]
    $ReadArchive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($EntryPath in $ExpectedPaths) {
            $Entry = $ReadArchive.GetEntry($EntryPath)
            if ($null -eq $Entry) {
                if ($EntryPath -eq ([string]$InstallInfo.TcBaseItemsPath).Replace('\', '/')) {
                    throw "POE2 逻辑还原包缺少 BaseItemTypes：$EntryPath"
                }
                continue
            }
            $Integrity = Get-Poe2ZipEntryStreamIntegrity -Entry $Entry
            $RestoreFiles.Add([pscustomobject][ordered]@{
                    path = $EntryPath
                    length = [long]$Integrity.Length
                    sha256 = ([string]$Integrity.Sha256).ToLowerInvariant()
                })
        }
    }
    finally {
        $ReadArchive.Dispose()
    }

    $Manifest = [ordered]@{
        kind = "poe2-price-patch-logical-restore"
        version = 2
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        baseline_kind = $BaselineKind
        game_version = "poe2"
        install_kind = [string]$InstallInfo.InstallKind
        mode = [string]$InstallInfo.Mode
        config_language = [string]$InstallInfo.ConfigLanguage
        baseitems_path = [string]$InstallInfo.TcBaseItemsPath
        words_path = [string]$InstallInfo.TcWordsPath
        endgamemaps_path = [string]$InstallInfo.TcEndgameMapsPath
        baseitems_signature = $BaseItemsSignature
        restore_files = $RestoreFiles.ToArray()
    }

    $Archive = [System.IO.Compression.ZipFile]::Open($ZipPath, [System.IO.Compression.ZipArchiveMode]::Update)
    try {
        $Existing = $Archive.GetEntry("poe2-restore-manifest.json")
        if ($null -ne $Existing) {
            $Existing.Delete()
        }
        $Entry = $Archive.CreateEntry("poe2-restore-manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
        $Writer = New-Object System.IO.StreamWriter($Entry.Open(), (New-Object System.Text.UTF8Encoding($false)))
        try {
            $Writer.Write(($Manifest | ConvertTo-Json -Depth 16))
        }
        finally {
            $Writer.Dispose()
        }
    }
    finally {
        $Archive.Dispose()
    }
    return $Manifest
}

function Assert-Poe2LogicalRestoreManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [switch]$AllowLegacyWithoutManifest
    )

    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
        throw "POE2 逻辑还原包不存在：$ZipPath"
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $ManifestEntry = $Archive.GetEntry("poe2-restore-manifest.json")
        if ($null -eq $ManifestEntry) {
            if ($AllowLegacyWithoutManifest) {
                return $null
            }
            throw "POE2 逻辑还原包缺少作用域 manifest，拒绝把未知客户端的备份写入当前游戏。"
        }
        $Reader = New-Object System.IO.StreamReader($ManifestEntry.Open(), [System.Text.Encoding]::UTF8)
        try {
            $Manifest = $Reader.ReadToEnd() | ConvertFrom-Json
        }
        finally {
            $Reader.Dispose()
        }
        if ([string]$Manifest.kind -ne "poe2-price-patch-logical-restore" -or [int]$Manifest.version -ne 2) {
            throw "POE2 逻辑还原包 manifest 类型或版本无效。"
        }
        foreach ($Scope in @(
                @("install_kind", [string]$InstallInfo.InstallKind),
                @("mode", [string]$InstallInfo.Mode),
                @("config_language", [string]$InstallInfo.ConfigLanguage),
                @("baseitems_path", [string]$InstallInfo.TcBaseItemsPath),
                @("words_path", [string]$InstallInfo.TcWordsPath),
                @("endgamemaps_path", [string]$InstallInfo.TcEndgameMapsPath)
            )) {
            $Property = [string]$Scope[0]
            $Expected = [string]$Scope[1]
            $Actual = [string]$Manifest.$Property
            if (-not $Actual.Equals($Expected, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "POE2 逻辑还原包作用域不匹配：$Property 为 $Actual，当前需要 $Expected。"
            }
        }

        $Allowed = @{}
        foreach ($Path in @(
                [string]$InstallInfo.TcBaseItemsPath,
                [string]$InstallInfo.TcWordsPath,
                [string]$InstallInfo.TcEndgameMapsPath
            )) {
            if (-not [string]::IsNullOrWhiteSpace($Path)) {
                $Allowed[$Path.Replace('\', '/').ToLowerInvariant()] = $true
            }
        }
        $Seen = @{}
        foreach ($Descriptor in @($Manifest.restore_files)) {
            $Path = ([string]$Descriptor.path).Replace('\', '/')
            $Key = $Path.ToLowerInvariant()
            if (-not $Allowed.ContainsKey($Key)) {
                throw "POE2 逻辑还原包 manifest 包含越界条目：$Path"
            }
            if ($Seen.ContainsKey($Key)) {
                throw "POE2 逻辑还原包 manifest 包含重复条目：$Path"
            }
            $Seen[$Key] = $true
            $Entry = $Archive.GetEntry($Path)
            if ($null -eq $Entry) {
                throw "POE2 逻辑还原包缺少 manifest 声明的文件：$Path"
            }
            $Integrity = Get-Poe2ZipEntryStreamIntegrity -Entry $Entry
            if ([long]$Descriptor.length -ne [long]$Integrity.Length -or
                -not ([string]$Descriptor.sha256).Equals([string]$Integrity.Sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "POE2 逻辑还原包完整性校验失败：$Path"
            }
        }
        $BaseKey = ([string]$InstallInfo.TcBaseItemsPath).Replace('\', '/').ToLowerInvariant()
        if (-not $Seen.ContainsKey($BaseKey)) {
            throw "POE2 逻辑还原包 manifest 未声明 BaseItemTypes。"
        }
        foreach ($Entry in @($Archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })) {
            if ([string]$Entry.FullName -eq "poe2-restore-manifest.json") {
                continue
            }
            $Key = ([string]$Entry.FullName).Replace('\', '/').ToLowerInvariant()
            if (-not $Seen.ContainsKey($Key)) {
                throw "POE2 逻辑还原包包含当前作用域之外的文件：$($Entry.FullName)"
            }
        }
        return $Manifest
    }
    finally {
        $Archive.Dispose()
    }
}

function Get-Poe2PhysicalBaseFingerprint {
    param([Parameter(Mandatory = $true)][string]$Poe2Dir)

    $GameRoot = (Resolve-Path -LiteralPath $Poe2Dir).Path
    $Bundles2Root = Join-Path $GameRoot "Bundles2"
    if (-not (Test-Path -LiteralPath $Bundles2Root -PathType Container)) {
        throw "无法读取 Bundles2 官方底板：目录不存在：$Bundles2Root"
    }

    $Executables = @(Get-ChildItem -LiteralPath $GameRoot -Filter "PathOfExile*.exe" -File -ErrorAction Stop | Sort-Object Name)
    $TopLevelBundles = @(Get-ChildItem -LiteralPath $Bundles2Root -Filter "*.bundle.bin" -File -ErrorAction Stop | Sort-Object Name)
    if ($Executables.Count -eq 0) {
        throw "无法确认官方底板：游戏根目录没有 PathOfExile*.exe。"
    }
    if ($TopLevelBundles.Count -eq 0) {
        throw "无法确认官方底板：Bundles2 顶层没有 *.bundle.bin。"
    }

    $Records = New-Object System.Collections.Generic.List[object]
    foreach ($File in $Executables) {
        $Records.Add([pscustomobject][ordered]@{
                path = $File.Name
                length = [long]$File.Length
                last_write_time_utc = $File.LastWriteTimeUtc.ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
            })
    }
    foreach ($File in $TopLevelBundles) {
        $Records.Add([pscustomobject][ordered]@{
                path = "Bundles2/$($File.Name)"
                length = [long]$File.Length
                last_write_time_utc = $File.LastWriteTimeUtc.ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
            })
    }

    $SortedRecords = @($Records | Sort-Object @{ Expression = { ([string]$_.path).ToLowerInvariant() } })
    $CanonicalLines = @($SortedRecords | ForEach-Object {
            "{0}|{1}|{2}" -f ([string]$_.path).ToLowerInvariant(), [long]$_.length, [string]$_.last_write_time_utc
        })
    $Canonical = [string]::Join("`n", $CanonicalLines)

    return [pscustomobject][ordered]@{
        version = 1
        algorithm = "path-length-last-write-time-utc-v1"
        files = $SortedRecords
        inventory_sha256 = Get-Poe2TextSha256Hex -Text $Canonical
    }
}

function Get-Poe2Bundles2MutationFingerprint {
    param([Parameter(Mandatory = $true)][string]$Bundles2Dir)

    $Root = (Resolve-Path -LiteralPath $Bundles2Dir).Path
    $RootPrefix = $Root.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    $Files = New-Object System.Collections.Generic.List[object]

    foreach ($Relative in @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")) {
        $Path = Join-Path $Root $Relative
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            $Files.Add((Get-Item -LiteralPath $Path -ErrorAction Stop))
        }
    }
    $LibDir = Join-Path $Root "LibGGPK3"
    if (Test-Path -LiteralPath $LibDir -PathType Container) {
        foreach ($File in @(Get-ChildItem -LiteralPath $LibDir -Recurse -File -ErrorAction Stop | Sort-Object FullName)) {
            $Files.Add($File)
        }
    }

    if (-not ($Files | Where-Object { $_.FullName.Equals((Join-Path $Root "_.index.bin"), [System.StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1)) {
        throw "无法确认 Bundles2 写入状态：_.index.bin 不存在。"
    }

    $Records = @($Files | ForEach-Object {
            $Relative = $_.FullName.Substring($RootPrefix.Length).Replace("\", "/")
            [pscustomobject][ordered]@{
                path = $Relative
                length = [long]$_.Length
                sha256 = Get-Poe2Sha256Hex -Path $_.FullName
            }
        } | Sort-Object @{ Expression = { ([string]$_.path).ToLowerInvariant() } })
    $Canonical = [string]::Join("`n", @($Records | ForEach-Object {
                "{0}|{1}|{2}" -f ([string]$_.path).ToLowerInvariant(), [long]$_.length, ([string]$_.sha256).ToLowerInvariant()
            }))
    return [pscustomobject][ordered]@{
        version = 1
        algorithm = "path-length-sha256-v1"
        files = $Records
        inventory_sha256 = Get-Poe2TextSha256Hex -Text $Canonical
    }
}

function Assert-Poe2Bundles2MutationFingerprintCurrent {
    param(
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Bundles2Dir
    )

    if ($null -eq $Expected -or [int]$Expected.version -ne 1 -or [string]$Expected.algorithm -ne "path-length-sha256-v1") {
        throw "真实还原包缺少可识别的 Bundles2 写入前状态指纹。"
    }
    $Current = Get-Poe2Bundles2MutationFingerprint -Bundles2Dir $Bundles2Dir
    if (@($Expected.files).Count -ne @($Current.files).Count) {
        throw "Bundles2 状态已并发变化：文件数量与本次写入准备时不同。请等待游戏平台更新完成并完全关闭游戏与启动器后重试。"
    }
    $ExpectedHash = [string]$Expected.inventory_sha256
    if ($ExpectedHash -notmatch '^[0-9a-fA-F]{64}$' -or -not $ExpectedHash.Equals([string]$Current.inventory_sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Bundles2 状态已并发变化：索引或 LibGGPK3 内容与本次写入准备时不同。请等待游戏平台更新完成并完全关闭游戏与启动器后重试。"
    }
    return $Current
}

function ConvertTo-Poe2UtcDateTimeOffset {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [string]$Name = "timestamp"
    )

    [System.DateTimeOffset]$Parsed = [System.DateTimeOffset]::MinValue
    $Ok = [System.DateTimeOffset]::TryParse(
        $Text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind,
        [ref]$Parsed
    )
    if (-not $Ok) {
        throw "无法解析真实还原包的 $Name：$Text"
    }
    return $Parsed.ToUniversalTime()
}

function Assert-Poe2PhysicalRestoreManifestCurrent {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$Poe2Dir,
        [int]$LegacyClockToleranceSeconds = 5
    )

    if ([string]$Manifest.kind -ne "poe2-price-patch-physical-restore") {
        throw "真实还原包 manifest kind 无效。"
    }

    try {
        $ManifestVersion = [int]$Manifest.version
    }
    catch {
        throw "真实还原包 manifest version 无法解析。"
    }
    $Current = Get-Poe2PhysicalBaseFingerprint -Poe2Dir $Poe2Dir

    if ($ManifestVersion -eq 2) {
        $Expected = $Manifest.base_fingerprint
        if ($null -eq $Expected -or [int]$Expected.version -ne 1) {
            throw "真实还原包 v2 缺少可识别的官方底板指纹。"
        }

        $ExpectedFiles = @($Expected.files)
        $CurrentFiles = @($Current.files)
        if ($ExpectedFiles.Count -ne $CurrentFiles.Count) {
            throw "真实还原包已过期：官方底板文件数量已变化（备份 $($ExpectedFiles.Count)，当前 $($CurrentFiles.Count)）。"
        }

        $CurrentByPath = @{}
        foreach ($File in $CurrentFiles) {
            $CurrentByPath[([string]$File.path).ToLowerInvariant()] = $File
        }
        $Seen = @{}
        foreach ($File in $ExpectedFiles) {
            $Relative = [string]$File.path
            if ([string]::IsNullOrWhiteSpace($Relative)) {
                throw "真实还原包 v2 的官方底板指纹包含空路径。"
            }
            $Key = $Relative.ToLowerInvariant()
            if ($Seen.ContainsKey($Key)) {
                throw "真实还原包 v2 的官方底板指纹包含重复路径：$Relative"
            }
            $Seen[$Key] = $true
            if (-not $CurrentByPath.ContainsKey($Key)) {
                throw "真实还原包已过期：官方底板文件已删除或改名：$Relative"
            }

            $CurrentFile = $CurrentByPath[$Key]
            try {
                $ExpectedLength = [long]$File.length
            }
            catch {
                throw "真实还原包 v2 的文件长度无法解析：$Relative"
            }
            if ($ExpectedLength -ne [long]$CurrentFile.length) {
                throw "真实还原包已过期：官方底板文件长度已变化：$Relative"
            }

            $ExpectedTime = ConvertTo-Poe2UtcDateTimeOffset -Text ([string]$File.last_write_time_utc) -Name "$Relative LastWriteTimeUtc"
            $CurrentTime = ConvertTo-Poe2UtcDateTimeOffset -Text ([string]$CurrentFile.last_write_time_utc) -Name "$Relative current LastWriteTimeUtc"
            if ($ExpectedTime.UtcDateTime.Ticks -ne $CurrentTime.UtcDateTime.Ticks) {
                throw "真实还原包已过期：官方底板文件时间已变化：$Relative"
            }
        }

        $ExpectedInventory = [string]$Expected.inventory_sha256
        if ($ExpectedInventory -notmatch '^[0-9a-fA-F]{64}$') {
            throw "真实还原包 v2 的官方底板组合指纹无效。"
        }
        if (-not $ExpectedInventory.Equals([string]$Current.inventory_sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "真实还原包已过期：官方底板组合指纹与当前游戏不一致。"
        }
        return $Current
    }

    if ($ManifestVersion -eq 1) {
        $CreatedAt = ConvertTo-Poe2UtcDateTimeOffset -Text ([string]$Manifest.created_at) -Name "created_at"
        if ($CreatedAt -gt [System.DateTimeOffset]::UtcNow.AddMinutes(5)) {
            throw "旧版真实还原包的 created_at 晚于当前时间，无法安全确认兼容性：$($CreatedAt.ToString('o'))。"
        }
        $LatestAllowed = $CreatedAt.AddSeconds([Math]::Max(0, $LegacyClockToleranceSeconds))
        foreach ($File in @($Current.files)) {
            $CurrentTime = ConvertTo-Poe2UtcDateTimeOffset -Text ([string]$File.last_write_time_utc) -Name "$($File.path) current LastWriteTimeUtc"
            if ($CurrentTime -gt $LatestAllowed) {
                throw "旧版真实还原包已过期：$($File.path) 的修改时间 $($CurrentTime.ToString('o')) 晚于备份创建时间 $($CreatedAt.ToString('o'))。"
            }
        }
        return $Current
    }

    throw "不支持的真实还原包 manifest version：$ManifestVersion"
}

function Assert-Poe2PhysicalRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Poe2Dir,
        [Parameter(Mandatory = $true)]$InstallInfo
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "真实还原包不存在：$Path"
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $CrcByName = Get-Poe2ZipEntryCrc32Map -Path $Path
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $ManifestEntry = $Archive.GetEntry("manifest.json")
        if ($null -eq $ManifestEntry) {
            throw "真实还原包缺少 manifest.json。"
        }

        $Reader = New-Object System.IO.StreamReader($ManifestEntry.Open(), [System.Text.Encoding]::UTF8)
        try {
            $ManifestText = $Reader.ReadToEnd()
        }
        finally {
            $Reader.Dispose()
        }
        try {
            $Manifest = $ManifestText | ConvertFrom-Json
        }
        catch {
            throw "真实还原包 manifest.json 无法解析：$($_.Exception.Message)"
        }

        if ([string]$Manifest.install_kind -ne [string]$InstallInfo.InstallKind) {
            throw "真实还原包属于 $($Manifest.install_kind)，当前安装为 $($InstallInfo.InstallKind)。"
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Manifest.target_path) -and [string]$Manifest.target_path -ne [string]$InstallInfo.TcBaseItemsPath) {
            throw "真实还原包目标为 $($Manifest.target_path)，当前目标为 $($InstallInfo.TcBaseItemsPath)。"
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Manifest.mode) -and [string]$Manifest.mode -ne "Bundles2") {
            throw "真实还原包模式无效：$($Manifest.mode)"
        }

        Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Poe2Dir | Out-Null

        $PhysicalEntries = @($Archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) -and $_.FullName -like "Bundles2/*" })
        $IndexEntry = @($PhysicalEntries | Where-Object { $_.FullName -eq "Bundles2/_.index.bin" })
        if ($IndexEntry.Count -ne 1 -or $IndexEntry[0].Length -le 1048576) {
            throw "真实还原包没有有效的 Bundles2/_.index.bin。"
        }

        $SeenEntries = @{}
        foreach ($Entry in $Archive.Entries) {
            if ([string]::IsNullOrEmpty($Entry.Name)) {
                continue
            }
            $Name = [string]$Entry.FullName
            if ($Name -ne "manifest.json" -and $Name -notmatch '^Bundles2/(?:_\.index\.bin|_\.index\.(?:high|low)\.bin|\.index\.dbg|LibGGPK3/.+)$') {
                throw "真实还原包包含不允许写入的条目：$Name"
            }
            $Key = $Name.ToLowerInvariant()
            if ($SeenEntries.ContainsKey($Key)) {
                throw "真实还原包包含重复条目：$Name"
            }
            $SeenEntries[$Key] = $true
            if (-not $CrcByName.ContainsKey($Name)) {
                throw "ZIP 中央目录缺少条目 CRC：$Name"
            }
        }

        try {
            $ManifestVersion = [int]$Manifest.version
        }
        catch {
            throw "真实还原包 manifest version 无法解析。"
        }
        $RestoreFileByPath = @{}
        if ($ManifestVersion -eq 2) {
            foreach ($Descriptor in @($Manifest.restore_files)) {
                $DescriptorPath = [string]$Descriptor.path
                if ([string]::IsNullOrWhiteSpace($DescriptorPath)) {
                    throw "真实还原包 v2 的 restore_files 包含空路径。"
                }
                $DescriptorKey = $DescriptorPath.ToLowerInvariant()
                if ($RestoreFileByPath.ContainsKey($DescriptorKey)) {
                    throw "真实还原包 v2 的 restore_files 包含重复路径：$DescriptorPath"
                }
                $RestoreFileByPath[$DescriptorKey] = $Descriptor
            }
            if ($RestoreFileByPath.Count -ne $PhysicalEntries.Count) {
                throw "真实还原包 v2 的 restore_files 与 ZIP 条目数量不一致。"
            }
        }

        foreach ($Entry in @($ManifestEntry) + $PhysicalEntries) {
            $Integrity = Get-Poe2ZipEntryStreamIntegrity -Entry $Entry
            $ExpectedCrc = [string]$CrcByName[[string]$Entry.FullName]
            if (-not $Integrity.Crc32.Equals($ExpectedCrc, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "真实还原包 CRC 校验失败：$($Entry.FullName)"
            }
            if ($Integrity.Length -ne [long]$Entry.Length) {
                throw "真实还原包解压长度校验失败：$($Entry.FullName)"
            }

            if ($ManifestVersion -eq 2 -and $Entry.FullName -ne "manifest.json") {
                $DescriptorKey = ([string]$Entry.FullName).ToLowerInvariant()
                if (-not $RestoreFileByPath.ContainsKey($DescriptorKey)) {
                    throw "真实还原包 v2 缺少条目描述：$($Entry.FullName)"
                }
                $Descriptor = $RestoreFileByPath[$DescriptorKey]
                try {
                    $ExpectedLength = [long]$Descriptor.length
                }
                catch {
                    throw "真实还原包 v2 的条目长度无法解析：$($Entry.FullName)"
                }
                if ($ExpectedLength -ne $Integrity.Length) {
                    throw "真实还原包 v2 的条目长度不匹配：$($Entry.FullName)"
                }
                $ExpectedSha = [string]$Descriptor.sha256
                if ($ExpectedSha -notmatch '^[0-9a-fA-F]{64}$' -or -not $Integrity.Sha256.Equals($ExpectedSha, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "真实还原包 v2 的条目 SHA256 校验失败：$($Entry.FullName)"
                }
                $DescriptorCrc = [string]$Descriptor.crc32
                if ($DescriptorCrc -notmatch '^[0-9a-fA-F]{8}$' -or -not $Integrity.Crc32.Equals($DescriptorCrc, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "真实还原包 v2 的条目 CRC32 校验失败：$($Entry.FullName)"
                }
            }
        }

        return $Manifest
    }
    finally {
        $Archive.Dispose()
    }
}

function Move-Poe2FileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $SourceFull = [System.IO.Path]::GetFullPath($Source)
    $DestinationFull = [System.IO.Path]::GetFullPath($Destination)
    $DestinationDir = Split-Path -Parent $DestinationFull
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    if (-not (Test-Path -LiteralPath $DestinationFull -PathType Leaf)) {
        [System.IO.File]::Move($SourceFull, $DestinationFull)
        return $DestinationFull
    }

    $SafetyBackup = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $DestinationFull), ".replace-backup-", [Guid]::NewGuid().ToString("N")))
    $FailedReplacement = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $DestinationFull), ".failed-replacement-", [Guid]::NewGuid().ToString("N")))
    $ReplaceSucceeded = $false
    $RollbackSucceeded = $false
    try {
        [System.IO.File]::Replace($SourceFull, $DestinationFull, $SafetyBackup, $true)
        $ReplaceSucceeded = $true
    }
    catch {
        $OriginalError = $_
        if (Test-Path -LiteralPath $SafetyBackup -PathType Leaf) {
            try {
                if (Test-Path -LiteralPath $DestinationFull -PathType Leaf) {
                    [System.IO.File]::Replace($SafetyBackup, $DestinationFull, $FailedReplacement, $true)
                }
                else {
                    [System.IO.File]::Move($SafetyBackup, $DestinationFull)
                }
                $RollbackSucceeded = $true
            }
            catch {
                throw "原子替换失败，自动恢复旧文件也失败。旧文件备份已保留：$SafetyBackup；目标：$DestinationFull；原始错误：$($OriginalError.Exception.Message)；恢复错误：$($_.Exception.Message)"
            }
        }
        elseif (-not (Test-Path -LiteralPath $DestinationFull -PathType Leaf)) {
            throw "原子替换失败，目标和安全备份均不存在。目标：$DestinationFull；原始错误：$($OriginalError.Exception.Message)"
        }
        throw $OriginalError
    }
    finally {
        if ($ReplaceSucceeded -or $RollbackSucceeded) {
            if (Test-Path -LiteralPath $SafetyBackup -PathType Leaf) {
                Remove-Item -LiteralPath $SafetyBackup -Force -ErrorAction SilentlyContinue
            }
            if (Test-Path -LiteralPath $FailedReplacement -PathType Leaf) {
                Remove-Item -LiteralPath $FailedReplacement -Force -ErrorAction SilentlyContinue
            }
        }
    }

    return $DestinationFull
}

function Copy-Poe2FileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $SourceFull = (Resolve-Path -LiteralPath $Source).Path
    $DestinationFull = [System.IO.Path]::GetFullPath($Destination)
    if ($SourceFull.Equals($DestinationFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $SourceFull
    }
    $DestinationDir = Split-Path -Parent $DestinationFull
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    $TempCopy = Join-Path $DestinationDir ([string]::Concat(".", (Split-Path -Leaf $DestinationFull), ".copy-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        [System.IO.File]::Copy($SourceFull, $TempCopy, $false)
        Move-Poe2FileAtomically -Source $TempCopy -Destination $DestinationFull | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempCopy -PathType Leaf) {
            Remove-Item -LiteralPath $TempCopy -Force -ErrorAction SilentlyContinue
        }
    }
    return (Resolve-Path -LiteralPath $DestinationFull).Path
}

function Assert-Poe2GameFilesAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Poe2Dir,
        [Parameter(Mandatory = $true)][string]$IndexPath,
        [int]$RetryCount = 5,
        [int]$RetryDelaySeconds = 2
    )

    $Attempts = [Math]::Max(1, $RetryCount)
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        $RunningGames = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
                $_.ProcessName -like "PathOfExile*"
            })
        if ($RunningGames.Count -gt 0) {
            if ($Attempt -ge $Attempts) {
                $Names = [string]::Join(", ", @($RunningGames | ForEach-Object { "$($_.ProcessName) (PID $($_.Id))" }))
                throw "检测到 POE2 游戏仍在运行，请完全关闭游戏后重试。进程：$Names"
            }
            Write-Host "检测到游戏仍在运行，等待关闭后自动重试（$Attempt/$Attempts）..." -ForegroundColor Yellow
            Start-Sleep -Seconds ([Math]::Max(1, $RetryDelaySeconds))
            continue
        }

        $Stream = $null
        try {
            $Stream = [System.IO.File]::Open(
                $IndexPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            return
        }
        catch {
            if ($Attempt -ge $Attempts) {
                throw "Bundles2 索引文件被占用或不可写，请关闭游戏并等待游戏平台更新完成后重试。路径：$IndexPath。$($_.Exception.Message)"
            }
            Write-Host "Bundles2 索引暂时被占用，等待后自动重试（$Attempt/$Attempts）..." -ForegroundColor Yellow
            Start-Sleep -Seconds ([Math]::Max(1, $RetryDelaySeconds))
        }
        finally {
            if ($null -ne $Stream) {
                $Stream.Dispose()
            }
        }
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
        [string]$ExpectedSha512 = "",
        [string]$ExpectedSha256 = "",
        [int]$Retries = 3,
        [int]$TimeoutSeconds = 120
    )

    if ([string]::IsNullOrWhiteSpace($ExpectedSha512) -and [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        throw "A pinned SHA512 or SHA256 checksum is required for runtime downloads."
    }

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
    catch {
    }

    for ($Attempt = 1; $Attempt -le $Retries; $Attempt++) {
        $TempFile = [string]::Concat($OutFile, ".download-", [Guid]::NewGuid().ToString("N"), ".tmp")
        try {
            Invoke-WebRequest -Uri $Url -OutFile $TempFile -UseBasicParsing -TimeoutSec ([Math]::Max(30, $TimeoutSeconds))
            if (-not (Test-ZipHeader $TempFile)) {
                throw "Downloaded file is not a valid runtime zip."
            }
            if (-not [string]::IsNullOrWhiteSpace($ExpectedSha512)) {
                $ActualSha512 = (Get-FileHash -LiteralPath $TempFile -Algorithm SHA512).Hash
                if (-not $ActualSha512.Equals($ExpectedSha512, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Downloaded runtime SHA512 does not match pinned release metadata."
                }
            }
            else {
                $ActualSha256 = (Get-FileHash -LiteralPath $TempFile -Algorithm SHA256).Hash
                if (-not $ActualSha256.Equals($ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Downloaded runtime SHA256 does not match pinned release metadata."
                }
            }
            Move-Poe2FileAtomically -Source $TempFile -Destination $OutFile | Out-Null
            return
        }
        catch {
            if ($Attempt -ge $Retries) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Min(10, $Attempt * 2))
        }
        finally {
            if (Test-Path -LiteralPath $TempFile -PathType Leaf) {
                Remove-Item -LiteralPath $TempFile -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Install-Poe2DotNetRuntimeArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$RuntimeDir
    )

    $ToolsDir = Split-Path -Parent $RuntimeDir
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $StageDir = Join-Path $ToolsDir ([string]::Concat(".dotnet-new-", [Guid]::NewGuid().ToString("N")))
    $BackupDir = Join-Path $ToolsDir ([string]::Concat(".dotnet-backup-", [Guid]::NewGuid().ToString("N")))
    try {
        New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $StageDir -Force
        $StagedDotnet = Join-Path $StageDir "dotnet.exe"
        if (-not (Test-DotNet8Runtime $StagedDotnet)) {
            throw "Extracted .NET runtime is not usable."
        }

        $OldMoved = $false
        try {
            if (Test-Path -LiteralPath $RuntimeDir -PathType Container) {
                [System.IO.Directory]::Move($RuntimeDir, $BackupDir)
                $OldMoved = $true
            }
            [System.IO.Directory]::Move($StageDir, $RuntimeDir)
        }
        catch {
            if ($OldMoved -and -not (Test-Path -LiteralPath $RuntimeDir) -and (Test-Path -LiteralPath $BackupDir -PathType Container)) {
                [System.IO.Directory]::Move($BackupDir, $RuntimeDir)
            }
            throw
        }
        if (Test-Path -LiteralPath $BackupDir -PathType Container) {
            Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        return (Join-Path $RuntimeDir "dotnet.exe")
    }
    finally {
        if (Test-Path -LiteralPath $StageDir -PathType Container) {
            Remove-Item -LiteralPath $StageDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Install-LocalDotNet8Runtime {
    param([string]$RepoRoot)

    $RuntimeVersions = @("8.0.28", "8.0.27")
    $RuntimeSha512 = @{
        "8.0.28" = "cc7c5006285e95340a7bc4321acb76b143ee8ca6fc7e7925758624381d61ffeaf65d5a7dad389404677666f8f936df17a136716a773912e4c42b0eae637c5797"
        "8.0.27" = "e31528b5452afdec4cdf78fb073e8693ed0c24a14f5b69065e7018f89eefc38e52fcfd4eed8255b5d58867aa850f66790fead5b66f0fab13a72bebf098e98937"
    }
    $DownloadDir = Join-Path $RepoRoot "tools\downloads"
    $RuntimeDir = Join-Path $RepoRoot "tools\dotnet-runtime"

    New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

    foreach ($RuntimeVersion in $RuntimeVersions) {
        $RuntimeFile = "dotnet-runtime-$RuntimeVersion-win-x64.zip"
        $ZipPath = Join-Path $DownloadDir $RuntimeFile
        $Sources = @(
            @{
                Name = "Microsoft CDN（国内网络可直连时使用）"
                Url = "https://dotnetcli.azureedge.net/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
                TimeoutSeconds = 180
            },
            @{
                Name = "Microsoft 官方源"
                Url = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$RuntimeVersion/$RuntimeFile"
                TimeoutSeconds = 180
            }
        )

        if (
            (Test-ZipHeader $ZipPath) -and
            (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA512).Hash.Equals($RuntimeSha512[$RuntimeVersion], [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            try {
                Write-Host "使用随发布包提供的 .NET $RuntimeVersion 离线修复包。" -ForegroundColor Cyan
                $LocalDotnet = Install-Poe2DotNetRuntimeArchive -ArchivePath $ZipPath -RuntimeDir $RuntimeDir
                Write-Host ".NET 8 runtime ready: $LocalDotnet" -ForegroundColor Green
                return $LocalDotnet
            }
            catch {
                Write-Warning "本地 .NET 修复包安装失败，将尝试网络备用源：$($_.Exception.Message)"
            }
        }

        foreach ($Source in $Sources) {
            try {
                Write-Host "Download .NET 8 runtime $RuntimeVersion`: $($Source.Name)"
                Invoke-DownloadWithRetry `
                    -Url $Source.Url `
                    -OutFile $ZipPath `
                    -ExpectedSha512 $RuntimeSha512[$RuntimeVersion] `
                    -Retries 2 `
                    -TimeoutSeconds ([int]$Source.TimeoutSeconds)

                $LocalDotnet = Install-Poe2DotNetRuntimeArchive -ArchivePath $ZipPath -RuntimeDir $RuntimeDir
                Write-Host ".NET 8 runtime ready: $LocalDotnet" -ForegroundColor Green
                return $LocalDotnet
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

function Get-Poe2PythonElevationMessage {
    return 'Python 无法以普通权限启动。当前 python.exe 很可能被勾选了以管理员身份运行，或存在兼容性提权垫片。请取消该勾选，不要把整个物价补丁提权。补丁会以普通权限调用捆绑的 poe_python.exe。'
}

function Test-Poe2PythonElevationFailure {
    param(
        [string]$Text = "",
        $ExitCode = $null,
        $Exception = $null
    )

    $Blob = @($Text, [string]$Exception)
    if ($null -ne $Exception -and $Exception.PSObject.Properties["InnerException"]) {
        $Blob += [string]$Exception.InnerException
    }
    $Joined = ($Blob -join "`n")
    if ($ExitCode -eq 740) {
        return $true
    }
    return ($Joined -match "requires elevation|requested operation requires elevation|ERROR_ELEVATION_REQUIRED|740")
}

function Get-Poe2BundledPython {
    param([string]$PythonDir)

    if ([string]::IsNullOrWhiteSpace($PythonDir) -or -not (Test-Path -LiteralPath $PythonDir -PathType Container)) {
        return ""
    }
    $Stock = Join-Path $PythonDir "python.exe"
    $Preferred = Join-Path $PythonDir "poe_python.exe"
    if ((Test-Path -LiteralPath $Stock -PathType Leaf) -and -not (Test-Path -LiteralPath $Preferred -PathType Leaf)) {
        try {
            Copy-Item -LiteralPath $Stock -Destination $Preferred -Force
        }
        catch {
            Write-Warning "Unable to create poe_python.exe: $($_.Exception.Message)"
        }
    }
    if (Test-Path -LiteralPath $Preferred -PathType Leaf) {
        return $Preferred
    }
    if (Test-Path -LiteralPath $Stock -PathType Leaf) {
        return $Stock
    }
    return ""
}

function Invoke-Poe2Python {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [string[]]$ArgumentList = @(),
        [switch]$Quiet
    )

    Set-Poe2PythonEnvironment
    $OldErrorActionPreference = $ErrorActionPreference
    $OldCompatLayer = $env:__COMPAT_LAYER
    $Lines = New-Object System.Collections.Generic.List[string]
    $ExitCode = 0
    try {
        $env:__COMPAT_LAYER = "RunAsInvoker"
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
    catch {
        $Lines.Add([string]$_)
        if (Test-Poe2PythonElevationFailure -Text ($Lines -join "`n") -Exception $_.Exception) {
            throw (Get-Poe2PythonElevationMessage)
        }
        throw
    }
    finally {
        $ErrorActionPreference = $OldErrorActionPreference
        if ($null -eq $OldCompatLayer) {
            Remove-Item Env:__COMPAT_LAYER -ErrorAction SilentlyContinue
        }
        else {
            $env:__COMPAT_LAYER = $OldCompatLayer
        }
    }

    $LineArray = @($Lines.ToArray())
    $Text = ($LineArray -join "`n")
    if (Test-Poe2PythonElevationFailure -Text $Text -ExitCode $ExitCode) {
        throw (Get-Poe2PythonElevationMessage)
    }

    return [pscustomobject]@{
        ExitCode = $ExitCode
        Lines    = $LineArray
        Text     = $Text
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

    $PythonVersion = "3.13.14"
    $PythonZipName = "python-$PythonVersion-embed-amd64.zip"
    $PythonZipSha256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"
    $DownloadDir = Join-Path $RepoRoot "tools\downloads"
    $PythonDir = Join-Path $RepoRoot "tools\python"
    $ZipPath = Join-Path $DownloadDir $PythonZipName

    New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

    $Sources = @(
        @{
            Name = "华为云镜像"
            Url = "https://mirrors.huaweicloud.com/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 90
        },
        @{
            Name = "阿里云镜像"
            Url = "https://mirrors.aliyun.com/python-release/windows/$PythonZipName"
            TimeoutSeconds = 90
        },
        @{
            Name = "南京大学镜像"
            Url = "https://mirrors.nju.edu.cn/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 90
        },
        @{
            Name = "Python 官方备用源"
            Url = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"
            TimeoutSeconds = 180
        }
    )

    foreach ($Source in $Sources) {
        $StageDir = ""
        try {
            Write-Host "Download Python runtime: $($Source.Name)"
            Invoke-DownloadWithRetry `
                -Url $Source.Url `
                -OutFile $ZipPath `
                -ExpectedSha256 $PythonZipSha256 `
                -Retries 2 `
                -TimeoutSeconds ([int]$Source.TimeoutSeconds)

            $ToolsDir = Split-Path -Parent $PythonDir
            $StageDir = Join-Path $ToolsDir ([string]::Concat(".python-new-", [Guid]::NewGuid().ToString("N")))
            $BackupDir = Join-Path $ToolsDir ([string]::Concat(".python-backup-", [Guid]::NewGuid().ToString("N")))
            New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
            Expand-Archive -LiteralPath $ZipPath -DestinationPath $StageDir -Force
            Set-Content -LiteralPath (Join-Path $StageDir "python313._pth") -Encoding ASCII -Value @(
                "python313.zip",
                "."
            )

            $StagedPython = Join-Path $StageDir "python.exe"
            if (-not (Test-Poe2PythonPackages $StagedPython)) {
                throw "Extracted Python runtime is not usable."
            }
            $StagedAlias = Join-Path $StageDir "poe_python.exe"
            Copy-Item -LiteralPath $StagedPython -Destination $StagedAlias -Force
            $OldMoved = $false
            try {
                if (Test-Path -LiteralPath $PythonDir -PathType Container) {
                    [System.IO.Directory]::Move($PythonDir, $BackupDir)
                    $OldMoved = $true
                }
                [System.IO.Directory]::Move($StageDir, $PythonDir)
            }
            catch {
                if ($OldMoved -and -not (Test-Path -LiteralPath $PythonDir) -and (Test-Path -LiteralPath $BackupDir -PathType Container)) {
                    [System.IO.Directory]::Move($BackupDir, $PythonDir)
                }
                throw
            }
            finally {
                if (Test-Path -LiteralPath $StageDir -PathType Container) {
                    Remove-Item -LiteralPath $StageDir -Recurse -Force -ErrorAction SilentlyContinue
                }
            }
            if (Test-Path -LiteralPath $BackupDir -PathType Container) {
                Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            $LocalPython = Get-Poe2BundledPython -PythonDir $PythonDir
            if ([string]::IsNullOrWhiteSpace($LocalPython)) {
                throw "Extracted Python runtime is missing."
            }
            Write-Host "Python runtime ready: $LocalPython" -ForegroundColor Green
            return $LocalPython
        }
        catch {
            Write-Warning "$($Source.Name) failed: $($_.Exception.Message)"
        }
        finally {
            if (-not [string]::IsNullOrWhiteSpace($StageDir) -and (Test-Path -LiteralPath $StageDir -PathType Container)) {
                Remove-Item -LiteralPath $StageDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    throw "Unable to prepare Python runtime. Please check your network and run again."
}

function Ensure-PythonRequests {
    param([string]$RepoRoot = "")

    Set-Poe2PythonEnvironment

    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $LocalPython = Get-Poe2BundledPython -PythonDir (Join-Path $RepoRoot "tools\python")
        if (-not [string]::IsNullOrWhiteSpace($LocalPython)) {
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
