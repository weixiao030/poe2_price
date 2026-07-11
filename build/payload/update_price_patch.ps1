param(
    [string]$Poe2Dir = "",
    [switch]$SkipExtract,
    [switch]$NoOpenTool,
    [switch]$NoInstall,
    [switch]$NoPoe2dbFallback,
    [switch]$IslandRumourHints,
    [ValidateSet("", "all", "currency", "uniques", "none")]
    [string]$PatchScope = ""
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
$script:PatchScopeDialogSelection = $null
$script:PatchVersion = "v0.4.9.5"
$script:PatchWindowTitle = "POE2 Price Patch $script:PatchVersion"

if ([string]::IsNullOrWhiteSpace($Poe2Dir)) {
    $Poe2Dir = (Split-Path -Parent $RepoRoot)
}
$Poe2Dir = (Resolve-Path -LiteralPath $Poe2Dir).Path

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function New-Utf16Text {
    param([Parameter(Mandatory = $true)][int[]]$CodePoints)
    return [string]::Concat(($CodePoints | ForEach-Object { [char]$_ }))
}

function Get-PatchScopeDisplayName {
    param([string]$Scope)

    switch ($Scope) {
        "currency" { return (New-Utf16Text @(0x53EA, 0x6253, 0x901A, 0x8D27, 0x8865, 0x4E01)) }
        "uniques" { return (New-Utf16Text @(0x53EA, 0x6253, 0x4F20, 0x5947, 0x88C5, 0x5907, 0x8865, 0x4E01)) }
        "none" { return (New-Utf16Text @(0x4EC5, 0x5C9B, 0x5C7F, 0x4F20, 0x8A00, 0x8865, 0x4E01)) }
        default { return (New-Utf16Text @(0x901A, 0x8D27, 0x0020, 0x002B, 0x0020, 0x4F20, 0x5947, 0x88C5, 0x5907)) }
    }
}

function Show-PatchScopeDialog {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $Form = New-Object System.Windows.Forms.Form
    $Form.Text = $script:PatchWindowTitle
    $Form.StartPosition = "CenterScreen"
    $Form.FormBorderStyle = "FixedDialog"
    $Form.MaximizeBox = $false
    $Form.MinimizeBox = $false
    $Form.TopMost = $true
    $Form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
    $Form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::None
    $Form.ClientSize = New-Object System.Drawing.Size(610, 340)

    $Title = New-Object System.Windows.Forms.Label
    $Title.Text = (New-Utf16Text @(0x9009, 0x62E9, 0x672C, 0x6B21, 0x8981, 0x5199, 0x5165, 0x7684, 0x8865, 0x4E01, 0x5185, 0x5BB9))
    $Title.AutoSize = $true
    $Title.Location = New-Object System.Drawing.Point(24, 22)
    $Title.Font = New-Object System.Drawing.Font($Form.Font.FontFamily, 11, [System.Drawing.FontStyle]::Bold)
    $Form.Controls.Add($Title)

    $Group = New-Object System.Windows.Forms.GroupBox
    $Group.Text = (New-Utf16Text @(0x8865, 0x4E01, 0x5185, 0x5BB9))
    $Group.Location = New-Object System.Drawing.Point(24, 60)
    $Group.Size = New-Object System.Drawing.Size(572, 132)
    $Form.Controls.Add($Group)

    $CurrencyCheck = New-Object System.Windows.Forms.CheckBox
    $CurrencyCheck.Text = (New-Utf16Text @(0x901A, 0x8D27, 0x4EF7, 0x683C, 0x8865, 0x4E01))
    $CurrencyCheck.Tag = "currency-price"
    $CurrencyCheck.Checked = $true
    $CurrencyCheck.Location = New-Object System.Drawing.Point(22, 30)
    $CurrencyCheck.AutoSize = $true
    $Group.Controls.Add($CurrencyCheck)

    $UniqueCheck = New-Object System.Windows.Forms.CheckBox
    $UniqueCheck.Text = (New-Utf16Text @(0x4F20, 0x5947, 0x88C5, 0x5907, 0x4EF7, 0x683C, 0x8865, 0x4E01))
    $UniqueCheck.Tag = "unique-price"
    $UniqueCheck.Checked = $true
    $UniqueCheck.Location = New-Object System.Drawing.Point(22, 62)
    $UniqueCheck.AutoSize = $true
    $Group.Controls.Add($UniqueCheck)

    $IslandRumourCheck = New-Object System.Windows.Forms.CheckBox
    $IslandRumourCheck.Text = (New-Utf16Text @(0x5C9B, 0x5C7F, 0x4F20, 0x8A00, 0x8865, 0x4E01))
    $IslandRumourCheck.Tag = "island-rumour-hints"
    $IslandRumourCheck.Checked = $true
    $IslandRumourCheck.Location = New-Object System.Drawing.Point(22, 94)
    $IslandRumourCheck.AutoSize = $true
    $Group.Controls.Add($IslandRumourCheck)

    $OpenLink = {
        param($Sender, $EventArgs)

        $Url = [string]$Sender.Tag
        try {
            Start-Process -FilePath $Url
        }
        catch {
            [System.Windows.Forms.Clipboard]::SetText($Url)
            [System.Windows.Forms.MessageBox]::Show(
                "无法打开链接，已复制到剪贴板：`n$Url",
                "更新地址"
            ) | Out-Null
        }
    }

    $LinksGroup = New-Object System.Windows.Forms.GroupBox
    $LinksGroup.Text = "更新地址"
    $LinksGroup.Location = New-Object System.Drawing.Point(24, 208)
    $LinksGroup.Size = New-Object System.Drawing.Size(572, 72)
    $Form.Controls.Add($LinksGroup)

    $GitHubCaption = New-Object System.Windows.Forms.Label
    $GitHubCaption.Text = "GitHub:"
    $GitHubCaption.Location = New-Object System.Drawing.Point(18, 29)
    $GitHubCaption.AutoSize = $true
    $LinksGroup.Controls.Add($GitHubCaption)

    $GitHubLink = New-Object System.Windows.Forms.LinkLabel
    $GitHubLink.Text = "weixiao030/poe2_price"
    $GitHubLink.Tag = "https://github.com/weixiao030/poe2_price"
    $GitHubLink.Location = New-Object System.Drawing.Point(86, 26)
    $GitHubLink.AutoSize = $true
    $GitHubLink.Add_LinkClicked($OpenLink)
    $LinksGroup.Controls.Add($GitHubLink)

    $CaimoguCaption = New-Object System.Windows.Forms.Label
    $CaimoguCaption.Text = (New-Utf16Text @(0x8E29, 0x8611, 0x83C7, 0x003A))
    $CaimoguCaption.Location = New-Object System.Drawing.Point(18, 53)
    $CaimoguCaption.AutoSize = $true
    $LinksGroup.Controls.Add($CaimoguCaption)

    $CaimoguLink = New-Object System.Windows.Forms.LinkLabel
    $CaimoguLink.Text = "caimogu.cc/post/2403703.html"
    $CaimoguLink.Tag = "https://www.caimogu.cc/post/2403703.html"
    $CaimoguLink.Location = New-Object System.Drawing.Point(86, 50)
    $CaimoguLink.AutoSize = $true
    $CaimoguLink.Add_LinkClicked($OpenLink)
    $LinksGroup.Controls.Add($CaimoguLink)

    $OkButton = New-Object System.Windows.Forms.Button
    $OkButton.Text = (New-Utf16Text @(0x5F00, 0x59CB, 0x66F4, 0x65B0))
    $OkButton.Location = New-Object System.Drawing.Point(390, 292)
    $OkButton.Size = New-Object System.Drawing.Size(96, 32)
    $Form.AcceptButton = $OkButton
    $Form.Controls.Add($OkButton)

    $CancelButton = New-Object System.Windows.Forms.Button
    $CancelButton.Text = (New-Utf16Text @(0x53D6, 0x6D88))
    $CancelButton.Location = New-Object System.Drawing.Point(500, 292)
    $CancelButton.Size = New-Object System.Drawing.Size(96, 32)
    $CancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $Form.CancelButton = $CancelButton
    $Form.Controls.Add($CancelButton)

    $OkButton.Add_Click({
            if (-not ($CurrencyCheck.Checked -or $UniqueCheck.Checked -or $IslandRumourCheck.Checked)) {
                [System.Windows.Forms.MessageBox]::Show(
                    (New-Utf16Text @(0x8BF7, 0x81F3, 0x5C11, 0x9009, 0x62E9, 0x4E00, 0x4E2A, 0x8865, 0x4E01, 0x5185, 0x5BB9)),
                    $script:PatchWindowTitle
                ) | Out-Null
                return
            }
            $Form.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $Form.Close()
        })

    $Result = $Form.ShowDialog()
    if ($Result -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Patch scope selection was cancelled."
    }

    if ($CurrencyCheck.Checked -and $UniqueCheck.Checked) {
        $Scope = "all"
    }
    elseif ($CurrencyCheck.Checked) {
        $Scope = "currency"
    }
    elseif ($UniqueCheck.Checked) {
        $Scope = "uniques"
    }
    else {
        $Scope = "none"
    }
    return [pscustomobject]@{
        Scope              = $Scope
        CurrencyPrices     = [bool]$CurrencyCheck.Checked
        UniquePrices       = [bool]$UniqueCheck.Checked
        IslandRumourHints  = [bool]$IslandRumourCheck.Checked
    }
}

function Resolve-PatchScope {
    param([string]$Requested)

    $Allowed = @("all", "currency", "uniques", "none")
    $Scope = $Requested
    if ([string]::IsNullOrWhiteSpace($Scope) -and -not [string]::IsNullOrWhiteSpace($env:POE2_PATCH_SCOPE)) {
        $Scope = $env:POE2_PATCH_SCOPE.Trim().ToLowerInvariant()
    }
    if (-not [string]::IsNullOrWhiteSpace($Scope)) {
        $Scope = $Scope.Trim().ToLowerInvariant()
        if ($Scope -notin $Allowed) {
            throw "Invalid POE2_PATCH_SCOPE '$Scope'. Use all, currency or uniques."
        }
        return $Scope
    }
    if (Test-Poe2ReleaseMode) {
        try {
            $Selection = Show-PatchScopeDialog
            $script:PatchScopeDialogSelection = $Selection
            return [string]$Selection.Scope
        }
        catch {
            if ($_.Exception.Message -eq "Patch scope selection was cancelled.") {
                throw
            }
            Write-Warning "Patch scope dialog failed; falling back to all: $($_.Exception.Message)"
        }
    }
    return "all"
}

function Resolve-IslandRumourHints {
    param([switch]$Requested)

    if ($Requested.IsPresent) {
        return $true
    }
    if (-not [string]::IsNullOrWhiteSpace($env:POE2_PATCH_ISLAND_RUMOUR_HINTS)) {
        $Value = $env:POE2_PATCH_ISLAND_RUMOUR_HINTS.Trim().ToLowerInvariant()
        if ($Value -in @("1", "true", "yes", "on")) {
            return $true
        }
        if ($Value -in @("0", "false", "no", "off")) {
            return $false
        }
        throw "Invalid POE2_PATCH_ISLAND_RUMOUR_HINTS '$($env:POE2_PATCH_ISLAND_RUMOUR_HINTS)'. Use 1 or 0."
    }
    if ($null -ne $script:PatchScopeDialogSelection) {
        return [bool]$script:PatchScopeDialogSelection.IslandRumourHints
    }
    return $false
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
        "^(.+) EndgameMaps$" { return "$(Get-DisplayLanguageName $Matches[1]) EndgameMaps.datc64" }
        "^EndgameMaps$" { return "EndgameMaps.datc64" }
        "^UniqueGoldPrices$" { return "UniqueGoldPrices.datc64" }
        "BaseItemTypes" { return "$Name.datc64" }
        "^Content\.ggpk$" { return "游戏数据文件 Content.ggpk" }
        "^GGPKExtractor$" { return "GGPK 提取工具" }
        "^vcruntime140\.dll$" { return "VC++ 运行库 vcruntime140.dll" }
        "^vcruntime140_1\.dll$" { return "VC++ 运行库 vcruntime140_1.dll" }
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

    if ($Message -match '^GGPKExtractor failed\. Exit code: (.+?)\. Log: (.+)$') {
        return New-FailureMessage `
            -Reason "从 Content.ggpk 提取游戏数据失败。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @(
                "GGPK 提取工具退出码：$($Matches[1])",
                "提取日志：$($Matches[2])"
            )
    }

    if ($Message -match '^GGPKExtractor did not refresh required file: (.+?)\. Log: (.+)$') {
        $Name = Get-FriendlyFileName $Matches[1]
        return New-FailureMessage `
            -Reason "从 Content.ggpk 提取后没有刷新必要文件：$Name" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("提取日志：$($Matches[2])")
    }

    if ($Message -match '^GGPKExtractor exit code: (.+)$') {
        return New-FailureMessage `
            -Reason "从 Content.ggpk 提取游戏数据失败。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("GGPK 提取工具退出码：$($Matches[1])")
    }

    if ($Message -match '^GGPKExtractor missing VC runtime dependency\. Exit code: (.+?)\. Log: (.+)$') {
        return New-FailureMessage `
            -Reason "GGPK 提取工具启动失败，缺少 VC++ 运行库依赖。" `
            -Suggestions (Get-GgpkExtractorFailureSuggestions) `
            -Details @(
                "GGPK 提取工具退出码：$($Matches[1])",
                "提取日志：$($Matches[2])"
            )
    }

    if ($Message -match '^Failed to extract (.+?)\. Exit code: (.+)$') {
        $Name = Get-FriendlyFileName $Matches[1]
        return New-FailureMessage `
            -Reason "提取 $Name 失败。" `
            -Suggestions (Get-BaseItemsFailureSuggestions) `
            -Details @("提取工具退出码：$($Matches[2])")
    }

    if ($Message -match '^Price fetch or patch build failed\. Exit code: (.+?)\. Log: (.+)$') {
        return New-FailureMessage `
            -Reason "获取价格或生成补丁失败。" `
            -Suggestions @(
                "请检查网络是否能访问当前价格源。",
                "如果是临时网络问题，稍后重新运行一键更新即可。",
                "如果仍然失败，把下方构建日志一起发给作者排查。"
            ) `
            -Details @(
                "脚本退出码：$($Matches[1])",
                "构建日志：$($Matches[2])"
            )
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
    $AllowedRoots = @($RepoRoot, $Poe2Dir) | ForEach-Object {
        [System.IO.Path]::GetFullPath($_).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ) + [System.IO.Path]::DirectorySeparatorChar
    }
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                if (-not $_.Path -or [System.IO.Path]::GetFileName($_.Path) -ne (Get-Poe2PatchName "InstallerExe")) {
                    return $false
                }
                $ProcessPath = [System.IO.Path]::GetFullPath($_.Path)
                return [bool]($AllowedRoots | Where-Object {
                        $ProcessPath.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase)
                    } | Select-Object -First 1)
            }
            catch {
                $false
            }
        } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Remove-LegacyFiles {
    param([switch]$IncludeGameFiles)

    $LegacyPatchZipNames = @(
        (Get-Poe2PatchName "LegacyPatchZip"),
        "price_patch.zip"
    )

    foreach ($Name in $LegacyPatchZipNames) {
        Remove-FileIfInside (Join-Path $RepoRoot $Name) $RepoRoot
        if ($IncludeGameFiles) {
            Remove-FileIfInside (Join-Path $Poe2Dir $Name) $Poe2Dir
        }
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
            $Detail = ([string]$ExportResult.Text).Trim()
            throw "无法判断 BaseItemTypes.datc64 是否包含物价补丁标记：检测工具退出码 $($ExportResult.ExitCode)。$Detail"
        }
        $Rows = Import-Csv -LiteralPath $TempCsv -Encoding UTF8
        return [bool]($Rows | Where-Object {
                $Name = [string]$_.name
                if ([string]::IsNullOrWhiteSpace($Name)) {
                    return $false
                }
                return (
                    $Name -match '=(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                    $Name -match '^(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$' -or
                    ($Name.Length -le 12 -and $Name -match '(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]$')
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

    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $CheckScript = Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"
    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
        $CheckScript,
        "--check-words", $SourceWords
    ) -Quiet
    if ($Result.ExitCode -ne 0) {
        $Detail = ([string]$Result.Text).Trim()
        throw "无法判断 Words.datc64 是否包含物价补丁标记：检测工具退出码 $($Result.ExitCode)。$Detail"
    }
    try {
        $Info = $Result.Text | ConvertFrom-Json
        return ([int]$Info.patched_count -gt 0)
    }
    catch {
        throw "无法判断 Words.datc64 是否包含物价补丁标记：检测结果无法解析。$($_.Exception.Message)"
    }
}

function Test-EndgameMapsLookPatched {
    param([string]$SourceEndgameMaps)

    if (-not (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf)) {
        return $false
    }

    try {
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $ScriptPath = Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $ScriptPath,
            "check",
            "--source", $SourceEndgameMaps,
            "--game-path", $InstallInfo.TcEndgameMapsPath
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            $Detail = ([string]$Result.Text).Trim()
            throw "无法判断 EndgameMaps.datc64 是否包含岛屿传言提示：检测工具退出码 $($Result.ExitCode)。$Detail"
        }
        $Info = $Result.Text | ConvertFrom-Json
        return ([int]$Info.patched_count -gt 0)
    }
    catch {
        throw "无法判断 EndgameMaps.datc64 是否包含岛屿传言提示：$($_.Exception.Message)"
    }
}

function Get-BaseItemsMetadataSignature {
    param([string]$SourceDat)

    Assert-File $SourceDat "BaseItemTypes.datc64"
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $SignatureScript = Join-Path $CodeToolsRoot "poe2_name_price_patch.py"
    $SignatureResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
        $SignatureScript,
        "signature",
        "--source", $SourceDat
    ) -Quiet
    if ($SignatureResult.ExitCode -ne 0) {
        throw "生成 BaseItemTypes 结构签名失败。退出码：$($SignatureResult.ExitCode)`n$($SignatureResult.Text)"
    }

    try {
        $Signature = $SignatureResult.Text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "解析 BaseItemTypes 结构签名失败：$($_.Exception.Message)"
    }

    $RequiredFields = @(
        "signature_version",
        "row_count",
        "row_size",
        "metadata_paths_sha256",
        "fixed_rows_sha256",
        "compatibility_sha256"
    )
    foreach ($Field in $RequiredFields) {
        $Property = $Signature.PSObject.Properties[$Field]
        if ($null -eq $Property -or [string]::IsNullOrWhiteSpace([string]$Property.Value)) {
            throw "BaseItemTypes 结构签名缺少字段或字段为空：$Field"
        }
    }

    return $Signature
}

function Test-BaseItemsCompatible {
    param(
        [string]$LeftDat,
        [string]$RightDat
    )

    try {
        $Left = Get-BaseItemsMetadataSignature $LeftDat
        $Right = Get-BaseItemsMetadataSignature $RightDat
        return (
            [string]$Left.signature_version -ceq [string]$Right.signature_version -and
            [string]$Left.row_count -ceq [string]$Right.row_count -and
            [string]$Left.row_size -ceq [string]$Right.row_size -and
            [string]$Left.metadata_paths_sha256 -ceq [string]$Right.metadata_paths_sha256 -and
            [string]$Left.fixed_rows_sha256 -ceq [string]$Right.fixed_rows_sha256 -and
            [string]$Left.compatibility_sha256 -ceq [string]$Right.compatibility_sha256
        )
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

function Test-RestoreZipWordsUsable {
    param([string]$Path)

    if (-not $SupportsUniqueWords) {
        return $true
    }
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
        $Entry = $Archive.GetEntry($TcWordsPath)
        if ($null -eq $Entry -or $Entry.Length -le 1024) {
            return $false
        }

        $TempWords = Join-Path $env:TEMP ([string]::Concat("poe2_restore_words_validate_", [Guid]::NewGuid().ToString("N"), ".datc64"))
        try {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempWords, $true)
            return -not (Test-WordsLookPatched $TempWords)
        }
        catch {
            return $false
        }
        finally {
            if (Test-Path -LiteralPath $TempWords -PathType Leaf) {
                Remove-Item -LiteralPath $TempWords -Force
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
    try {
        Assert-Poe2PhysicalRestoreZip -Path $Path -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo | Out-Null
        $script:LastPhysicalRestoreZipError = ""
        return $true
    }
    catch {
        $script:LastPhysicalRestoreZipError = $_.Exception.Message
        return $false
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

    $SearchRoots = New-Object System.Collections.Generic.List[string]
    foreach ($Root in @(
        $RepoRoot,
        $RestoreOutDir,
        (Join-Path $Poe2Dir ".poe2-price-patch"),
        $Poe2Dir,
        (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)),
        (Join-Path (Join-Path $Poe2Dir (Split-Path -Leaf $RepoRoot)) "output\restore")
    )) {
        if (-not [string]::IsNullOrWhiteSpace($Root)) {
            $SearchRoots.Add($Root)
        }
    }

    # A downloaded update is often extracted to a newly named sibling folder.
    # Search one level of sibling patch folders so their last verified backup is
    # not lost merely because the release directory name changed.
    if (Test-Path -LiteralPath $Poe2Dir -PathType Container) {
        foreach ($Directory in @(Get-ChildItem -LiteralPath $Poe2Dir -Directory -ErrorAction SilentlyContinue)) {
            $SearchRoots.Add($Directory.FullName)
            $SearchRoots.Add((Join-Path $Directory.FullName "output\restore"))
        }
    }

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

function Extract-RestoreEndgameMaps {
    param(
        [Parameter(Mandatory = $true)][string]$RestoreZip,
        [Parameter(Mandatory = $true)][string]$OutputEndgameMaps
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($RestoreZip)
    try {
        $Entry = $Archive.GetEntry($InstallInfo.TcEndgameMapsPath)
        if ($null -eq $Entry) {
            throw "还原包缺少目标文件 $($InstallInfo.TcEndgameMapsPath)：$RestoreZip"
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputEndgameMaps) | Out-Null
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $OutputEndgameMaps, $true)
    }
    finally {
        $Archive.Dispose()
    }

    if (Test-EndgameMapsLookPatched $OutputEndgameMaps) {
        throw "还原包里的 EndgameMaps.datc64 已经带有岛屿传言提示，拒绝继续使用：$RestoreZip"
    }
}

function Restore-CleanPatchSources {
    param([Parameter(Mandatory = $true)][string]$RestoreZip)

    Write-Step "还原干净补丁底板"
    Extract-RestoreBaseItems -RestoreZip $RestoreZip -OutputDat $TcBaseItems

    if ($SupportsUniqueWords) {
        if (Test-ZipEntryExists -ZipPath $RestoreZip -EntryName $TcWordsPath) {
            Extract-RestoreWords -RestoreZip $RestoreZip -OutputWords $TcWords
        }
        elseif ((Test-Path -LiteralPath $TcWords -PathType Leaf) -and -not (Test-WordsLookPatched $TcWords)) {
            Write-Host "还原包缺少 Words，当前提取的 Words 已确认干净，将作为底板。" -ForegroundColor Yellow
        }
        else {
            throw "缺少可用的干净 Words.datc64，无法保证按补丁范围清理旧传奇价格。请先运行一键还原或修复游戏文件后再更新。"
        }
    }

    if ($PatchIslandRumourHintsEnabled) {
        if (Test-ZipEntryExists -ZipPath $RestoreZip -EntryName $InstallInfo.TcEndgameMapsPath) {
            Extract-RestoreEndgameMaps -RestoreZip $RestoreZip -OutputEndgameMaps $TcEndgameMaps
        }
        elseif ((Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf) -and -not (Test-EndgameMapsLookPatched $TcEndgameMaps)) {
            Write-Host "还原包缺少 EndgameMaps，当前提取的 EndgameMaps 已确认干净，将作为底板。" -ForegroundColor Yellow
        }
        else {
            throw "缺少可用的干净 EndgameMaps.datc64，无法生成岛屿传言提示。请先运行一键还原或修复游戏文件后再更新。"
        }
    }
}

function New-BaseItemZip {
    param(
        [string]$SourceDat,
        [string]$SourceWords = "",
        [string]$SourceEndgameMaps = "",
        [string]$OutputZip
    )

    Assert-File $SourceDat $InstallInfo.TcBaseItemsPath
    if (-not [string]::IsNullOrWhiteSpace($SourceWords) -and (Test-Path -LiteralPath $SourceWords -PathType Leaf) -and (Test-WordsLookPatched $SourceWords)) {
        throw "检测到 Words.datc64 已包含物价补丁标记，拒绝用它创建还原包。"
    }
    if (-not [string]::IsNullOrWhiteSpace($SourceEndgameMaps) -and (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf) -and (Test-EndgameMapsLookPatched $SourceEndgameMaps)) {
        throw "检测到 EndgameMaps.datc64 已包含岛屿传言提示，拒绝用它创建还原包。"
    }

    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputZip), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $Archive,
                $SourceDat,
                $InstallInfo.TcBaseItemsPath,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
            if (-not [string]::IsNullOrWhiteSpace($SourceWords) -and (Test-Path -LiteralPath $SourceWords -PathType Leaf)) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceWords,
                    $TcWordsPath,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
            if (-not [string]::IsNullOrWhiteSpace($SourceEndgameMaps) -and (Test-Path -LiteralPath $SourceEndgameMaps -PathType Leaf)) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceEndgameMaps,
                    $InstallInfo.TcEndgameMapsPath,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $Archive.Dispose()
        }
        Get-Poe2ZipEntryCrc32Map -Path $TempZip | Out-Null
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputZip | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
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
    $ZipPath = [System.IO.Path]::GetFullPath($ZipPath)
    $ZipDir = Split-Path -Parent $ZipPath
    $TempZip = Join-Path $ZipDir ([string]::Concat(".", (Split-Path -Leaf $ZipPath), ".update-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Mode = if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
            [System.IO.File]::Copy($ZipPath, $TempZip, $false)
            [System.IO.Compression.ZipArchiveMode]::Update
        }
        else {
            [System.IO.Compression.ZipArchiveMode]::Create
        }
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, $Mode)
        try {
            $OldEntry = if ($Mode -eq [System.IO.Compression.ZipArchiveMode]::Update) {
                $Archive.GetEntry($EntryName)
            }
            else {
                $null
            }
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
        Get-Poe2ZipEntryCrc32Map -Path $TempZip | Out-Null
        Move-Poe2FileAtomically -Source $TempZip -Destination $ZipPath | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
}

function Merge-ExistingBundlePatchEntries {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string[]]$ExcludeEntries
    )

    if ($GameMode -ne "Bundles2") {
        return
    }

    $LibDir = Join-Path $Bundles2Paths.Bundles2Dir "LibGGPK3"
    if (-not (Test-Path -LiteralPath $LibDir -PathType Container)) {
        return
    }

    Resolve-BundleExtractor
    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_preserve_bundle_patch_", [Guid]::NewGuid().ToString("N")))
    $ListPath = Join-Path $TempDir "libggpk3-files.tsv"
    $RequestListPath = Join-Path $TempDir "preserve-files.txt"
    $ExtractDir = Join-Path $TempDir "extracted"
    $ListLog = Join-Path $TempDir "list.log"
    $ExtractLog = Join-Path $TempDir "extract.log"
    $Exclude = @{}
    foreach ($Entry in $ExcludeEntries) {
        if (-not [string]::IsNullOrWhiteSpace($Entry)) {
            $Exclude[$Entry.Replace("\", "/").ToLowerInvariant()] = $true
        }
    }

    try {
        New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
        Write-Host "正在扫描已有 Bundles2 增量补丁（大型索引通常需要 15-30 秒）..." -ForegroundColor Yellow
        & $BundledBundleExtractorExe --list $Bundles2Paths.IndexBin $ListPath "LibGGPK3/" *> $ListLog
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ListPath -PathType Leaf)) {
            throw "列出现有 Bundles2 增量补丁失败。为避免覆盖并丢失其它补丁，本次已中止。日志：$ListLog"
        }

        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $ExistingZipEntries = @{}
        if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
            $ReadArchive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
            try {
                foreach ($ZipEntry in $ReadArchive.Entries) {
                    $ExistingZipEntries[$ZipEntry.FullName.Replace("\", "/").ToLowerInvariant()] = $true
                }
            }
            finally {
                $ReadArchive.Dispose()
            }
        }

        $Rows = @(Import-Csv -LiteralPath $ListPath -Delimiter "`t" -Encoding UTF8)
        $EntriesToPreserve = New-Object System.Collections.Generic.List[string]
        foreach ($Row in $Rows) {
            $EntryName = ([string]$Row.path).Replace("\", "/")
            if ([string]::IsNullOrWhiteSpace($EntryName)) {
                continue
            }
            if ($Exclude.ContainsKey($EntryName.ToLowerInvariant())) {
                continue
            }
            if ($ExistingZipEntries.ContainsKey($EntryName.ToLowerInvariant())) {
                continue
            }

            $EntriesToPreserve.Add($EntryName)
        }

        if ($EntriesToPreserve.Count -eq 0) {
            Write-Host "没有需要合并的其它 Bundles2 增量补丁。" -ForegroundColor DarkGray
            return
        }

        New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
        [System.IO.File]::WriteAllLines(
            $RequestListPath,
            $EntriesToPreserve.ToArray(),
            (New-Object System.Text.UTF8Encoding($false))
        )
        Write-Host "发现 $($EntriesToPreserve.Count) 个其它增量文件，正在批量读取（索引只加载一次）..." -ForegroundColor Yellow
        & $BundledBundleExtractorExe --extract-list $Bundles2Paths.IndexBin $RequestListPath $ExtractDir *> $ExtractLog
        $BatchExitCode = $LASTEXITCODE
        if ($BatchExitCode -ne 0) {
            throw "批量读取已有 Bundles2 增量文件失败。为避免覆盖并丢失其它补丁，本次已中止。退出码：$BatchExitCode；日志：$ExtractLog"
        }
        $MissingExtractedEntries = New-Object System.Collections.Generic.List[string]
        for ($Index = 0; $Index -lt $EntriesToPreserve.Count; $Index++) {
            $OutFile = Join-Path $ExtractDir ([string]::Format("{0:D6}.bin", $Index))
            if (-not (Test-Path -LiteralPath $OutFile -PathType Leaf)) {
                $MissingExtractedEntries.Add($EntriesToPreserve[$Index])
            }
        }
        if ($MissingExtractedEntries.Count -gt 0) {
            throw "批量读取已有 Bundles2 增量文件不完整，缺少 $($MissingExtractedEntries.Count) 个文件。为避免覆盖并丢失其它补丁，本次已中止。日志：$ExtractLog"
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ZipPath) | Out-Null
        $ZipMode = if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
            [System.IO.Compression.ZipArchiveMode]::Update
        }
        else {
            [System.IO.Compression.ZipArchiveMode]::Create
        }
        $PatchArchive = [System.IO.Compression.ZipFile]::Open($ZipPath, $ZipMode)
        $Merged = 0
        try {
            for ($Index = 0; $Index -lt $EntriesToPreserve.Count; $Index++) {
                $EntryName = $EntriesToPreserve[$Index]
                $OutFile = Join-Path $ExtractDir ([string]::Format("{0:D6}.bin", $Index))
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $PatchArchive,
                    $OutFile,
                    $EntryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
                $Merged += 1
                if (($Merged % 25) -eq 0 -or $Index -eq ($EntriesToPreserve.Count - 1)) {
                    Write-Host "合并已有增量补丁：$Merged/$($EntriesToPreserve.Count)" -ForegroundColor DarkGray
                }
            }
        }
        finally {
            $PatchArchive.Dispose()
        }

        if ($Merged -gt 0) {
            Write-Host "已合并保留现有 Bundles2 增量补丁文件 $Merged 个。" -ForegroundColor Green
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempDir -PathType Container) {
            Remove-Item -LiteralPath $TempDir -Recurse -Force
        }
    }
}

function Assert-Bundles2PatchApplied {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string[]]$EntryNames,
        [string]$IndexPath = "",
        [switch]$RequireCleanPriceLayer
    )

    if ([string]::IsNullOrWhiteSpace($IndexPath)) {
        $IndexPath = $Bundles2Paths.IndexBin
    }

    Resolve-BundleExtractor
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $EntriesToVerify = New-Object System.Collections.Generic.List[string]
    $Seen = @{}
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($Name in $EntryNames) {
            if ([string]::IsNullOrWhiteSpace($Name)) {
                continue
            }
            $Normalized = $Name.Replace("\", "/")
            $Key = $Normalized.ToLowerInvariant()
            if ($Seen.ContainsKey($Key)) {
                continue
            }
            if ($null -ne $Archive.GetEntry($Normalized)) {
                $Seen[$Key] = $true
                $EntriesToVerify.Add($Normalized)
            }
        }
    }
    finally {
        $Archive.Dispose()
    }

    if ($EntriesToVerify.Count -eq 0) {
        throw "Bundles2 patch verification failed. No target entries were found in patch zip: $ZipPath"
    }

    $TempDir = Join-Path $env:TEMP ([string]::Concat("poe2_verify_bundle_patch_", [Guid]::NewGuid().ToString("N")))
    $RequestListPath = Join-Path $TempDir "verify-files.txt"
    $ExtractDir = Join-Path $TempDir "extracted"
    $VerifyLog = Join-Path $TempDir "verify.log"
    try {
        New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
        [System.IO.File]::WriteAllLines(
            $RequestListPath,
            $EntriesToVerify.ToArray(),
            (New-Object System.Text.UTF8Encoding($false))
        )
        & $BundledBundleExtractorExe --extract-list $IndexPath $RequestListPath $ExtractDir *> $VerifyLog
        $VerifyExitCode = $LASTEXITCODE
        if ($VerifyExitCode -ne 0) {
            throw "Bundles2 patch verification failed. Extractor exit code: $VerifyExitCode. Log: $VerifyLog"
        }

        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            for ($Index = 0; $Index -lt $EntriesToVerify.Count; $Index++) {
                $EntryName = $EntriesToVerify[$Index]
                $ActualPath = Join-Path $ExtractDir ([string]::Format("{0:D6}.bin", $Index))
                if (-not (Test-Path -LiteralPath $ActualPath -PathType Leaf)) {
                    throw "Bundles2 patch verification failed. Extracted target is missing: $EntryName. Log: $VerifyLog"
                }

                $ZipEntry = $Archive.GetEntry($EntryName)
                if ($null -eq $ZipEntry) {
                    throw "Bundles2 patch verification failed. Patch entry disappeared: $EntryName"
                }
                $ActualInfo = Get-Item -LiteralPath $ActualPath
                if ($ActualInfo.Length -ne $ZipEntry.Length) {
                    throw "Bundles2 patch verification failed. Size mismatch: $EntryName"
                }

                $Sha = [System.Security.Cryptography.SHA256]::Create()
                $EntryStream = $ZipEntry.Open()
                try {
                    $ExpectedHash = [System.BitConverter]::ToString($Sha.ComputeHash($EntryStream)).Replace("-", "")
                }
                finally {
                    $EntryStream.Dispose()
                    $Sha.Dispose()
                }
                $ActualHash = (Get-FileHash -LiteralPath $ActualPath -Algorithm SHA256).Hash
                if ($ActualHash -ne $ExpectedHash) {
                    throw "Bundles2 patch verification failed. Content mismatch: $EntryName"
                }

                if ($RequireCleanPriceLayer) {
                    if ($EntryName -eq $InstallInfo.TcBaseItemsPath -and (Test-BaseItemsLookPatched $ActualPath)) {
                        throw "清理迁移校验失败：BaseItemTypes.datc64 仍包含物价补丁标记。"
                    }
                    if ($EntryName -eq $TcWordsPath -and (Test-WordsLookPatched $ActualPath)) {
                        throw "清理迁移校验失败：Words.datc64 的当前有效行仍包含物价补丁标记。"
                    }
                    if ($EntryName -eq $InstallInfo.TcEndgameMapsPath -and (Test-EndgameMapsLookPatched $ActualPath)) {
                        throw "清理迁移校验失败：EndgameMaps.datc64 仍包含岛屿传言提示。"
                    }
                }
            }
        }
        finally {
            $Archive.Dispose()
        }

        Write-Host "已校验 Bundles2 中的 $($EntriesToVerify.Count) 个补丁文件。" -ForegroundColor Green
    }
    finally {
        if (Test-Path -LiteralPath $TempDir -PathType Container) {
            Remove-Item -LiteralPath $TempDir -Recurse -Force
        }
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
            }
            else {
                Update-ZipEntryFromFile -ZipPath $ZipPath -SourceDat $ExtractedWords -EntryName $WordsEntryName
                $Updated += 1
            }
        }

        $EndgameMapsEntryName = Get-Poe2EndgameMapsPathFromBaseItemsPath -BaseItemsPath $EntryName
        $ExtractedEndgameMaps = Get-ExtractedBaseItemsPathForEntry $EndgameMapsEntryName
        if (Test-Path -LiteralPath $ExtractedEndgameMaps -PathType Leaf) {
            if (Test-EndgameMapsLookPatched $ExtractedEndgameMaps) {
                Write-Warning "跳过 EndgameMaps 还原条目刷新：该文件已包含岛屿传言提示。条目：$EndgameMapsEntryName"
                continue
            }
            Update-ZipEntryFromFile -ZipPath $ZipPath -SourceDat $ExtractedEndgameMaps -EntryName $EndgameMapsEntryName
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
            $TempEndgameMaps = Join-Path $TempDir "EndgameMaps.datc64"
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

            if ($PatchIslandRumourHintsEnabled) {
                & $BundledBundleExtractorExe $TempIndex $InstallInfo.TcEndgameMapsPath $TempEndgameMaps *> $ExtractLog
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "忽略真实还原包：提取 EndgameMaps 失败。文件：$Candidate；日志：$ExtractLog"
                    continue
                }
                if (Test-EndgameMapsLookPatched $TempEndgameMaps) {
                    Write-Warning "忽略真实还原包：提取出的 EndgameMaps 已包含岛屿传言提示。文件：$Candidate"
                    continue
                }
            }

            New-BaseItemZip -SourceDat $TempDat -SourceWords $TempWords -SourceEndgameMaps $TempEndgameMaps -OutputZip $OutputZip
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
    param(
        [string]$OutputZip,
        [string]$SourceBundles2Dir = "",
        [ValidateSet("byte-exact-prepatch", "semantic-clean-migration")]
        [string]$BaselineKind = "byte-exact-prepatch",
        $WritePrecondition = $null
    )

    if ($GameMode -ne "Bundles2") {
        return $null
    }

    # Extraction/building can take minutes; close the race with the earlier preflight.
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin
    if ($null -eq $WritePrecondition) {
        $WritePrecondition = Get-Poe2Bundles2MutationFingerprint -Bundles2Dir $Bundles2Paths.Bundles2Dir
    }
    else {
        Assert-Poe2Bundles2MutationFingerprintCurrent `
            -Expected $WritePrecondition `
            -Bundles2Dir $Bundles2Paths.Bundles2Dir | Out-Null
    }

    $BackupBundles2Dir = $Bundles2Paths.Bundles2Dir
    if (-not [string]::IsNullOrWhiteSpace($SourceBundles2Dir)) {
        $BackupBundles2Dir = (Resolve-Path -LiteralPath $SourceBundles2Dir).Path
    }

    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputZip
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputZip), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))

    $BackupSources = New-Object System.Collections.Generic.List[object]
    foreach ($Relative in @(
        "_.index.bin",
        "_.index.high.bin",
        "_.index.low.bin",
        ".index.dbg"
    )) {
        $Source = Join-Path $BackupBundles2Dir $Relative
        if (Test-Path -LiteralPath $Source -PathType Leaf) {
            $BackupSources.Add([pscustomobject]@{
                    Source = $Source
                    Entry = "Bundles2/" + ($Relative -replace '\\', '/')
                })
        }
    }
    if (-not ($BackupSources | Where-Object { $_.Entry -eq "Bundles2/_.index.bin" } | Select-Object -First 1)) {
        throw "无法创建真实还原包：Bundles2/_.index.bin 不存在。"
    }

    $LibDir = Join-Path $BackupBundles2Dir "LibGGPK3"
    if (Test-Path -LiteralPath $LibDir -PathType Container) {
        $Bundles2Prefix = [System.IO.Path]::GetFullPath($BackupBundles2Dir).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ) + [System.IO.Path]::DirectorySeparatorChar
        foreach ($File in @(Get-ChildItem -LiteralPath $LibDir -Recurse -File -ErrorAction Stop | Sort-Object FullName)) {
            $Relative = $File.FullName.Substring($Bundles2Prefix.Length).Replace("\", "/")
            $BackupSources.Add([pscustomobject]@{
                    Source = $File.FullName
                    Entry = "Bundles2/" + $Relative
                })
        }
    }

    $BaseFingerprint = Get-Poe2PhysicalBaseFingerprint -Poe2Dir $Poe2Dir
    $RestoreFiles = New-Object System.Collections.Generic.List[object]
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($Item in $BackupSources) {
                $SourceInfo = Get-Item -LiteralPath $Item.Source -ErrorAction Stop
                $Sha256 = Get-Poe2Sha256Hex -Path $SourceInfo.FullName
                $Crc32 = Get-Poe2FileCrc32Hex -Path $SourceInfo.FullName
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceInfo.FullName,
                    [string]$Item.Entry,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
                $RestoreFiles.Add([pscustomobject][ordered]@{
                        path = [string]$Item.Entry
                        length = [long]$SourceInfo.Length
                        sha256 = $Sha256
                        crc32 = $Crc32
                    })
            }

            $Manifest = [ordered]@{
                kind = "poe2-price-patch-physical-restore"
                version = 2
                created_at = (Get-Date).ToUniversalTime().ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
                install_kind = $InstallInfo.InstallKind
                target_path = $InstallInfo.TcBaseItemsPath
                mode = $GameMode
                baseline_kind = $BaselineKind
                base_fingerprint = $BaseFingerprint
                write_precondition = $WritePrecondition
                restore_files = $RestoreFiles.ToArray()
                note = if ($BaselineKind -eq "semantic-clean-migration") {
                    "A clean price-layer baseline synthesized offline from the current Bundles2 state. Other compatible patches are preserved."
                }
                else {
                    "Restore these byte-exact pre-patch Bundles2 files only while the official base fingerprint still matches."
                }
            }
            $ManifestJson = $Manifest | ConvertTo-Json -Depth 8
            $ManifestEntry = $Archive.CreateEntry("manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
            $Writer = New-Object System.IO.StreamWriter($ManifestEntry.Open(), [System.Text.UTF8Encoding]::new($false))
            try {
                $Writer.Write($ManifestJson)
            }
            finally {
                $Writer.Dispose()
            }
        }
        finally {
            $Archive.Dispose()
        }

        Assert-Poe2PhysicalRestoreZip -Path $TempZip -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo | Out-Null
        Assert-Poe2Bundles2MutationFingerprintCurrent `
            -Expected $WritePrecondition `
            -Bundles2Dir $Bundles2Paths.Bundles2Dir | Out-Null
        if ($env:POE2_PATCH_TEST_FAIL_PHYSICAL_ZIP -eq "before-replace") {
            throw "Injected physical restore ZIP generation failure before atomic replace."
        }
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputZip | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }

    return (Resolve-Path -LiteralPath $OutputZip).Path
}

function New-CleanPhysicalRestoreZipFromPatchedSources {
    param([Parameter(Mandatory = $true)][string]$OutputZip)

    if ($GameMode -ne "Bundles2") {
        return $null
    }

    # Legacy releases could write a price layer without leaving a durable
    # physical backup.  Rebuild a semantically clean baseline entirely in a
    # sandbox: clean only markers owned by this tool, apply that clean layer to
    # a copied index/LibGGPK3 state, verify live rows, and package the sandbox.
    # The real game is not written anywhere in this function.
    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe2_clean_restore_migration_", [Guid]::NewGuid().ToString("N")))
    $CleanupOutDir = Join-Path $TempRoot "clean-layer"
    $CleanPatchZip = Join-Path $TempRoot "clean-price-layer.zip"
    $CleanBaseItems = Join-Path $CleanupOutDir "baseitemtypes.clean.datc64"
    $CleanWords = Join-Path $CleanupOutDir "words.clean.datc64"
    $CleanEndgameMaps = Join-Path $CleanupOutDir "endgamemaps.clean.datc64"
    $CleanupReport = Join-Path $CleanupOutDir "cleanup.report.json"
    $CleanupLog = Join-Path $CleanupOutDir "cleanup.log"
    $SandboxBundles2 = Join-Path $TempRoot "sandbox\Bundles2"

    try {
        New-Item -ItemType Directory -Force -Path $CleanupOutDir | Out-Null
        Write-Host "未找到旧版真实还原包，正在离线清理旧物价层并构建安全迁移基线..." -ForegroundColor Yellow

        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $CleanupArgs = @(
            (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
            "--patch-scope", "none",
            "--fallback-price-sources", "none",
            "--en-baseitems", $EnBaseItems,
            "--tc-baseitems", $TcBaseItems,
            "--out-dir", $CleanupOutDir,
            "--output-zip", $CleanPatchZip,
            "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
            "--mode", "append",
            "--patched-dat", $CleanBaseItems,
            "--report", $CleanupReport,
            "--game-path", $InstallInfo.TcBaseItemsPath,
            "--no-uniques",
            "--strict-feature-cleanup"
        )
        if ($SupportsUniqueWords -and (Test-Path -LiteralPath $TcWords -PathType Leaf)) {
            $CleanupArgs += @(
                "--tc-words", $TcWords,
                "--patched-words", $CleanWords,
                "--words-game-path", $TcWordsPath
            )
        }

        $CleanupResult = Invoke-Poe2Python -Python $Python -ArgumentList $CleanupArgs
        $CleanupResult.Text | Out-File -LiteralPath $CleanupLog -Encoding UTF8
        if ($CleanupResult.ExitCode -ne 0) {
            throw "清理旧 BaseItemTypes/Words 物价标记失败。退出码：$($CleanupResult.ExitCode)；日志：$CleanupLog"
        }

        $EndgameWasPatched = $false
        if (Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf) {
            $EndgameWasPatched = Test-EndgameMapsLookPatched $TcEndgameMaps
        }
        if ($EndgameWasPatched) {
            $EndgameCleanup = Invoke-Poe2Python -Python $Python -ArgumentList @(
                (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"),
                "clean",
                "--source", $TcEndgameMaps,
                "--output-zip", $CleanPatchZip,
                "--patched-dat", $CleanEndgameMaps,
                "--game-path", $InstallInfo.TcEndgameMapsPath,
                "--report", (Join-Path $CleanupOutDir "endgamemaps-cleanup.report.json")
            )
            $EndgameCleanup.Text | Out-File -LiteralPath $CleanupLog -Encoding UTF8 -Append
            if ($EndgameCleanup.ExitCode -ne 0) {
                throw "清理旧 EndgameMaps 岛屿提示失败。退出码：$($EndgameCleanup.ExitCode)；日志：$CleanupLog"
            }
        }
        Assert-File $CleanPatchZip "clean price-layer migration zip"

        Write-Host "正在创建 Bundles2 离线沙盒，不会修改真实游戏文件..." -ForegroundColor Yellow
        $MigrationWritePrecondition = Get-Poe2Bundles2MutationFingerprint -Bundles2Dir $Bundles2Paths.Bundles2Dir
        New-Item -ItemType Directory -Force -Path $SandboxBundles2 | Out-Null
        foreach ($Relative in @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")) {
            $Source = Join-Path $Bundles2Paths.Bundles2Dir $Relative
            if (Test-Path -LiteralPath $Source -PathType Leaf) {
                Copy-Item -LiteralPath $Source -Destination (Join-Path $SandboxBundles2 $Relative) -Force
            }
        }
        Assert-File (Join-Path $SandboxBundles2 "_.index.bin") "sandbox Bundles2 _.index.bin"
        $SourceLibDir = Join-Path $Bundles2Paths.Bundles2Dir "LibGGPK3"
        if (Test-Path -LiteralPath $SourceLibDir -PathType Container) {
            Copy-Item -LiteralPath $SourceLibDir -Destination $SandboxBundles2 -Recurse -Force
        }

        $SandboxIndex = Join-Path $SandboxBundles2 "_.index.bin"
        $UsePatchBundleDll = Test-Path -LiteralPath $BundledBundlePatchDll -PathType Leaf
        $PatchBundleExe = $BundledBundlePatchExe
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $PatchBundleExe -PathType Leaf)) {
            $PatchBundleExe = Join-Path $CodeToolsRoot "PatchBundle3.exe"
        }
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $PatchBundleExe -PathType Leaf)) {
            throw "Missing PatchBundle3.dll or PatchBundle3.exe: $BundledBundlePatchDll"
        }

        Push-Location -LiteralPath $BundledInstallerDir
        try {
            if ($UsePatchBundleDll) {
                $PatchResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledBundlePatchDll, $SandboxIndex, $CleanPatchZip) -InputText "" -Quiet
                $PatchOutput = $PatchResult.Lines
                $PatchExitCode = $PatchResult.ExitCode
            }
            else {
                $PatchOutput = & $PatchBundleExe $SandboxIndex $CleanPatchZip 2>&1
                $PatchExitCode = $LASTEXITCODE
            }
        }
        finally {
            Pop-Location
        }
        $PatchOutput | ForEach-Object { Write-Host $_ }
        if ($PatchExitCode -ne 0 -or (Test-ToolOutputFailure -Text ($PatchOutput | Out-String) -ExtraNeedles @("FileNotFound", "Could not load"))) {
            throw "PatchBundle3 离线清理迁移失败。退出码：$PatchExitCode"
        }

        Assert-Bundles2PatchApplied -ZipPath $CleanPatchZip -EntryNames @(
            $InstallInfo.TcBaseItemsPath,
            $TcWordsPath,
            $InstallInfo.TcEndgameMapsPath
        ) -IndexPath $SandboxIndex -RequireCleanPriceLayer

        $Created = New-PhysicalRestoreZip `
            -OutputZip $OutputZip `
            -SourceBundles2Dir $SandboxBundles2 `
            -BaselineKind "semantic-clean-migration" `
            -WritePrecondition $MigrationWritePrecondition
        Assert-Poe2PhysicalRestoreZip -Path $Created -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo | Out-Null
        Write-Host "已从旧补丁状态构建并验证干净迁移基线。" -ForegroundColor Green
        return $Created
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force
        }
    }
}

function Copy-PhysicalRestoreZipAtomically {
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
        Assert-Poe2PhysicalRestoreZip -Path $TempCopy -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo | Out-Null
        Move-Poe2FileAtomically -Source $TempCopy -Destination $DestinationFull | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempCopy -PathType Leaf) {
            Remove-Item -LiteralPath $TempCopy -Force -ErrorAction SilentlyContinue
        }
    }
    return (Resolve-Path -LiteralPath $DestinationFull).Path
}

function Publish-PhysicalRestoreZip {
    param([Parameter(Mandatory = $true)][string]$Source)

    $PatchFolderCopy = Copy-PhysicalRestoreZipAtomically `
        -Source $Source `
        -Destination $PhysicalRestorePatchFolderZip
    if (-not [string]::IsNullOrWhiteSpace($PersistentPhysicalRestoreZip)) {
        Copy-PhysicalRestoreZipAtomically `
            -Source $PatchFolderCopy `
            -Destination $PersistentPhysicalRestoreZip | Out-Null
    }
    return $PatchFolderCopy
}

function Ensure-PhysicalRestoreZip {
    param([bool]$SourceLooksPatched)

    if ($GameMode -ne "Bundles2") {
        return ""
    }

    if (-not $SourceLooksPatched) {
        Write-Host "正在用当前 Bundles2 状态刷新真实还原包..." -ForegroundColor Yellow
        $Created = New-PhysicalRestoreZip -OutputZip $PhysicalRestoreOutZip
        if ([string]::IsNullOrWhiteSpace($Created) -or -not (Test-PhysicalRestoreZipUsable $Created)) {
            throw "创建真实还原包失败：$PhysicalRestoreOutZip"
        }

        return Publish-PhysicalRestoreZip -Source $Created
    }

    $UsableCandidates = New-Object System.Collections.Generic.List[string]
    foreach ($Candidate in (Get-PhysicalRestoreZipCandidates)) {
        if (Test-PhysicalRestoreZipUsable $Candidate) {
            $UsableCandidates.Add((Resolve-Path -LiteralPath $Candidate).Path)
        }
    }

    if ($UsableCandidates.Count -gt 0) {
        $CandidatesByHash = @($UsableCandidates | Group-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
        if ($CandidatesByHash.Count -gt 1) {
            $CandidateList = [string]::Join("；", $UsableCandidates.ToArray())
            throw "找到多个内容不同、但都能通过校验的真实还原包，无法安全判断应使用哪一个：$CandidateList"
        }
        $Selected = @($UsableCandidates | Sort-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } -Descending)[0]
        return Publish-PhysicalRestoreZip -Source $Selected
    }

    $Reason = if ([string]::IsNullOrWhiteSpace($script:LastPhysicalRestoreZipError)) { "未找到可用文件" } else { $script:LastPhysicalRestoreZipError }
    try {
        $Migrated = New-CleanPhysicalRestoreZipFromPatchedSources -OutputZip $PhysicalRestoreOutZip
        if ([string]::IsNullOrWhiteSpace($Migrated) -or -not (Test-PhysicalRestoreZipUsable $Migrated)) {
            throw "迁移函数没有生成可验证的真实还原包。"
        }
        return Publish-PhysicalRestoreZip -Source $Migrated
    }
    catch {
        throw "缺少与当前游戏底板匹配的安全真实还原包（$Reason），自动清理迁移也失败：$($_.Exception.Message)。真实游戏文件尚未被修改。请让 Steam/Epic/WeGame 验证或修复游戏文件后再运行一键更新。"
    }
}

function Ensure-RestoreZip {
    param([string]$SourceDat)

    New-Item -ItemType Directory -Force -Path $RestoreOutDir | Out-Null
    $SourceBaseItemsLooksPatched = Test-BaseItemsLookPatched $SourceDat
    $SourceWordsLooksPatched = $false
    $SourceWordsAvailable = $SupportsUniqueWords -and (Test-Path -LiteralPath $TcWords -PathType Leaf)
    if ($SourceWordsAvailable) {
        $SourceWordsLooksPatched = Test-WordsLookPatched $TcWords
    }
    $SourceEndgameMapsLooksPatched = $false
    $SourceEndgameMapsAvailable = Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf
    if ($SourceEndgameMapsAvailable) {
        $SourceEndgameMapsLooksPatched = Test-EndgameMapsLookPatched $TcEndgameMaps
    }
    $SourceLooksPatched = $SourceBaseItemsLooksPatched -or $SourceWordsLooksPatched -or $SourceEndgameMapsLooksPatched

    foreach ($Candidate in (Get-RestoreZipCandidates)) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            if (-not (Test-RestoreZipUsable -Path $Candidate -ReferenceDat $SourceDat)) {
                Write-Warning "忽略不可用或已过期的还原包：$Candidate"
                continue
            }
            $ResolvedCandidate = (Resolve-Path -LiteralPath $Candidate).Path
            $CandidateWork = Join-Path $RestoreOutDir ([string]::Concat(".", $RestoreZipName, ".candidate-", [Guid]::NewGuid().ToString("N"), ".tmp"))
            try {
                [System.IO.File]::Copy($ResolvedCandidate, $CandidateWork, $false)
                if ($SupportsUniqueWords -and -not (Test-RestoreZipWordsUsable $CandidateWork)) {
                    if ($SourceWordsAvailable -and -not $SourceWordsLooksPatched) {
                        Update-ZipEntryFromFile -ZipPath $CandidateWork -SourceDat $TcWords -EntryName $TcWordsPath
                    }
                    elseif ($SourceWordsLooksPatched) {
                        Write-Warning "忽略缺少干净 Words 的还原包：$Candidate"
                        continue
                    }
                    else {
                        Write-Warning "还原包缺少 Words，且当前没有可用的 Words 文件：$Candidate"
                    }
                }
                if ($SourceEndgameMapsAvailable -and -not (Test-ZipEntryExists -ZipPath $CandidateWork -EntryName $InstallInfo.TcEndgameMapsPath)) {
                    if (-not $SourceEndgameMapsLooksPatched) {
                        Update-ZipEntryFromFile -ZipPath $CandidateWork -SourceDat $TcEndgameMaps -EntryName $InstallInfo.TcEndgameMapsPath
                    }
                    else {
                        Write-Warning "忽略缺少干净 EndgameMaps 的还原包：$Candidate"
                        continue
                    }
                }
                if (-not (Test-RestoreZipUsable -Path $CandidateWork -ReferenceDat $SourceDat)) {
                    Write-Warning "忽略补全后仍不可用的还原包：$Candidate"
                    continue
                }
                if ($SupportsUniqueWords -and -not (Test-RestoreZipWordsUsable $CandidateWork)) {
                    Write-Warning "忽略补全后仍缺少干净 Words 的还原包：$Candidate"
                    continue
                }
                Move-Poe2FileAtomically -Source $CandidateWork -Destination $RestoreOutZip | Out-Null
                return (Resolve-Path -LiteralPath $RestoreOutZip).Path
            }
            finally {
                if (Test-Path -LiteralPath $CandidateWork -PathType Leaf) {
                    Remove-Item -LiteralPath $CandidateWork -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }

    if (-not $SourceLooksPatched) {
        Write-Host "正在用当前干净 BaseItemTypes/Words 刷新固定还原包..." -ForegroundColor Yellow
        $CleanTcWords = ""
        if ($SourceWordsAvailable -and -not $SourceWordsLooksPatched) {
            $CleanTcWords = $TcWords
        }
        $CleanTcEndgameMaps = ""
        if ($SourceEndgameMapsAvailable -and -not $SourceEndgameMapsLooksPatched) {
            $CleanTcEndgameMaps = $TcEndgameMaps
        }
        $RestoreBuildTemp = Join-Path $RestoreOutDir ([string]::Concat(".", $RestoreZipName, ".build-", [Guid]::NewGuid().ToString("N"), ".tmp"))
        try {
            if ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") {
                New-BaseItemZip -SourceDat $SourceDat -SourceWords $CleanTcWords -SourceEndgameMaps $CleanTcEndgameMaps -OutputZip $RestoreBuildTemp
            }
            else {
                $SeedZip = ""
                foreach ($Candidate in (Get-RestoreZipCandidates)) {
                    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                        $SeedZip = (Resolve-Path -LiteralPath $Candidate).Path
                        break
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($SeedZip)) {
                    Copy-Poe2FileAtomically -Source $SeedZip -Destination $RestoreBuildTemp | Out-Null
                }
                Update-RestoreZipEntry -ZipPath $RestoreBuildTemp -SourceDat $SourceDat -EntryName $InstallInfo.TcBaseItemsPath
                if (-not [string]::IsNullOrWhiteSpace($CleanTcWords)) {
                    Update-ZipEntryFromFile -ZipPath $RestoreBuildTemp -SourceDat $CleanTcWords -EntryName $TcWordsPath
                }
                if (-not [string]::IsNullOrWhiteSpace($CleanTcEndgameMaps)) {
                    Update-ZipEntryFromFile -ZipPath $RestoreBuildTemp -SourceDat $CleanTcEndgameMaps -EntryName $InstallInfo.TcEndgameMapsPath
                }
            }
            if (-not (Test-RestoreZipUsable -Path $RestoreBuildTemp -ReferenceDat $SourceDat)) {
                throw "新建还原包的 BaseItemTypes 校验失败。"
            }
            if (-not [string]::IsNullOrWhiteSpace($CleanTcWords) -and -not (Test-RestoreZipWordsUsable $RestoreBuildTemp)) {
                throw "新建还原包的 Words 校验失败。"
            }
            Move-Poe2FileAtomically -Source $RestoreBuildTemp -Destination $RestoreOutZip | Out-Null
        }
        finally {
            if (Test-Path -LiteralPath $RestoreBuildTemp -PathType Leaf) {
                Remove-Item -LiteralPath $RestoreBuildTemp -Force -ErrorAction SilentlyContinue
            }
        }
        if (-not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") -and $RestoreOutZip -ne $RestorePatchFolderZip) {
            Copy-Poe2FileAtomically -Source $RestoreOutZip -Destination $RestorePatchFolderZip | Out-Null
        }
        return (Resolve-Path -LiteralPath $RestoreOutZip).Path
    }

    $PhysicalBaseItemZip = New-BaseItemZipFromPhysicalRestore -OutputZip $RestoreOutZip
    if (-not [string]::IsNullOrWhiteSpace($PhysicalBaseItemZip)) {
        return $PhysicalBaseItemZip
    }

    throw "当前 BaseItemTypes 或 Words 已包含物价补丁标记，并且没有找到兼容的干净还原包。请先运行一键还原，或让官方启动器完成更新/修复游戏文件后重新运行一键更新。"
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

function Test-PricePatchZipCompatible {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ReferenceDat
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_cached_patch_", [Guid]::NewGuid().ToString("N"), ".datc64"))
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        Get-Poe2ZipEntryCrc32Map -Path $Path | Out-Null
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try {
            $Entry = $Archive.GetEntry($InstallInfo.TcBaseItemsPath)
            if ($null -eq $Entry -or $Entry.Length -le 1048576) {
                return $false
            }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
        }
        finally {
            $Archive.Dispose()
        }
        return (Test-BaseItemsCompatible -LeftDat $TempDat -RightDat $ReferenceDat)
    }
    catch {
        Write-Warning "缓存补丁兼容性检查失败：$($_.Exception.Message)"
        return $false
    }
    finally {
        if (Test-Path -LiteralPath $TempDat -PathType Leaf) {
            Remove-Item -LiteralPath $TempDat -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-CorePricePatchFromCache {
    param(
        [Parameter(Mandatory = $true)][string]$CacheZip,
        [Parameter(Mandatory = $true)][string]$OutputZip
    )

    $TempDat = Join-Path $env:TEMP ([string]::Concat("poe2_cached_core_", [Guid]::NewGuid().ToString("N"), ".datc64"))
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($CacheZip)
        try {
            $Entry = $Archive.GetEntry(([string]$InstallInfo.TcBaseItemsPath).Replace("\", "/"))
            if ($null -eq $Entry) {
                throw "缓存补丁缺少当前 BaseItemTypes 条目。"
            }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TempDat, $true)
        }
        finally {
            $Archive.Dispose()
        }
        # A cached Words or EndgameMaps table may come from an older game build.
        # Repackage only the structurally checked BaseItemTypes layer so a
        # degraded update never overwrites the user's current optional tables.
        New-BaseItemZip -SourceDat $TempDat -OutputZip $OutputZip
        Get-Poe2ZipEntryCrc32Map -Path $OutputZip | Out-Null
        return (Resolve-Path -LiteralPath $OutputZip).Path
    }
    finally {
        if (Test-Path -LiteralPath $TempDat -PathType Leaf) {
            Remove-Item -LiteralPath $TempDat -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-JsonAtomically {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $Directory = Split-Path -Parent $FullPath
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    $TempPath = Join-Path $Directory ([string]::Concat(".", (Split-Path -Leaf $FullPath), ".json-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Json = $Value | ConvertTo-Json -Depth 20
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($TempPath, $Json, $Utf8NoBom)
        Move-Poe2FileAtomically -Source $TempPath -Destination $FullPath | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempPath -PathType Leaf) {
            Remove-Item -LiteralPath $TempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-CoreOnlyPriceBuildArgs {
    param([Parameter(Mandatory = $true)][object[]]$ArgumentList)

    $OptionsWithValues = @(
        "--en-words",
        "--tc-words",
        "--unique-gold-prices",
        "--patched-words",
        "--words-game-path"
    )
    $Result = New-Object System.Collections.Generic.List[object]
    for ($Index = 0; $Index -lt $ArgumentList.Count; $Index++) {
        $Value = [string]$ArgumentList[$Index]
        if ($Value -in $OptionsWithValues) {
            $Index += 1
            continue
        }
        if ($Value -eq "--no-uniques") {
            continue
        }
        if ($Value -eq "--patch-scope" -and ($Index + 1) -lt $ArgumentList.Count) {
            $Result.Add($Value)
            $Scope = [string]$ArgumentList[$Index + 1]
            $Result.Add($(if ($Scope -eq "uniques") { "none" } else { $Scope }))
            $Index += 1
            continue
        }
        $Result.Add($ArgumentList[$Index])
    }
    $Result.Add("--no-uniques")
    return $Result.ToArray()
}

function Publish-PriceBuildStage {
    param(
        [Parameter(Mandatory = $true)][string]$StageDir,
        [Parameter(Mandatory = $true)][string]$DestinationDir
    )

    $StageRoot = (Resolve-Path -LiteralPath $StageDir).Path
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    foreach ($File in @(Get-ChildItem -LiteralPath $StageRoot -Recurse -File -ErrorAction Stop)) {
        $Relative = $File.FullName.Substring($StageRoot.Length).TrimStart(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        $Destination = Join-Path $DestinationDir $Relative
        Copy-Poe2FileAtomically -Source $File.FullName -Destination $Destination | Out-Null
    }
}

function Assert-GgpkPatchApplied {
    param([Parameter(Mandatory = $true)][string]$ZipPath)

    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe2_verify_ggpk_", [Guid]::NewGuid().ToString("N")))
    $ExpectedDir = Join-Path $TempRoot "expected"
    $ActualDir = Join-Path $TempRoot "actual"
    $LogPath = Join-Path $TempRoot "extract.log"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        New-Item -ItemType Directory -Force -Path $ExpectedDir, $ActualDir | Out-Null
        $Targets = [ordered]@{
            $InstallInfo.TcBaseItemsPath = $InstallInfo.LanguageFileSlug
            $InstallInfo.TcWordsPath = $InstallInfo.WordsFileSlug
            $InstallInfo.TcEndgameMapsPath = $InstallInfo.EndgameMapsFileSlug
        }
        $ExpectedByEntry = @{}
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            foreach ($EntryName in $Targets.Keys) {
                $Entry = $Archive.GetEntry(([string]$EntryName).Replace("\", "/"))
                if ($null -eq $Entry) {
                    continue
                }
                $ExpectedPath = Join-Path $ExpectedDir ([Guid]::NewGuid().ToString("N") + ".datc64")
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $ExpectedPath, $true)
                $ExpectedByEntry[[string]$EntryName] = $ExpectedPath
            }
        }
        finally {
            $Archive.Dispose()
        }
        if ($ExpectedByEntry.Count -eq 0) {
            throw "GGPK 写入校验找不到任何目标 DAT 条目。"
        }

        if ($ExtractorUsesDotnet) {
            $Result = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($Extractor, $ContentGgpk, $ActualDir) -Quiet
            $Result.Text | Out-File -LiteralPath $LogPath -Encoding UTF8
            $ExitCode = $Result.ExitCode
            $ExtractText = $Result.Text
        }
        else {
            & $Extractor $ContentGgpk $ActualDir *> $LogPath
            $ExitCode = $LASTEXITCODE
            $ExtractText = if (Test-Path -LiteralPath $LogPath -PathType Leaf) { Get-Content -LiteralPath $LogPath -Raw -Encoding UTF8 } else { "" }
        }
        if ($ExitCode -ne 0 -or (Test-ToolOutputFailure -Text $ExtractText -ExtraNeedles @("Fatal:"))) {
            throw "GGPK 写入后读回提取失败。退出码：$ExitCode；日志：$LogPath"
        }
        foreach ($EntryName in $ExpectedByEntry.Keys) {
            $ActualPath = Join-Path $ActualDir ("data\" + [string]$Targets[$EntryName])
            Assert-File $ActualPath "GGPK read-back $EntryName"
            $ExpectedHash = (Get-FileHash -LiteralPath $ExpectedByEntry[$EntryName] -Algorithm SHA256).Hash
            $ActualHash = (Get-FileHash -LiteralPath $ActualPath -Algorithm SHA256).Hash
            if ($ExpectedHash -ne $ActualHash) {
                throw "GGPK 写入后读回内容不一致：$EntryName"
            }
        }
        Write-Host "已校验 GGPK 中的 $($ExpectedByEntry.Count) 个补丁文件。" -ForegroundColor Green
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
$PatchScope = Resolve-PatchScope -Requested $PatchScope
$PatchUniqueWordsEnabled = ($PatchScope -in @("all", "uniques"))
$PatchPriceFetchEnabled = ($PatchScope -in @("all", "currency", "uniques"))
$PatchIslandRumourHintsEnabled = Resolve-IslandRumourHints -Requested:$IslandRumourHints
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
$TcEndgameMaps = Join-Path $LatestDir ("data\" + $InstallInfo.EndgameMapsFileSlug)
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
$PersistentRestoreDir = Join-Path $Poe2Dir ".poe2-price-patch"
$PersistentPhysicalRestoreZip = Join-Path $PersistentRestoreDir $PhysicalRestoreZipName
$PricePatchZipName = Get-Poe2PatchName "PricePatchZip"
$PatchZip = Join-Path $OutDir $PricePatchZipName
$PatchedDat = Join-Path $OutDir "baseitemtypes.patched.datc64"
$PatchedWords = Join-Path $OutDir "words.patched.datc64"
$PatchedEndgameMaps = Join-Path $OutDir "endgamemaps.patched.datc64"
$ReportJson = Join-Path $OutDir "price_patch.report.json"
$IslandRumourReportJson = Join-Path $OutDir "island_rumour_patch.report.json"
$SummaryJson = Join-Path $OutDir "summary.json"
$PriceBuildLog = Join-Path $OutDir "price_patch_build.log"
$PriceCacheDir = Join-Path $RepoRoot "output\price_patch_cache"
$EnglishBaseItemsUnavailable = $false
$EnglishWordsUnavailable = $false

Write-Host "POE2 物价补丁更新器 $script:PatchVersion" -ForegroundColor Green
Write-Host "游戏目录：$Poe2Dir"
Write-Host "补丁目录：$RepoRoot"
Write-Host "检测结果：$($InstallInfo.DisplayName)" -ForegroundColor Cyan
Write-Host "安装模式：$GameMode" -ForegroundColor Cyan
Write-Host "游戏语言：$DisplayLanguageName ($($InstallInfo.ConfigLanguage))" -ForegroundColor Cyan
Write-Host "写入目标：$($InstallInfo.TcBaseItemsPath)" -ForegroundColor Cyan
Write-Host "通货价格补丁：$(if ($PatchScope -in @('all', 'currency')) { '开启' } else { '关闭' })" -ForegroundColor Cyan
Write-Host "传奇装备价格补丁：$(if ($PatchUniqueWordsEnabled) { '开启' } else { '关闭' })" -ForegroundColor Cyan
Write-Host "岛屿传言补丁：$(if ($PatchIslandRumourHintsEnabled) { '开启' } else { '关闭' })" -ForegroundColor Cyan
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
if ($PatchIslandRumourHintsEnabled) {
    Assert-File (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py") "island rumour patch script"
}
if ($GameMode -eq "Bundles2" -and -not $NoInstall -and -not $NoOpenTool) {
    # Fail before extraction/backup so a running game cannot produce a mixed-state restore package.
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin
}
$Dotnet = Ensure-DotNet8Runtime -RepoRoot $RepoRoot
if (-not $NoInstall -and -not $NoOpenTool) {
    Stop-LegacyInstallerProcesses
    Remove-LegacyFiles -IncludeGameFiles
}
else {
    Write-Host "本次不会写入游戏，已跳过旧安装器终止和游戏目录清理。" -ForegroundColor Yellow
}

if (-not $SkipExtract) {
    New-Item -ItemType Directory -Force -Path $LatestDir | Out-Null

    if ($GameMode -eq "GGPK") {
        Write-Step "从 Content.ggpk 提取最新 BaseItemTypes"
        $ExtractStartedAt = (Get-Date).AddSeconds(-2)
        try {
            if ($ExtractorUsesDotnet) {
                $ExtractorResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($Extractor, $ContentGgpk, $LatestDir) -Quiet
                $ExtractorResult.Text | Out-File -LiteralPath $ExtractLog -Encoding UTF8
                $ExtractorExitCode = $ExtractorResult.ExitCode
                $ExtractorText = $ExtractorResult.Text
            }
            else {
                & $Extractor $ContentGgpk $LatestDir *> $ExtractLog
                $ExtractorExitCode = $LASTEXITCODE
                $ExtractorText = if (Test-Path -LiteralPath $ExtractLog -PathType Leaf) {
                    Get-Content -LiteralPath $ExtractLog -Raw -Encoding UTF8
                }
                else {
                    ""
                }
            }
            if ($ExtractorExitCode -ne 0 -or (Test-ToolOutputFailure -Text $ExtractorText -ExtraNeedles @("Fatal:"))) {
                if (Test-GgpkExtractorMissingRuntimeDependency -Text $ExtractorText) {
                    throw "GGPKExtractor missing VC runtime dependency. Exit code: $ExtractorExitCode. Log: $ExtractLog"
                }
                throw "GGPKExtractor failed. Exit code: $ExtractorExitCode. Log: $ExtractLog"
            }
            $RequiredExtractedFiles = @($EnBaseItems, $TcBaseItems) | Select-Object -Unique
            foreach ($RequiredExtractedFile in $RequiredExtractedFiles) {
                if (-not (Test-Path -LiteralPath $RequiredExtractedFile -PathType Leaf)) {
                    throw "GGPKExtractor did not refresh required file: $RequiredExtractedFile. Log: $ExtractLog"
                }
                $RequiredFileInfo = Get-Item -LiteralPath $RequiredExtractedFile
                if ($RequiredFileInfo.LastWriteTime -lt $ExtractStartedAt) {
                    throw "GGPKExtractor did not refresh required file: $RequiredExtractedFile. Log: $ExtractLog"
                }
            }
            Write-Host "已提取到：$LatestDir"
        }
        catch {
            Write-Warning "提取失败：$($_.Exception.Message)"
            Write-Warning "如果游戏或启动器还在运行，请完全关闭后重新运行一键更新。"
            Write-Warning "为避免误用旧缓存，本次不会自动改用 dat_files_latest；如确实要使用缓存，请显式传入 -SkipExtract。"
            throw
        }
    }
    else {
        Write-Step "使用 BundleExtractor 从 Bundles2 提取最新 BaseItemTypes"

        $DestDir = Join-Path $LatestDir "data"
        New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

        Write-Host "正在提取英文 BaseItemTypes..."
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.EnBaseItemsPath $EnBaseItems
        if ($LASTEXITCODE -ne 0) {
            if ($IsChinaClient) {
                $EnglishBaseItemsUnavailable = $true
                if (Test-Path -LiteralPath $EnBaseItems -PathType Leaf) {
                    Remove-Item -LiteralPath $EnBaseItems -Force
                }
                Write-Warning "国服 Bundles2 未包含英文 BaseItemTypes，将改用 Poe2DB Economy 做国际服价格参考。退出码：$LASTEXITCODE"
            }
            else {
                throw "Failed to extract English BaseItemTypes. Exit code: $LASTEXITCODE"
            }
        }
        else {
            Write-Host "已提取到：$EnBaseItems"
        }

        Write-Host "正在提取$DisplayLanguageName BaseItemTypes..."
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.TcBaseItemsPath $TcBaseItems
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract $($InstallInfo.LanguageName) BaseItemTypes. Exit code: $LASTEXITCODE"
        }
        Write-Host "已提取到：$TcBaseItems"

        Write-Host "正在提取$DisplayLanguageName EndgameMaps..."
        if (Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf) {
            Remove-Item -LiteralPath $TcEndgameMaps -Force
        }
        & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $InstallInfo.TcEndgameMapsPath $TcEndgameMaps
        if ($LASTEXITCODE -ne 0) {
            if ($PatchIslandRumourHintsEnabled) {
                throw "Failed to extract $($InstallInfo.LanguageName) EndgameMaps. Exit code: $LASTEXITCODE"
            }
            Write-Warning "EndgameMaps 提取失败，将无法清理旧岛屿传言提示。退出码：$LASTEXITCODE"
        }
        else {
            Write-Host "已提取到：$TcEndgameMaps"
        }

        if ($SupportsUniqueWords) {
            Write-Host "正在提取英文 Words..."
            & $BundledBundleExtractorExe $Bundles2Paths.IndexBin "data/balance/words.datc64" $EnWords
            if ($LASTEXITCODE -ne 0) {
                if ($IsChinaClient) {
                    $EnglishWordsUnavailable = $true
                    if (Test-Path -LiteralPath $EnWords -PathType Leaf) {
                        Remove-Item -LiteralPath $EnWords -Force
                    }
                    Write-Warning "国服 Bundles2 未包含英文 Words，将跳过依赖英文 Words 的传奇英文兜底。退出码：$LASTEXITCODE"
                }
                else {
                    throw "Failed to extract English Words. Exit code: $LASTEXITCODE"
                }
            }
            else {
                Write-Host "已提取到：$EnWords"
            }

            Write-Host "正在提取$DisplayLanguageName Words..."
            & $BundledBundleExtractorExe $Bundles2Paths.IndexBin $TcWordsPath $TcWords
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to extract $($InstallInfo.LanguageName) Words. Exit code: $LASTEXITCODE"
            }
            Write-Host "已提取到：$TcWords"

            if ($PatchUniqueWordsEnabled) {
                Write-Host "正在提取 UniqueGoldPrices..."
                & $BundledBundleExtractorExe $Bundles2Paths.IndexBin "data/balance/uniquegoldprices.datc64" $UniqueGoldPrices
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to extract UniqueGoldPrices. Exit code: $LASTEXITCODE"
                }
                Write-Host "已提取到：$UniqueGoldPrices"
            }
            else {
                Write-Host "当前选择只打通货补丁，已跳过 UniqueGoldPrices 提取。" -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "当前语言不支持传奇物品 Words 提取，已跳过。语言：$DisplayLanguageName" -ForegroundColor Yellow
        }
    }
}
else {
    Write-Step "跳过提取，使用已有 BaseItemTypes"
}

if ($IsChinaClient -and -not (Test-Path -LiteralPath $EnBaseItems -PathType Leaf)) {
    $EnglishBaseItemsUnavailable = $true
}
if (-not ($IsChinaClient -and $EnglishBaseItemsUnavailable)) {
    Assert-File $EnBaseItems "English BaseItemTypes"
}
elseif (Test-Path -LiteralPath $EnBaseItems -PathType Leaf) {
    Write-Host "已找到英文 BaseItemTypes 缓存，将继续使用本地英文表。" -ForegroundColor Yellow
    $EnglishBaseItemsUnavailable = $false
}
else {
    Write-Host "英文 BaseItemTypes 不可用：国服将使用 Poe2DB Economy 作为国际服参考源。" -ForegroundColor Yellow
}
Assert-File $TcBaseItems "$($InstallInfo.LanguageName) BaseItemTypes"
if ($PatchIslandRumourHintsEnabled) {
    Assert-File $TcEndgameMaps "$($InstallInfo.LanguageName) EndgameMaps"
}
$CanPatchUniqueWords = (
    $PatchUniqueWordsEnabled -and
    $SupportsUniqueWords -and
    (Test-Path -LiteralPath $EnWords -PathType Leaf) -and
    (Test-Path -LiteralPath $TcWords -PathType Leaf) -and
    (Test-Path -LiteralPath $UniqueGoldPrices -PathType Leaf)
)
if ($PatchUniqueWordsEnabled -and $SupportsUniqueWords -and -not $CanPatchUniqueWords) {
    Write-Warning "传奇物品价格标记已禁用：Words 或 UniqueGoldPrices datc64 文件没有成功提取。"
}
elseif ($PatchUniqueWordsEnabled -and -not $SupportsUniqueWords) {
    Write-Warning "传奇物品价格标记已禁用：当前语言没有受支持的 Words.datc64 路径。"
}
$SourceBaseItemsLooksPatched = Test-BaseItemsLookPatched $TcBaseItems
$SourceWordsLooksPatched = $false
if ($SupportsUniqueWords -and (Test-Path -LiteralPath $TcWords -PathType Leaf)) {
    $SourceWordsLooksPatched = Test-WordsLookPatched $TcWords
}
if ($SourceBaseItemsLooksPatched -and $GameMode -eq "Bundles2") {
    Write-Host "当前 BaseItemTypes 已包含物价标记，将保留当前 Bundles2 底板并只替换物价层。" -ForegroundColor Yellow
}
if ($SupportsUniqueWords -and $SourceWordsLooksPatched -and $GameMode -eq "Bundles2") {
    Write-Host "当前 Words.datc64 已包含传奇价格标记，将在生成补丁时清理并重打。" -ForegroundColor Yellow
}
$SourceEndgameMapsLooksPatched = $false
if (Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf) {
    $SourceEndgameMapsLooksPatched = Test-EndgameMapsLookPatched $TcEndgameMaps
}
if ($PatchIslandRumourHintsEnabled -and $SourceEndgameMapsLooksPatched -and $GameMode -eq "Bundles2") {
    Write-Host "当前 EndgameMaps.datc64 已包含岛屿传言提示，将在生成补丁时清理并重打。" -ForegroundColor Yellow
}
$CanPatchUniqueWords = (
    $PatchUniqueWordsEnabled -and
    $SupportsUniqueWords -and
    (Test-Path -LiteralPath $EnWords -PathType Leaf) -and
    (Test-Path -LiteralPath $TcWords -PathType Leaf) -and
    (Test-Path -LiteralPath $UniqueGoldPrices -PathType Leaf)
)
$BuildPatchScope = $PatchScope
if ($PatchScope -eq "uniques" -and -not $CanPatchUniqueWords) {
    Write-Warning "传奇装备价格补丁不可用：Words 或 UniqueGoldPrices datc64 文件没有成功提取。本次将只清理旧价格标记并继续。"
    $BuildPatchScope = "none"
}
$PatchBuildMode = "append"
if (-not [string]::IsNullOrWhiteSpace($env:POE2_PATCH_BUILD_MODE)) {
    $PatchBuildMode = $env:POE2_PATCH_BUILD_MODE.Trim().ToLowerInvariant()
    if ($PatchBuildMode -notin @("append", "fixed")) {
        throw "Invalid POE2_PATCH_BUILD_MODE '$($env:POE2_PATCH_BUILD_MODE)'. Use append or fixed."
    }
}
$PriceCacheKey = [string]::Concat(
    ($InstallInfo.InstallKind -replace '[^A-Za-z0-9._-]', '_'),
    "_",
    ($InstallInfo.LanguageFileSlug -replace '[^A-Za-z0-9._-]', '_'),
    "_",
    ($BuildPatchScope -replace '[^A-Za-z0-9._-]', '_'),
    "_mode-",
    ($PatchBuildMode -replace '[^A-Za-z0-9._-]', '_'),
    "_unique-",
    $(if ($CanPatchUniqueWords) { "on" } else { "off" }),
    "_island-",
    $(if ($PatchIslandRumourHintsEnabled) { "on" } else { "off" })
)
$CachedPatchZip = Join-Path $PriceCacheDir ($PriceCacheKey + ".zip")
$CachedSummaryJson = Join-Path $PriceCacheDir ($PriceCacheKey + ".summary.json")
Compact-LatestBaseItems $LatestDir @($EnBaseItems, $TcBaseItems, $EnWords, $TcWords, $TcEndgameMaps, $UniqueGoldPrices)
$LogicalRestoreReady = $false
$InstallSuppressedReason = ""
try {
    $RestoreZip = Ensure-RestoreZip $TcBaseItems
    if (-not ([bool]$InstallInfo.IsChina -or [string]$InstallInfo.InstallKind -like "CN-*") -and -not (Test-BaseItemsLookPatched $TcBaseItems)) {
        $RestoreZip = Update-IntlRestoreZipFromExtractedBaseItems -ZipPath $RestoreZip
    }
    if ($RestoreZip -ne $RestorePatchFolderZip) {
        Copy-Poe2FileAtomically -Source $RestoreZip -Destination $RestorePatchFolderZip | Out-Null
    }
    $LogicalRestoreReady = $true
}
catch {
    $RestoreFailure = $_.Exception.Message
    if ($GameMode -eq "GGPK" -and -not $NoInstall -and -not $NoOpenTool) {
        $InstallSuppressedReason = "无法构建或验证兼容的 GGPK 还原包：$RestoreFailure"
        $NoInstall = $true
        Write-Warning "$InstallSuppressedReason。将继续生成补丁，但保持 Content.ggpk 原状。"
    }
    else {
        Write-Warning "刷新逻辑还原包失败，将继续生成补丁并保留现有游戏状态。原因：$RestoreFailure"
    }
}
if ($GameMode -eq "Bundles2" -and -not $NoInstall -and -not $NoOpenTool) {
    # A physical write without a verified rollback package is never safe.
    $PhysicalRestoreZip = Ensure-PhysicalRestoreZip -SourceLooksPatched ($SourceBaseItemsLooksPatched -or $SourceWordsLooksPatched -or $SourceEndgameMapsLooksPatched)
    Write-Host "真实还原包：" -ForegroundColor Green
    Write-Host "  $PhysicalRestoreZip"
}
elseif ($GameMode -eq "Bundles2") {
    Write-Host "本次不会写入游戏，已跳过真实还原包的创建与替换。" -ForegroundColor Yellow
}

if ($BuildPatchScope -in @("all", "currency", "uniques")) {
    Write-Step "获取 $PriceSourceName 价格并生成补丁包"
}
else {
    Write-Step "清理未勾选价格标记并生成补丁包"
}
$Python = Ensure-PythonRequests -RepoRoot $RepoRoot
Write-Host "补丁模式：$PatchBuildMode" -ForegroundColor Cyan
$BuildStageDir = Join-Path $RepoRoot ([string]::Concat("output\.price-build-", [Guid]::NewGuid().ToString("N")))
$StagePatchZip = Join-Path $BuildStageDir $PricePatchZipName
$StagePatchedDat = Join-Path $BuildStageDir "baseitemtypes.patched.datc64"
$StagePatchedWords = Join-Path $BuildStageDir "words.patched.datc64"
$StagePatchedEndgameMaps = Join-Path $BuildStageDir "endgamemaps.patched.datc64"
$StageReportJson = Join-Path $BuildStageDir "price_patch.report.json"
$StageIslandReportJson = Join-Path $BuildStageDir "island_rumour_patch.report.json"
$StageSummaryJson = Join-Path $BuildStageDir "summary.json"
$StagePriceBuildLog = Join-Path $BuildStageDir "price_patch_build.log"
$BuildArgs = @(
    (Join-Path $CodeToolsRoot "build_poe2scout_price_patch.py"),
    "--en-baseitems", $EnBaseItems,
    "--tc-baseitems", $TcBaseItems,
    "--out-dir", $BuildStageDir,
    "--output-zip", $StagePatchZip,
    "--patch-script", (Join-Path $CodeToolsRoot "poe2_name_price_patch.py"),
    "--mode", $PatchBuildMode,
    "--patch-scope", $BuildPatchScope,
    "--patched-dat", $StagePatchedDat,
    "--report", $StageReportJson,
    "--game-path", $InstallInfo.TcBaseItemsPath
)
if ($CanPatchUniqueWords) {
    $BuildArgs += @(
        "--en-words", $EnWords,
        "--tc-words", $TcWords,
        "--unique-gold-prices", $UniqueGoldPrices,
        "--patched-words", $StagePatchedWords,
        "--words-game-path", $TcWordsPath
    )
}
else {
    if ($SupportsUniqueWords -and (Test-Path -LiteralPath $TcWords -PathType Leaf)) {
        $BuildArgs += @(
            "--tc-words", $TcWords,
            "--patched-words", $StagePatchedWords,
            "--words-game-path", $TcWordsPath
        )
    }
    $BuildArgs += "--no-uniques"
}
if (-not $NoPoe2dbFallback -and -not $IsChinaClient) {
    $BuildArgs += "--poe2db-fallback"
}
if ($IsChinaClient) {
    $CnReferenceSource = if ($EnglishBaseItemsUnavailable) { "poe2db-economy" } else { "poe2scout" }
    $BuildArgs += @(
        "--price-source", "poecurrency-cn",
        "--poecurrency-summary-url", "https://poecurrency.top/api/summary?version=2",
        "--cn-reference-source", $CnReferenceSource
    )
    if ($EnglishBaseItemsUnavailable) {
        Write-Host "国服国际服参考源：Poe2DB Economy（英文 BaseItemTypes 不可用）" -ForegroundColor Yellow
    }
    else {
        Write-Host "国服国际服参考源：POE2 Scout（本地英文 BaseItemTypes 可用）" -ForegroundColor Cyan
    }
}

$UsingCachedPatch = $false
$PatchFolderZip = Join-Path $RepoRoot $PricePatchZipName
try {
    New-Item -ItemType Directory -Force -Path $BuildStageDir | Out-Null
    $BuildResult = Invoke-Poe2Python -Python $Python -ArgumentList $BuildArgs
    $BuildResult.Text | Out-File -LiteralPath $StagePriceBuildLog -Encoding UTF8
    if ($BuildResult.ExitCode -ne 0 -and $CanPatchUniqueWords) {
        Write-Warning "完整补丁构建失败，正在自动降级为 BaseItemTypes 核心价格层并保留游戏中的 Words。"
        Remove-Item -LiteralPath $BuildStageDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $BuildStageDir | Out-Null
        $CoreBuildArgs = Get-CoreOnlyPriceBuildArgs -ArgumentList $BuildArgs
        $BuildResult = Invoke-Poe2Python -Python $Python -ArgumentList $CoreBuildArgs
        $BuildResult.Text | Out-File -LiteralPath $StagePriceBuildLog -Encoding UTF8
    }
    if ($BuildResult.ExitCode -ne 0) {
        throw "Price fetch or patch build failed. Exit code: $($BuildResult.ExitCode). Log: $StagePriceBuildLog"
    }

    Assert-File $StagePatchZip $PricePatchZipName
    if (-not (Test-PricePatchZipCompatible -Path $StagePatchZip -ReferenceDat $TcBaseItems)) {
        throw "新生成补丁与当前 BaseItemTypes 结构不兼容。"
    }

    if ($PatchIslandRumourHintsEnabled) {
        Write-Step "生成岛屿传言提示补丁"
        $IslandRumourResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
            (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"),
            "build",
            "--source", $TcEndgameMaps,
            "--output-zip", $StagePatchZip,
            "--patched-dat", $StagePatchedEndgameMaps,
            "--game-path", $InstallInfo.TcEndgameMapsPath,
            "--report", $StageIslandReportJson
        )
        if ($IslandRumourResult.ExitCode -ne 0) {
            Write-Warning "岛屿传言提示生成失败，已跳过该功能并继续安装物价补丁。退出码：$($IslandRumourResult.ExitCode)"
        }
    }
    elseif ((Test-Path -LiteralPath $TcEndgameMaps -PathType Leaf) -and $SourceEndgameMapsLooksPatched) {
        Write-Step "清理旧岛屿传言提示"
        $IslandRumourResult = Invoke-Poe2Python -Python $Python -ArgumentList @(
            (Join-Path $CodeToolsRoot "poe2_island_rumour_patch.py"),
            "clean",
            "--source", $TcEndgameMaps,
            "--output-zip", $StagePatchZip,
            "--patched-dat", $StagePatchedEndgameMaps,
            "--game-path", $InstallInfo.TcEndgameMapsPath,
            "--report", $StageIslandReportJson
        )
        if ($IslandRumourResult.ExitCode -ne 0) {
            Write-Warning "清理旧岛屿传言提示失败，将保留游戏中的当前 EndgameMaps 并继续安装其它补丁。退出码：$($IslandRumourResult.ExitCode)"
        }
    }

    Write-Step "发布已验证补丁包"
    Publish-PriceBuildStage -StageDir $BuildStageDir -DestinationDir $OutDir
    Assert-File $PatchZip $PricePatchZipName
    Copy-Poe2FileAtomically -Source $PatchZip -Destination $PatchFolderZip | Out-Null
    try {
        New-Item -ItemType Directory -Force -Path $PriceCacheDir | Out-Null
        Copy-Poe2FileAtomically -Source $PatchZip -Destination $CachedPatchZip | Out-Null
        if (Test-Path -LiteralPath $SummaryJson -PathType Leaf) {
            Copy-Poe2FileAtomically -Source $SummaryJson -Destination $CachedSummaryJson | Out-Null
        }
    }
    catch {
        Write-Warning "保存上次成功补丁缓存失败，但不影响本次安装：$($_.Exception.Message)"
    }
}
catch {
    $BuildFailure = $_.Exception.Message
    $CompatibleFallbackPatch = ""
    try {
        if (
            $BuildPatchScope -in @("all", "currency") -and
            (Test-PricePatchZipCompatible -Path $CachedPatchZip -ReferenceDat $TcBaseItems)
        ) {
            $SafeFallbackZip = Join-Path $BuildStageDir "safe-core-cache.zip"
            $CompatibleFallbackPatch = New-CorePricePatchFromCache `
                -CacheZip $CachedPatchZip `
                -OutputZip $SafeFallbackZip
        }
    }
    catch {
        Write-Warning "兼容缓存准备失败，将保持游戏当前状态：$($_.Exception.Message)"
        $CompatibleFallbackPatch = ""
    }
    if (-not [string]::IsNullOrWhiteSpace($CompatibleFallbackPatch)) {
        $UsingCachedPatch = $true
        $CacheTime = (Get-Item -LiteralPath $CachedPatchZip).LastWriteTime
        Write-Warning "实时构建失败，已自动使用当前范围和模式的兼容核心缓存（$CacheTime）；Words 与 EndgameMaps 保持游戏当前内容。原因：$BuildFailure"
        try {
            Copy-Poe2FileAtomically -Source $CompatibleFallbackPatch -Destination $PatchZip | Out-Null
            Copy-Poe2FileAtomically -Source $CompatibleFallbackPatch -Destination $PatchFolderZip | Out-Null
        }
        catch {
            Write-Warning "兼容缓存无法安全发布，本次未修改游戏文件：$($_.Exception.Message)"
            return
        }
        try {
            Write-JsonAtomically -Path $SummaryJson -Value ([ordered]@{
                    patch_scope = $BuildPatchScope
                    patch_build_mode = $PatchBuildMode
                    cache_fallback = $true
                    cache_key = $PriceCacheKey
                    cache_time_utc = $CacheTime.ToUniversalTime().ToString("o", [System.Globalization.CultureInfo]::InvariantCulture)
                    applied_layers = @("BaseItemTypes")
                    preserved_layers = @("Words", "EndgameMaps")
                    build_failure = $BuildFailure
                })
        }
        catch {
            Write-Warning "写入缓存降级摘要失败，但不影响本次核心补丁：$($_.Exception.Message)"
        }
    }
    else {
        $NoInstall = $true
        Write-Warning "实时构建和兼容缓存均不可用，本次保持游戏与现有补丁原状。原因：$BuildFailure"
        Write-Host "完成：未修改游戏文件。请稍后联网重试；现有已安装补丁不会被空结果覆盖。" -ForegroundColor Yellow
        return
    }
}
finally {
    if (Test-Path -LiteralPath $BuildStageDir -PathType Container) {
        Remove-Item -LiteralPath $BuildStageDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

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

        try {
            Push-Location -LiteralPath $BundledInstallerDir
            try {
                $InstallerResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledPatchDll, $ContentGgpk, $PatchFolderZip) -InputText ""
                if ($InstallerResult.ExitCode -ne 0 -or (Test-ToolOutputFailure -Text $InstallerResult.Text)) {
                    throw "Patch installer failed. Exit code: $($InstallerResult.ExitCode)"
                }
            }
            finally {
                Pop-Location
            }
            Write-Host "正在读回校验 Content.ggpk..." -ForegroundColor Yellow
            Assert-GgpkPatchApplied -ZipPath $PatchFolderZip
        }
        catch {
            $InstallError = $_.Exception.Message
            if (-not $LogicalRestoreReady -or [string]::IsNullOrWhiteSpace($RestoreZip) -or -not (Test-Path -LiteralPath $RestoreZip -PathType Leaf)) {
                throw "GGPK 写入或校验失败，且没有可用还原包：$InstallError"
            }
            Write-Warning "GGPK 写入或校验失败，正在自动写回已验证还原包。原因：$InstallError"
            Push-Location -LiteralPath $BundledInstallerDir
            try {
                $RollbackResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledPatchDll, $ContentGgpk, $RestoreZip) -InputText ""
                if ($RollbackResult.ExitCode -ne 0 -or (Test-ToolOutputFailure -Text $RollbackResult.Text)) {
                    throw "GGPK 自动还原失败。退出码：$($RollbackResult.ExitCode)"
                }
            }
            finally {
                Pop-Location
            }
            Assert-GgpkPatchApplied -ZipPath $RestoreZip
            Write-Warning "本次补丁未安装，但 Content.ggpk 已自动恢复并通过读回校验。"
            return
        }
        Write-Host "补丁已写入 Content.ggpk。" -ForegroundColor Green
    }
    else {
        Write-Step "使用 PatchBundle3 写入补丁到 Bundles2"
        Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin

        $UsePatchBundleDll = Test-Path -LiteralPath $BundledBundlePatchDll -PathType Leaf
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
            $BundledBundlePatchExe = Join-Path $CodeToolsRoot "PatchBundle3.exe"
        }
        if (-not $UsePatchBundleDll -and -not (Test-Path -LiteralPath $BundledBundlePatchExe -PathType Leaf)) {
            throw "Missing PatchBundle3.dll or PatchBundle3.exe: $BundledBundlePatchDll"
        }

        $TempPatchZip = $PatchZip
        # PatchBundle3 only redirects records present in this ZIP; untouched
        # FileRecords (including other LibGGPK3 patches) remain referenced by the
        # index. Repacking every existing entry here duplicated their bytes on
        # every update and made the write appear to hang on large installations.

        if ([string]::IsNullOrWhiteSpace($PhysicalRestoreZip) -or -not (Test-Path -LiteralPath $PhysicalRestoreZip -PathType Leaf)) {
            throw "写入 Bundles2 前找不到已验证的真实还原包，已安全中止。"
        }
        Write-Host "写入前正在复验真实还原包与当前官方底板..." -ForegroundColor Yellow
        $PhysicalRestoreManifest = Assert-Poe2PhysicalRestoreZip -Path $PhysicalRestoreZip -Poe2Dir $Poe2Dir -InstallInfo $InstallInfo
        if ($null -ne $PhysicalRestoreManifest.write_precondition) {
            Assert-Poe2Bundles2MutationFingerprintCurrent `
                -Expected $PhysicalRestoreManifest.write_precondition `
                -Bundles2Dir $Bundles2Paths.Bundles2Dir | Out-Null
        }
        else {
            Write-Warning "真实还原包来自旧版本，缺少完整 Bundles2 写入前状态指纹；本次仍使用官方底板和文件锁兼容校验。"
        }
        # The merge and full backup verification can both take time.  Re-check the
        # game process and exclusive index access immediately before PatchBundle3.
        Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir -IndexPath $Bundles2Paths.IndexBin

        if ($UsePatchBundleDll) {
            Write-Host "Bundle3 工具：$($BundledBundlePatchDll)"
        }
        else {
            Write-Host "Bundle3 工具：$($BundledBundlePatchExe)"
        }
        Write-Host "索引文件：$($Bundles2Paths.IndexBin)"
        Write-Host "补丁包  ：$TempPatchZip"

        try {
            Push-Location -LiteralPath $BundledInstallerDir
            try {
                if ($UsePatchBundleDll) {
                    $BundlePatchResult = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($BundledBundlePatchDll, $Bundles2Paths.IndexBin, $TempPatchZip) -InputText "" -Quiet
                    $BundlePatchOutput = $BundlePatchResult.Lines
                    $BundlePatchExitCode = $BundlePatchResult.ExitCode
                }
                else {
                    $BundlePatchOutput = & $BundledBundlePatchExe $Bundles2Paths.IndexBin $TempPatchZip 2>&1
                    $BundlePatchExitCode = $LASTEXITCODE
                }
            }
            finally {
                Pop-Location
            }

            $BundlePatchOutput | ForEach-Object { Write-Host $_ }
            $BundlePatchText = ($BundlePatchOutput | Out-String)
            if ($BundlePatchExitCode -ne 0 -or (Test-ToolOutputFailure -Text $BundlePatchText -ExtraNeedles @("FileNotFound", "Could not load"))) {
                throw "PatchBundle3 failed. Exit code: $BundlePatchExitCode"
            }

            Write-Host "正在校验 Bundles2 写入结果..." -ForegroundColor Yellow
            Assert-Bundles2PatchApplied -ZipPath $TempPatchZip -EntryNames @(
                $InstallInfo.TcBaseItemsPath,
                $TcWordsPath,
                $InstallInfo.TcEndgameMapsPath
            )
            Write-Host "补丁已写入 Bundles2。" -ForegroundColor Green
        }
        catch {
            $PatchError = $_.Exception.Message
            Write-Warning "Bundles2 写入或读回校验失败，正在自动恢复更新前状态。原因：$PatchError"
            $RestoreScriptPath = Join-Path $CodeToolsRoot "restore_price_patch.ps1"
            Assert-File $RestoreScriptPath "restore_price_patch.ps1"
            $RollbackOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RestoreScriptPath `
                -Poe2Dir $Poe2Dir `
                -PhysicalRestoreZip $PhysicalRestoreZip 2>&1
            $RollbackExitCode = $LASTEXITCODE
            $RollbackOutput | ForEach-Object { Write-Host $_ }
            if ($RollbackExitCode -ne 0) {
                throw "Bundles2 写入失败，自动恢复也失败。原始错误：$PatchError；还原退出码：$RollbackExitCode"
            }
            Write-Warning "本次补丁未安装，但 Bundles2 已自动恢复到更新前状态。"
            return
        }
    }
}
else {
    if (-not [string]::IsNullOrWhiteSpace($InstallSuppressedReason)) {
        Write-Host "已跳过写入游戏文件：$InstallSuppressedReason" -ForegroundColor Yellow
    }
    else {
        Write-Host "已跳过写入游戏文件，仅生成补丁包。" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "完成。" -ForegroundColor Green
}
catch {
    Write-FriendlyFailure -ErrorRecord $_
    exit 1
}
