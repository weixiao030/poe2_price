function New-PoePatchLeagueOption {
    param([string]$Value, [string]$Scout = "", [string]$Ninja = "", [string]$Season = "", [bool]$Current = $false)
    return [pscustomobject]@{
        Label = $Value; Value = $Value; ScoutLeague = $Scout; PoeNinjaLeague = $Ninja
        PoeCurrencySeason = $Season; IsCurrent = $Current; UseCurrentEndpoint = $false
        DiscoveryFallback = $false; DiscoveryMessage = ""; Order = 0
    }
}

function Invoke-PoePatchLeagueRequest {
    param([string]$Url, [int]$TimeoutSeconds)
    for ($Attempt = 0; $Attempt -lt 2; $Attempt++) {
        try {
            return Invoke-RestMethod -Uri $Url -Headers @{ "User-Agent" = "poe-price-patch" } `
                -TimeoutSec ([Math]::Max(2, [Math]::Min(10, $TimeoutSeconds))) -ErrorAction Stop
        }
        catch { if ($Attempt -eq 1) { throw } }
    }
}

function Get-PoePatchOnlineLeagueOptions {
    param([ValidateSet("poe1", "poe2")][string]$GameVersion, [switch]$China, [int]$TimeoutSeconds = 10)
    if ($China) {
        $Response = Invoke-PoePatchLeagueRequest -Url "https://poecurrency.top/api/season_list?version=$GameVersion" -TimeoutSeconds $TimeoutSeconds
        $Values = @($Response)
        $Seen = @{}
        $Index = 0
        foreach ($Value in $Values) {
            if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value)) { continue }
            $Value = $Value.Trim()
            if ($Seen.ContainsKey($Value)) { continue }
            $Seen[$Value] = $true
            $Option = New-PoePatchLeagueOption -Value $Value -Season $Value -Current ($Index -eq 0)
            $Option.Order = $Index++
            $Option
        }
        return
    }

    $Providers = if ($GameVersion -eq "poe1") { @("ninja", "scout") } else { @("scout", "ninja") }
    $HistoricalOptions = @()
    foreach ($Provider in $Providers) {
        try {
            $Options = New-Object System.Collections.Generic.List[object]
            if ($Provider -eq "scout") {
                $Realm = if ($GameVersion -eq "poe1") { "pc" } else { "poe2" }
                $Response = Invoke-PoePatchLeagueRequest -Url "https://api.poe2scout.com/$Realm/Leagues" -TimeoutSeconds $TimeoutSeconds
                $Rows = @($Response)
                foreach ($Wrapper in @("data", "leagues", "items")) {
                    if ($null -ne $Response.PSObject.Properties[$Wrapper]) { $Rows = @($Response.$Wrapper); break }
                }
            }
            else {
                $Response = Invoke-PoePatchLeagueRequest -Url "https://poe.ninja/$GameVersion/api/data/index-state" -TimeoutSeconds $TimeoutSeconds
                if ($null -eq $Response.economyLeagues) { throw "Ninja 赛季目录格式无效。" }
                $Rows = @($Response.economyLeagues) + @($Response.oldEconomyLeagues)
            }
            $Seen = @{}
            $Index = 0
            $LatestFound = $false
            foreach ($Row in $Rows) {
                if ($null -eq $Row) { continue }
                $Value = if ($Provider -eq "scout") { [string]$Row.Value } else { [string]$Row.name }
                if (-not $Value) { $Value = [string]$Row.Name }
                $Value = $Value.Trim()
                $Scout = if ($Provider -eq "scout") { [string]$Row.ShortName } else { "" }
                if (-not $Scout -and $Provider -eq "scout") { $Scout = [string]$Row.Slug }
                if (-not $Value -or ($Provider -eq "scout" -and -not $Scout)) { continue }
                $Hardcore = $Row.PSObject.Properties["IsHardcore"]
                if ($null -eq $Hardcore) { $Hardcore = $Row.PSObject.Properties["hardcore"] }
                $IsHardcore = if ($null -ne $Hardcore) { ConvertTo-PoePatchBoolean $Hardcore.Value } else { $Value -match '^(HC |Hardcore)' -or $Scout -match '(hc|hardcore)$' }
                if ($IsHardcore -or $Value -match '(?i)\b(SSF|Ruthless)\b' -or $Seen.ContainsKey($Value)) { continue }
                $Seen[$Value] = $true
                $Current = if ($Provider -eq "scout") { -not $LatestFound -and (ConvertTo-PoePatchBoolean $Row.IsCurrent) -and $Value -ne "Standard" } else {
                    -not $LatestFound -and $Value -ne "Standard" -and @($Response.economyLeagues | Where-Object { $_.name -eq $Value }).Count -gt 0
                }
                if ($Current) { $LatestFound = $true }
                $Option = New-PoePatchLeagueOption -Value $Value -Scout $Scout -Ninja $Value -Current $Current
                $Option.Order = $Index++
                $Options.Add($Option)
            }
            if ($Options.Count -eq 0) { throw "服务没有返回可用赛季。" }
            if (-not $LatestFound) {
                if ($HistoricalOptions.Count -eq 0) { $HistoricalOptions = @($Options.ToArray()) }
                continue
            }
            return @($Options | Sort-Object @{ Expression = { if ($_.IsCurrent) { 0 } else { 1 } } }, Order)
        }
        catch { $Failure = $_.Exception.Message }
    }
    if ($HistoricalOptions.Count -gt 0) { return $HistoricalOptions }
    throw "赛季目录暂不可用：$Failure"
}

function Get-PoePatchLeagueOptions {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("poe1", "poe2")][string]$GameVersion,
        [switch]$China, [int]$TimeoutSeconds = 10, [switch]$ForceRefresh, [string]$CacheDirectory = ""
    )
    if (-not $CacheDirectory) {
        $Root = if ($env:POE2_PATCH_ROOT) { $env:POE2_PATCH_ROOT } else { Split-Path -Parent $PSScriptRoot }
        $CacheDirectory = Join-Path $Root "output\league_catalog"
    }
    $Scope = "$GameVersion-$(if ($China) { 'china' } else { 'international' })"
    $CachePath = Join-Path $CacheDirectory "$Scope.json"
    $Cached = @()
    $Age = [double]::PositiveInfinity
    try {
        $Saved = Get-Content -LiteralPath $CachePath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        if ($Saved.Version -eq 1 -and $Saved.Scope -eq $Scope) {
            $Age = ([DateTime]::UtcNow - [DateTime]::Parse($Saved.SavedAt).ToUniversalTime()).TotalSeconds
            if ($Age -ge 0 -and $Age -le 7 * 86400) {
                $Cached = @($Saved.Options | ForEach-Object {
                    if ($_.Value -isnot [string] -or -not $_.Value -or $_.IsCurrent -isnot [bool]) { return }
                    if ($_.ScoutLeague -isnot [string] -or $_.PoeNinjaLeague -isnot [string] -or $_.PoeCurrencySeason -isnot [string]) { return }
                    if ($(if ($China) { $_.PoeCurrencySeason -ne $_.Value } else { $_.PoeNinjaLeague -ne $_.Value })) { return }
                    $Option = New-PoePatchLeagueOption -Value $_.Value -Scout $_.ScoutLeague -Ninja $_.PoeNinjaLeague -Season $_.PoeCurrencySeason -Current $_.IsCurrent
                    if ($_.Label -is [string] -and $_.Label) { $Option.Label = $_.Label }
                    $Option
                })
                # A partially damaged list cannot identify the first/current season safely.
                if ($Cached.Count -ne @($Saved.Options).Count) { $Cached = @() }
            }
        }
    }
    catch { $Cached = @() }
    if (-not $ForceRefresh -and $Cached.Count -gt 0 -and $Age -lt 300) { return $Cached }
    try {
        $Options = @(Get-PoePatchOnlineLeagueOptions -GameVersion $GameVersion -China:$China -TimeoutSeconds $TimeoutSeconds)
        if ($Options.Count -eq 0) { throw "服务返回空赛季目录。" }
        $LatestLabeled = $false
        foreach ($Option in $Options) {
            if ($Option.IsCurrent -and -not $LatestLabeled) {
                $Option.Label = "$($Option.Value)（最新）"
                $LatestLabeled = $true
            }
            # Only reuse a provider ID for an exact same-league match.
            if (-not $China -and -not $Option.ScoutLeague) {
                $Previous = @($Cached | Where-Object { $_.Value -eq $Option.Value })
                if ($Previous.Count -eq 1) { $Option.ScoutLeague = [string]$Previous[0].ScoutLeague }
            }
        }
        try {
            New-Item -ItemType Directory -Path $CacheDirectory -Force -ErrorAction Stop | Out-Null
            $Temporary = "$CachePath.$([Guid]::NewGuid().ToString('N')).tmp"
            $Content = @{ Version = 1; Scope = $Scope; SavedAt = [DateTime]::UtcNow.ToString('o'); Options = $Options } | ConvertTo-Json -Depth 8
            [IO.File]::WriteAllText($Temporary, $Content, (New-Object Text.UTF8Encoding($false)))
            Move-Poe2FileAtomically -Source $Temporary -Destination $CachePath | Out-Null
        }
        catch { Write-Verbose "无法缓存赛季目录：$($_.Exception.Message)" }
        return $Options
    }
    catch {
        if ($Cached.Count -eq 0) { throw }
        foreach ($Option in $Cached) {
            $Option.DiscoveryFallback = $true
            $Option.DiscoveryMessage = "赛季列表刷新失败，已使用上次获取的赛季。"
        }
        return $Cached
    }
}

function Get-PoePatchChinaSummaryUrl {
    param([ValidateSet("poe1", "poe2")][string]$GameVersion, [string]$Season, [bool]$UseCurrentEndpoint)
    $Version = if ($GameVersion -eq "poe1") { "1" } else { "2" }
    $Url = "https://poecurrency.top/api/summary?version=$Version"
    if (-not $UseCurrentEndpoint) {
        if (-not $Season) { throw "历史赛季标识不能为空。" }
        $Url += "&season=$([Uri]::EscapeDataString($Season))"
    }
    return $Url
}

function Resolve-PoePatchLeagueSelection {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("poe1", "poe2")][string]$GameVersion,
        [string]$League = "", [string]$PoeNinjaLeague = "", [string]$PoeCurrencySeason = "",
        [ValidateSet("", "auto", "fixed")][string]$LeagueMode = "", [bool]$LeagueIsCurrent = $false,
        [switch]$China, [int]$TimeoutSeconds = 10, [string]$CacheDirectory = ""
    )
    if (-not $LeagueMode) { $LeagueMode = if ($League -or $PoeNinjaLeague -or $PoeCurrencySeason) { "fixed" } else { "auto" } }
    if (-not $China -and $LeagueMode -eq "fixed") {
        if ($GameVersion -eq "poe1") { $PoeNinjaLeague = $League; $League = "" }
        if (-not $League -and -not $PoeNinjaLeague) { throw "请选择价格赛季。" }
        $Value = if ($PoeNinjaLeague) { $PoeNinjaLeague } else { $League }
        return New-PoePatchLeagueOption -Value $Value -Scout $League -Ninja $PoeNinjaLeague -Current $LeagueIsCurrent
    }
    $Arguments = @{ GameVersion = $GameVersion; TimeoutSeconds = $TimeoutSeconds; CacheDirectory = $CacheDirectory }
    try { $Options = @(Get-PoePatchLeagueOptions @Arguments -China:$China) }
    catch {
        if (-not $China) { throw }
        $Options = @()
    }
    if (-not $China) {
        $Current = @($Options | Where-Object { $_.IsCurrent })
        if ($Current.Count -eq 0) { throw "当前赛季尚未公布，请稍后重试；现有补丁保持不变。" }
        return $Current[0]
    }

    if ($LeagueMode -eq "auto") {
        # An unidentified live CN season must never be cached under an old season's name.
        $Selected = if ($Options.Count -gt 0 -and $Options[0].IsCurrent -and -not $Options[0].DiscoveryFallback) { $Options[0] } else {
            New-PoePatchLeagueOption -Value "" -Current $true
        }
        $Selected.UseCurrentEndpoint = $true
    }
    else {
        $Season = if ($PoeCurrencySeason) { $PoeCurrencySeason } else { $League }
        if (-not $Season) { throw "请选择国服价格赛季。" }
        $Matches = @($Options | Where-Object { $_.PoeCurrencySeason -eq $Season })
        $Selected = if ($Matches.Count -eq 1) { $Matches[0] } else { New-PoePatchLeagueOption -Value $Season -Season $Season }
        $Selected.UseCurrentEndpoint = $Selected.IsCurrent -and -not $Selected.DiscoveryFallback
    }
    $Selected.ScoutLeague = ""
    $Selected.PoeNinjaLeague = ""
    if ($Selected.PoeCurrencySeason) {
        try {
            $International = @(Get-PoePatchLeagueOptions @Arguments)
            $SeasonKey = ($Selected.PoeCurrencySeason -replace '[^a-zA-Z0-9]', '').ToLowerInvariant()
            $References = @($International | Where-Object {
                (($_.Value -replace '[^a-zA-Z0-9]', '').ToLowerInvariant() -eq $SeasonKey) -or
                (($_.ScoutLeague -replace '[^a-zA-Z0-9]', '').ToLowerInvariant() -eq $SeasonKey)
            })
            if ($References.Count -eq 0 -and $Selected.UseCurrentEndpoint) {
                $References = @($International | Where-Object { $_.IsCurrent -and -not $_.DiscoveryFallback } | Select-Object -First 1)
            }
            if ($References.Count -eq 1) {
                $Selected.ScoutLeague = [string]$References[0].ScoutLeague
                $Selected.PoeNinjaLeague = [string]$References[0].PoeNinjaLeague
            }
        }
        catch { Write-Verbose "国际服参考赛季暂不可用：$($_.Exception.Message)" }
    }
    return $Selected
}
