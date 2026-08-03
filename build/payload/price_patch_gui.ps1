param(
    [ValidateSet("select", "update", "restore")]
    [string]$Mode = "select",
    [switch]$ConstructOnly,
    [switch]$SkipSystemGameDiscovery
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

. (Join-Path $PSScriptRoot "poe2_patch_common.ps1")
. (Join-Path $PSScriptRoot "poe_patch_profiles.ps1")

$script:PatchVersion = "v0.5.0"
$PreferredRoot = if ([string]::IsNullOrWhiteSpace($env:POE2_PATCH_ROOT)) {
    Split-Path -Parent (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    Split-Path -Parent (Resolve-Path -LiteralPath $env:POE2_PATCH_ROOT).Path
}

function Show-PoePatchLauncherDialog {
    param(
        [ValidateSet("select", "update", "restore")]
        [string]$Operation = "select",
        [string]$PreferredGameRoot = "",
        [switch]$ConstructOnly,
        [switch]$SkipSystemGameDiscovery
    )

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $Form = New-Object System.Windows.Forms.Form
    $Form.Text = "POE 物价补丁 $script:PatchVersion"
    $Form.StartPosition = "CenterScreen"
    $Form.FormBorderStyle = "FixedDialog"
    $Form.MaximizeBox = $false
    $Form.MinimizeBox = $false
    $Form.TopMost = $true
    $Form.BackColor = [System.Drawing.Color]::FromArgb(246, 246, 243)
    $Form.ForeColor = [System.Drawing.Color]::FromArgb(32, 35, 38)
    $Form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
    $Form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
    $InitialOperation = if ($Operation -eq "restore") { "restore" } else { "update" }
    $OperationState = [pscustomobject]@{
        Value = $InitialOperation
        CanChange = ($Operation -eq "select")
    }
    $Form.ClientSize = New-Object System.Drawing.Size(720, 610)

    $Accent = [System.Drawing.Color]::FromArgb(30, 105, 92)
    $AccentDark = [System.Drawing.Color]::FromArgb(23, 81, 72)
    $Muted = [System.Drawing.Color]::FromArgb(100, 105, 110)
    $ErrorColor = [System.Drawing.Color]::FromArgb(170, 48, 48)
    $BorderColor = [System.Drawing.Color]::FromArgb(205, 207, 203)
    $PanelColor = [System.Drawing.Color]::White

    $Header = New-Object System.Windows.Forms.Panel
    $Header.Location = New-Object System.Drawing.Point(0, 0)
    $Header.Size = New-Object System.Drawing.Size(720, 82)
    $Header.BackColor = [System.Drawing.Color]::FromArgb(38, 42, 45)
    $Form.Controls.Add($Header)

    $Title = New-Object System.Windows.Forms.Label
    $Title.Text = "POE 物价补丁"
    $Title.AutoSize = $true
    $Title.Location = New-Object System.Drawing.Point(24, 15)
    $Title.ForeColor = [System.Drawing.Color]::White
    $Title.Font = New-Object System.Drawing.Font($Form.Font.FontFamily, 16, [System.Drawing.FontStyle]::Bold)
    $Header.Controls.Add($Title)

    $VersionLabel = New-Object System.Windows.Forms.Label
    $VersionLabel.Text = $script:PatchVersion
    $VersionLabel.AutoSize = $true
    $VersionLabel.Location = New-Object System.Drawing.Point(646, 23)
    $VersionLabel.ForeColor = [System.Drawing.Color]::FromArgb(230, 174, 83)
    $VersionLabel.Font = New-Object System.Drawing.Font($Form.Font.FontFamily, 9, [System.Drawing.FontStyle]::Bold)
    $Header.Controls.Add($VersionLabel)

    $GameLabel = New-Object System.Windows.Forms.Label
    $GameLabel.Text = "游戏版本"
    $GameLabel.AutoSize = $true
    $GameLabel.Location = New-Object System.Drawing.Point(24, 100)
    $GameLabel.Font = New-Object System.Drawing.Font($Form.Font.FontFamily, 9, [System.Drawing.FontStyle]::Bold)
    $Form.Controls.Add($GameLabel)

    $AutoGameButton = New-Object System.Windows.Forms.RadioButton
    $Poe1GameButton = New-Object System.Windows.Forms.RadioButton
    $Poe2GameButton = New-Object System.Windows.Forms.RadioButton
    $GameButtons = @($AutoGameButton, $Poe1GameButton, $Poe2GameButton)
    $GameTexts = @("自动识别", "POE 1", "POE 2")
    $GameTags = @("auto", "poe1", "poe2")
    for ($Index = 0; $Index -lt $GameButtons.Count; $Index += 1) {
        $Button = $GameButtons[$Index]
        $Button.Text = $GameTexts[$Index]
        $Button.Tag = $GameTags[$Index]
        $Button.Appearance = [System.Windows.Forms.Appearance]::Button
        $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
        $Button.FlatAppearance.BorderColor = $BorderColor
        $Button.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
        $Button.Location = New-Object System.Drawing.Point((24 + 132 * $Index), 124)
        $Button.Size = New-Object System.Drawing.Size(128, 36)
        $Form.Controls.Add($Button)
    }
    $AutoGameButton.Checked = $true

    $PathGroup = New-Object System.Windows.Forms.GroupBox
    $PathGroup.Text = "游戏客户端"
    $PathGroup.Location = New-Object System.Drawing.Point(24, 178)
    $PathGroup.Size = New-Object System.Drawing.Size(672, 184)
    $PathGroup.BackColor = $PanelColor
    $Form.Controls.Add($PathGroup)

    $AutoPathRadio = New-Object System.Windows.Forms.RadioButton
    $AutoPathRadio.Text = "自动查找"
    $AutoPathRadio.Location = New-Object System.Drawing.Point(18, 26)
    $AutoPathRadio.AutoSize = $true
    $AutoPathRadio.Checked = $true
    $PathGroup.Controls.Add($AutoPathRadio)

    $ManualPathRadio = New-Object System.Windows.Forms.RadioButton
    $ManualPathRadio.Text = "手动选择"
    $ManualPathRadio.Location = New-Object System.Drawing.Point(118, 26)
    $ManualPathRadio.AutoSize = $true
    $PathGroup.Controls.Add($ManualPathRadio)

    $RefreshButton = New-Object System.Windows.Forms.Button
    $RefreshButton.Text = "刷新"
    $RefreshButton.Location = New-Object System.Drawing.Point(570, 20)
    $RefreshButton.Size = New-Object System.Drawing.Size(82, 28)
    $RefreshButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $RefreshButton.FlatAppearance.BorderColor = $BorderColor
    $PathGroup.Controls.Add($RefreshButton)

    $ClientCombo = New-Object System.Windows.Forms.ComboBox
    $ClientCombo.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
    $ClientCombo.Location = New-Object System.Drawing.Point(18, 58)
    $ClientCombo.Size = New-Object System.Drawing.Size(634, 25)
    $ClientCombo.DisplayMember = "Label"
    $PathGroup.Controls.Add($ClientCombo)

    $PathTextBox = New-Object System.Windows.Forms.TextBox
    $PathTextBox.Location = New-Object System.Drawing.Point(18, 98)
    $PathTextBox.Size = New-Object System.Drawing.Size(534, 25)
    $PathTextBox.Enabled = $false
    $PathGroup.Controls.Add($PathTextBox)

    $BrowseButton = New-Object System.Windows.Forms.Button
    $BrowseButton.Text = "浏览..."
    $BrowseButton.Location = New-Object System.Drawing.Point(560, 95)
    $BrowseButton.Size = New-Object System.Drawing.Size(92, 30)
    $BrowseButton.Enabled = $false
    $BrowseButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $BrowseButton.FlatAppearance.BorderColor = $BorderColor
    $PathGroup.Controls.Add($BrowseButton)

    $ToolTip = New-Object System.Windows.Forms.ToolTip
    $ToolTip.SetToolTip($BrowseButton, "浏览游戏根目录")
    $ToolTip.SetToolTip($RefreshButton, "重新扫描已安装的 POE 客户端")

    $PathStatus = New-Object System.Windows.Forms.Label
    $PathStatus.Location = New-Object System.Drawing.Point(18, 137)
    $PathStatus.Size = New-Object System.Drawing.Size(634, 36)
    $PathStatus.AutoEllipsis = $true
    $PathStatus.ForeColor = $Muted
    $PathGroup.Controls.Add($PathStatus)

    $ScopeGroup = New-Object System.Windows.Forms.GroupBox
    $ScopeGroup.Text = "更新内容"
    $ScopeGroup.Location = New-Object System.Drawing.Point(24, 378)
    $ScopeGroup.Size = New-Object System.Drawing.Size(672, 96)
    $ScopeGroup.BackColor = $PanelColor
    $ScopeGroup.Visible = ($OperationState.Value -eq "update")
    $Form.Controls.Add($ScopeGroup)

    $CurrencyCheck = New-Object System.Windows.Forms.CheckBox
    $CurrencyCheck.Text = "通货与普通物品价格"
    $CurrencyCheck.Location = New-Object System.Drawing.Point(18, 29)
    $CurrencyCheck.AutoSize = $true
    $CurrencyCheck.Checked = $true
    $ScopeGroup.Controls.Add($CurrencyCheck)

    $UniqueCheck = New-Object System.Windows.Forms.CheckBox
    $UniqueCheck.Text = "传奇装备价格"
    $UniqueCheck.Location = New-Object System.Drawing.Point(232, 29)
    $UniqueCheck.AutoSize = $true
    $UniqueCheck.Checked = $true
    $ScopeGroup.Controls.Add($UniqueCheck)

    $IslandCheck = New-Object System.Windows.Forms.CheckBox
    $IslandCheck.Text = "岛屿传言提示"
    $IslandCheck.Location = New-Object System.Drawing.Point(418, 29)
    $IslandCheck.AutoSize = $true
    $IslandCheck.Checked = $true
    $ScopeGroup.Controls.Add($IslandCheck)

    $ScopeStatus = New-Object System.Windows.Forms.Label
    $ScopeStatus.Text = ""
    $ScopeStatus.Location = New-Object System.Drawing.Point(18, 61)
    $ScopeStatus.Size = New-Object System.Drawing.Size(634, 22)
    $ScopeStatus.ForeColor = $Muted
    $ScopeGroup.Controls.Add($ScopeStatus)

    $WarningLabel = New-Object System.Windows.Forms.Label
    $WarningLabel.Text = "运行前请关闭游戏和对应启动器；工具会先建立可验证的还原包。"
    $WarningLabel.Location = New-Object System.Drawing.Point(26, 490)
    $WarningLabel.Size = New-Object System.Drawing.Size(660, 24)
    $WarningLabel.ForeColor = [System.Drawing.Color]::FromArgb(121, 82, 31)
    $Form.Controls.Add($WarningLabel)

    $RepositoryLink = New-Object System.Windows.Forms.LinkLabel
    $RepositoryLink.Text = "GitHub：weixiao030/poe2_price"
    $RepositoryLink.Tag = "https://github.com/weixiao030/poe2_price"
    $RepositoryLink.AutoSize = $true
    $RepositoryLink.Location = New-Object System.Drawing.Point(26, 526)
    $RepositoryLink.LinkColor = $Accent
    $Form.Controls.Add($RepositoryLink)

    $CaimoguLink = New-Object System.Windows.Forms.LinkLabel
    $CaimoguLink.Text = "踩蘑菇：caimogu.cc/post/2403703.html"
    $CaimoguLink.Tag = "https://www.caimogu.cc/post/2403703.html"
    $CaimoguLink.AutoSize = $true
    $CaimoguLink.Location = New-Object System.Drawing.Point(286, 526)
    $CaimoguLink.LinkColor = $Accent
    $Form.Controls.Add($CaimoguLink)

    $CancelButton = New-Object System.Windows.Forms.Button
    $CancelButton.Text = "取消"
    $CancelButton.Location = New-Object System.Drawing.Point(330, 556)
    $CancelButton.Size = New-Object System.Drawing.Size(96, 36)
    $CancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $CancelButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $CancelButton.FlatAppearance.BorderColor = $BorderColor
    $Form.Controls.Add($CancelButton)

    $RestoreButton = New-Object System.Windows.Forms.Button
    $RestoreButton.Text = "还原物价补丁"
    $RestoreButton.Location = New-Object System.Drawing.Point(438, 556)
    $RestoreButton.Size = New-Object System.Drawing.Size(96, 36)
    $RestoreButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $RestoreButton.FlatAppearance.BorderColor = $BorderColor
    $RestoreButton.BackColor = $PanelColor
    $RestoreButton.ForeColor = $Form.ForeColor
    $Form.Controls.Add($RestoreButton)

    $StartButton = New-Object System.Windows.Forms.Button
    $StartButton.Text = "开始/更新物价补丁"
    $StartButton.Location = New-Object System.Drawing.Point(546, 556)
    $StartButton.Size = New-Object System.Drawing.Size(150, 36)
    $StartButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $StartButton.FlatAppearance.BorderSize = 0
    $StartButton.BackColor = $Accent
    $StartButton.ForeColor = [System.Drawing.Color]::White
    $Form.Controls.Add($StartButton)
    $Form.AcceptButton = if ($InitialOperation -eq "restore") { $RestoreButton } else { $StartButton }
    $Form.CancelButton = $CancelButton

    $SetOperationLayout = {
        $IsUpdate = ($OperationState.Value -eq "update")
        $ScopeGroup.Visible = $IsUpdate
        $Form.ClientSize = New-Object System.Drawing.Size(720, $(if ($IsUpdate) { 610 } else { 500 }))
        $BottomY = if ($IsUpdate) { 556 } else { 446 }
        $WarningY = if ($IsUpdate) { 490 } else { 382 }
        $LinkY = if ($IsUpdate) { 526 } else { 418 }
        $WarningLabel.Location = New-Object System.Drawing.Point(26, $WarningY)
        $RepositoryLink.Location = New-Object System.Drawing.Point(26, $LinkY)
        $CaimoguLink.Location = New-Object System.Drawing.Point(286, $LinkY)
        $CancelButton.Location = New-Object System.Drawing.Point(330, $BottomY)
        $RestoreButton.Location = New-Object System.Drawing.Point(438, $BottomY)
        $StartButton.Location = New-Object System.Drawing.Point(546, $BottomY)
        $RestoreButton.Enabled = $OperationState.CanChange -or $OperationState.Value -eq "restore"
        $StartButton.Enabled = $OperationState.CanChange -or $OperationState.Value -eq "update"
    }

    $GetRequestedGameVersion = {
        foreach ($Button in $GameButtons) {
            if ($Button.Checked) { return [string]$Button.Tag }
        }
        return "auto"
    }

    $SetStatus = {
        param([string]$Text, [bool]$IsError)
        $PathStatus.Text = $Text
        $PathStatus.ForeColor = if ($IsError) { $ErrorColor } else { $Muted }
    }

    $UpdateGameButtonStyle = {
        foreach ($Button in $GameButtons) {
            if ($Button.Checked) {
                $Button.BackColor = $Accent
                $Button.ForeColor = [System.Drawing.Color]::White
                $Button.FlatAppearance.BorderColor = $AccentDark
            }
            else {
                $Button.BackColor = $PanelColor
                $Button.ForeColor = $Form.ForeColor
                $Button.FlatAppearance.BorderColor = $BorderColor
            }
        }
    }

    $UpdateScopeForGame = {
        $Version = & $GetRequestedGameVersion
        if ($Version -eq "auto" -and $ClientCombo.SelectedItem) {
            $Version = [string]$ClientCombo.SelectedItem.Candidate.GameVersion
        }
        $IslandCheck.Visible = ($Version -ne "poe1")
        if ($Version -eq "poe1") {
            $IslandCheck.Checked = $false
            $ScopeStatus.Text = "POE1 使用混沌石 / 神圣石计价；"
        }
        else {
            $ScopeStatus.Text = "POE2 使用崇高石 / 神圣石计价。"
        }
    }

    $CandidateCache = @{}
    $GetClientShortName = {
        param($Candidate)

        if ([bool]$Candidate.InstallInfo.IsChina) { return "国服" }
        if ([string]$Candidate.InstallInfo.Mode -eq "GGPK") { return "官服" }
        return "国际服"
    }

    $RefreshCandidates = {
        param([bool]$ForceRefresh = $false)

        $PreviousPath = if ($ClientCombo.SelectedItem) { [string]$ClientCombo.SelectedItem.Candidate.Path } else { "" }
        $ClientCombo.Items.Clear()
        $RequestedVersion = & $GetRequestedGameVersion
        $Form.UseWaitCursor = $true
        $RefreshButton.Enabled = $false
        try {
            if ($ForceRefresh) {
                $CandidateCache.Clear()
            }
            if ($CandidateCache.ContainsKey($RequestedVersion)) {
                $Candidates = @($CandidateCache[$RequestedVersion])
            }
            elseif ($RequestedVersion -ne "auto" -and $CandidateCache.ContainsKey("auto")) {
                $Candidates = @($CandidateCache["auto"] | Where-Object {
                        [string]$_.GameVersion -eq $RequestedVersion
                    })
                $CandidateCache[$RequestedVersion] = @($Candidates)
            }
            else {
                $Candidates = @(Get-PoePatchGameDirectoryCandidates `
                        -GameVersion $RequestedVersion `
                        -PreferredRoot $PreferredGameRoot `
                        -SkipSystemGameDiscovery:$SkipSystemGameDiscovery)
                $CandidateCache[$RequestedVersion] = @($Candidates)
                if ($RequestedVersion -eq "auto") {
                    foreach ($Version in @("poe1", "poe2")) {
                        $CandidateCache[$Version] = @($Candidates | Where-Object {
                                [string]$_.GameVersion -eq $Version
                            })
                    }
                }
            }
            foreach ($Candidate in $Candidates) {
                $VersionText = if ($Candidate.GameVersion -eq "poe1") { "POE1" } else { "POE2" }
                $ClientText = & $GetClientShortName $Candidate
                $Item = [pscustomobject]@{
                    Label = "[$VersionText]$ClientText | $($Candidate.Path)"
                    Candidate = $Candidate
                }
                [void]$ClientCombo.Items.Add($Item)
            }
            if ($ClientCombo.Items.Count -eq 0) {
                & $SetStatus "没有找到符合当前版本的客户端，请切换为手动选择。" $true
            }
            else {
                $SelectedIndex = 0
                for ($Index = 0; $Index -lt $ClientCombo.Items.Count; $Index += 1) {
                    if ([string]$ClientCombo.Items[$Index].Candidate.Path -eq $PreviousPath) {
                        $SelectedIndex = $Index
                        break
                    }
                }
                $ClientCombo.SelectedIndex = $SelectedIndex
                if ($ClientCombo.Items.Count -eq 1) {
                    & $SetStatus "已找到 1 个客户端，请确认路径后继续。" $false
                }
                else {
                    & $SetStatus "已找到 $($ClientCombo.Items.Count) 个客户端，请从列表选择本次目标。" $false
                }
            }
        }
        catch {
            & $SetStatus $_.Exception.Message $true
        }
        finally {
            $Form.UseWaitCursor = $false
            $RefreshButton.Enabled = $AutoPathRadio.Checked
        }
        & $UpdateScopeForGame
    }

    foreach ($Button in $GameButtons) {
        $Button.Add_CheckedChanged({
                if ($this.Checked) {
                    & $UpdateGameButtonStyle
                    if ($AutoPathRadio.Checked) { & $RefreshCandidates }
                    else { & $UpdateScopeForGame }
                }
            })
    }
    $AutoPathRadio.Add_CheckedChanged({
            $ClientCombo.Enabled = $AutoPathRadio.Checked
            $RefreshButton.Enabled = $AutoPathRadio.Checked
            $PathTextBox.Enabled = -not $AutoPathRadio.Checked
            $BrowseButton.Enabled = -not $AutoPathRadio.Checked
            if ($AutoPathRadio.Checked) { & $RefreshCandidates }
        })
    $ManualPathRadio.Add_CheckedChanged({
            if ($ManualPathRadio.Checked) {
                & $SetStatus "请选择游戏根目录。" $false
            }
        })
    $RefreshButton.Add_Click({ & $RefreshCandidates $true })
    $ClientCombo.Add_SelectedIndexChanged({
            if ($ClientCombo.SelectedItem) {
                $Candidate = $ClientCombo.SelectedItem.Candidate
                $PathTextBox.Text = [string]$Candidate.Path
                & $SetStatus "$($Candidate.InstallInfo.DisplayName)；$($Candidate.InstallInfo.LanguageName)" $false
                & $UpdateScopeForGame
            }
        })
    $BrowseButton.Add_Click({
            $Dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $Dialog.Description = "选择 Path of Exile 游戏根目录"
            $Dialog.ShowNewFolderButton = $false
            if (Test-Path -LiteralPath $PathTextBox.Text -PathType Container) {
                $Dialog.SelectedPath = $PathTextBox.Text
            }
            elseif (Test-Path -LiteralPath $PreferredGameRoot -PathType Container) {
                $Dialog.SelectedPath = $PreferredGameRoot
            }
            if ($Dialog.ShowDialog($Form) -eq [System.Windows.Forms.DialogResult]::OK) {
                $PathTextBox.Text = $Dialog.SelectedPath
                try {
                    $Candidate = Resolve-PoePatchManualSelection -RequestedGameVersion (& $GetRequestedGameVersion) -Path $PathTextBox.Text
                    & $SetStatus "$($Candidate.InstallInfo.DisplayName)；$($Candidate.InstallInfo.LanguageName)" $false
                    if ((& $GetRequestedGameVersion) -eq "auto") {
                        & $UpdateScopeForGame
                    }
                }
                catch {
                    & $SetStatus $_.Exception.Message $true
                }
            }
            $Dialog.Dispose()
        })
    $OpenLink = {
        param($Sender, $EventArgs)

        $Url = [string]$Sender.Tag
        try {
            Start-Process -FilePath $Url
        }
        catch {
            [System.Windows.Forms.Clipboard]::SetText($Url)
            [System.Windows.Forms.MessageBox]::Show(
                $Form,
                "无法打开链接，已复制到剪贴板：`n$Url",
                "打开链接",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
        }
    }
    $RepositoryLink.Add_LinkClicked($OpenLink)
    $CaimoguLink.Add_LinkClicked($OpenLink)

    $SubmitSelection = {
        param([ValidateSet("update", "restore")][string]$RequestedOperation)

            try {
                if ($AutoPathRadio.Checked) {
                    if (-not $ClientCombo.SelectedItem) {
                        throw "请先选择一个已识别的游戏客户端。"
                    }
                    $Candidate = $ClientCombo.SelectedItem.Candidate
                }
                else {
                    $Candidate = Resolve-PoePatchManualSelection `
                        -RequestedGameVersion (& $GetRequestedGameVersion) `
                        -Path $PathTextBox.Text
                }

                $PatchScope = "all"
                if ($RequestedOperation -eq "update") {
                    if ($CurrencyCheck.Checked -and $UniqueCheck.Checked) { $PatchScope = "all" }
                    elseif ($CurrencyCheck.Checked) { $PatchScope = "currency" }
                    elseif ($UniqueCheck.Checked) { $PatchScope = "uniques" }
                    elseif ($Candidate.GameVersion -eq "poe2" -and $IslandCheck.Checked) { $PatchScope = "none" }
                    else { throw "请至少选择一项更新内容。" }
                }

                $Form.Tag = [pscustomobject]@{
                    Operation = $RequestedOperation
                    GameVersion = [string]$Candidate.GameVersion
                    GameDirectory = [string]$Candidate.Path
                    InstallInfo = $Candidate.InstallInfo
                    PathMode = $(if ($AutoPathRadio.Checked) { "auto" } else { "manual" })
                    PatchScope = $PatchScope
                    IslandRumourHints = [bool]($Candidate.GameVersion -eq "poe2" -and $IslandCheck.Checked)
                }
                $Form.DialogResult = [System.Windows.Forms.DialogResult]::OK
                $Form.Close()
            }
            catch {
                & $SetStatus $_.Exception.Message $true
            }
    }

    $StartButton.Add_Click({ & $SubmitSelection "update" })
    $RestoreButton.Add_Click({ & $SubmitSelection "restore" })

    & $SetOperationLayout
    & $UpdateGameButtonStyle
    & $RefreshCandidates

    if ($ConstructOnly) {
        $Form.Dispose()
        return $null
    }

    $Result = $Form.ShowDialog()
    $Selection = $Form.Tag
    $Form.Dispose()
    if ($Result -ne [System.Windows.Forms.DialogResult]::OK -or $null -eq $Selection) {
        throw "已取消操作。"
    }
    return $Selection
}

$Selection = Show-PoePatchLauncherDialog `
    -Operation $Mode `
    -PreferredGameRoot $PreferredRoot `
    -ConstructOnly:$ConstructOnly `
    -SkipSystemGameDiscovery:$SkipSystemGameDiscovery
if ($ConstructOnly) {
    return
}

try {
    Save-PoePatchGameDirectory `
        -GameVersion $Selection.GameVersion `
        -GameDirectory $Selection.GameDirectory | Out-Null
}
catch {
    Write-Warning "无法保存最近使用的游戏目录，本次操作仍会继续：$($_.Exception.Message)"
}

if ($Selection.Operation -eq "update" -and $Selection.GameVersion -eq "poe1") {
    $ScriptName = "update_poe1_price_patch.ps1"
    $ScriptParameters = @{
        Poe1Dir = [string]$Selection.GameDirectory
    }
}
elseif ($Selection.Operation -eq "restore" -and $Selection.GameVersion -eq "poe1") {
    $ScriptName = "restore_poe1_price_patch.ps1"
    $ScriptParameters = @{
        Poe1Dir = [string]$Selection.GameDirectory
    }
}
elseif ($Selection.Operation -eq "update") {
    $ScriptName = "update_price_patch.ps1"
    $ScriptParameters = @{
        Poe2Dir = [string]$Selection.GameDirectory
    }
}
else {
    $ScriptName = "restore_price_patch.ps1"
    $ScriptParameters = @{
        Poe2Dir = [string]$Selection.GameDirectory
    }
}

if ($Selection.Operation -eq "update") {
    $ScriptParameters["PatchScope"] = [string]$Selection.PatchScope
    if ($Selection.GameVersion -eq "poe2" -and $Selection.IslandRumourHints) {
        $ScriptParameters["IslandRumourHints"] = $true
    }
}

$ScriptPath = Join-Path $PSScriptRoot $ScriptName
if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    throw "内置脚本不存在：$ScriptName"
}

& $ScriptPath @ScriptParameters
exit $LASTEXITCODE
