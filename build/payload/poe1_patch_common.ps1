. (Join-Path $PSScriptRoot "poe2_patch_common.ps1")
. (Join-Path $PSScriptRoot "poe_patch_profiles.ps1")

function Write-Poe1Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Assert-Poe1File {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Name：$Path"
    }
}

function Get-Poe1DisplayLanguageName {
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
        default { return $(if ([string]::IsNullOrWhiteSpace($Name)) { "未知语言" } else { $Name }) }
    }
}

function Get-Poe1PatchOutputKey {
    param([Parameter(Mandatory = $true)][string]$Poe1Dir)

    $Normalized = [System.IO.Path]::GetFullPath($Poe1Dir).TrimEnd('\', '/').ToUpperInvariant()
    $Hash = Get-Poe2TextSha256Hex -Text $Normalized
    return $Hash.Substring(0, 16).ToLowerInvariant()
}

function Get-Poe1LogicalRestoreZipName {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    $Kind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    $LanguageCode = [string]$InstallInfo.EffectiveLanguageCode
    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        $LanguageCode = [string]$InstallInfo.ConfigLanguage
    }
    $Language = ($LanguageCode -replace '[^A-Za-z0-9_-]+', '_')
    return "POE1还原补丁_${Kind}_${Language}.zip"
}

function Get-Poe1PhysicalRestoreZipName {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    $Kind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    $LanguageCode = [string]$InstallInfo.EffectiveLanguageCode
    if ([string]::IsNullOrWhiteSpace($LanguageCode)) {
        $LanguageCode = [string]$InstallInfo.ConfigLanguage
    }
    $Language = ($LanguageCode -replace '[^A-Za-z0-9_-]+', '_')
    return "POE1真实还原补丁_${Kind}_${Language}.zip"
}

function Get-Poe1PhysicalRestoreZipCandidateNames {
    param([Parameter(Mandatory = $true)]$InstallInfo)

    $Kind = ([string]$InstallInfo.InstallKind -replace '[^A-Za-z0-9_-]+', '_')
    return @(
        (Get-Poe1PhysicalRestoreZipName -InstallInfo $InstallInfo),
        "POE1真实还原补丁_${Kind}.zip"
    ) | Select-Object -Unique
}

function Write-Poe1JsonAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $Directory = Split-Path -Parent ([System.IO.Path]::GetFullPath($Path))
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    $Temp = Join-Path $Directory ([string]::Concat(".", (Split-Path -Leaf $Path), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Json = $Value | ConvertTo-Json -Depth 16
        [System.IO.File]::WriteAllText($Temp, $Json, (New-Object System.Text.UTF8Encoding($false)))
        Move-Poe2FileAtomically -Source $Temp -Destination $Path | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $Temp -PathType Leaf) {
            Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-Poe1BaseItemsLookPatched {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDat,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $TempCsv = Join-Path $env:TEMP ([string]::Concat("poe1_price_check_", [Guid]::NewGuid().ToString("N"), ".csv"))
    try {
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Script = Join-Path $PSScriptRoot "poe2_name_price_patch.py"
        $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
            $Script, "export", "--source", $SourceDat, "--output", $TempCsv
        ) -Quiet
        if ($Result.ExitCode -ne 0) {
            throw "BaseItemTypes 价格标记检测失败，退出码：$($Result.ExitCode)。$($Result.Text)"
        }
        return [bool](Import-Csv -LiteralPath $TempCsv -Encoding UTF8 | Where-Object {
                [string]$_.name -match '(?:=|^)(?:<1|[0-9]+(?:\.[0-9]+)?)[CDE]$'
            } | Select-Object -First 1)
    }
    finally {
        if (Test-Path -LiteralPath $TempCsv -PathType Leaf) {
            Remove-Item -LiteralPath $TempCsv -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-Poe1WordsLookPatched {
    param(
        [Parameter(Mandatory = $true)][string]$SourceWords,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    if (-not (Test-Path -LiteralPath $SourceWords -PathType Leaf)) {
        return $false
    }
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $Script = Join-Path $PSScriptRoot "build_poe1_price_patch.py"
    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @($Script, "--check-words", $SourceWords) -Quiet
    if ($Result.ExitCode -ne 0) {
        throw "Words 价格标记检测失败，退出码：$($Result.ExitCode)。$($Result.Text)"
    }
    $Info = $Result.Text | ConvertFrom-Json
    return ([int]$Info.patched_count -gt 0)
}

function Get-Poe1BaseItemsSignature {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDat,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    Assert-Poe1File -Path $SourceDat -Name "BaseItemTypes.datc64"
    $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
    $Script = Join-Path $PSScriptRoot "poe2_name_price_patch.py"
    $Result = Invoke-Poe2Python -Python $Python -ArgumentList @(
        $Script, "signature", "--source", $SourceDat
    ) -Quiet
    if ($Result.ExitCode -ne 0) {
        throw "BaseItemTypes 结构签名生成失败，退出码：$($Result.ExitCode)。$($Result.Text)"
    }
    $Signature = $Result.Text | ConvertFrom-Json
    foreach ($Name in @("signature_version", "row_count", "row_size", "metadata_paths_sha256", "fixed_rows_sha256", "compatibility_sha256")) {
        if ($null -eq $Signature.PSObject.Properties[$Name] -or [string]::IsNullOrWhiteSpace([string]$Signature.$Name)) {
            throw "BaseItemTypes 结构签名缺少字段：$Name"
        }
    }
    return $Signature
}

function Test-Poe1BaseItemsCompatible {
    param(
        [Parameter(Mandatory = $true)][string]$LeftDat,
        [Parameter(Mandatory = $true)][string]$RightDat,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    try {
        $Left = Get-Poe1BaseItemsSignature -SourceDat $LeftDat -RepoRoot $RepoRoot
        $Right = Get-Poe1BaseItemsSignature -SourceDat $RightDat -RepoRoot $RepoRoot
        return ([string]$Left.compatibility_sha256).Equals(
            [string]$Right.compatibility_sha256,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        Write-Warning "POE1 BaseItemTypes 兼容性检查失败：$($_.Exception.Message)"
        return $false
    }
}

function Get-Poe1ZipEntryTempFile {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$EntryName,
        [string]$Extension = ".datc64"
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Temp = Join-Path $env:TEMP ([string]::Concat("poe1_zip_entry_", [Guid]::NewGuid().ToString("N"), $Extension))
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $Entry = $Archive.GetEntry($EntryName.Replace('\', '/'))
        if ($null -eq $Entry) {
            throw "ZIP 缺少条目：$EntryName"
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Temp, $true)
    }
    finally {
        $Archive.Dispose()
    }
    return $Temp
}

function New-Poe1InstallPayloadZip {
    param(
        [Parameter(Mandatory = $true)][string]$SourceZip,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$OutputZip
    )

    Assert-Poe1File -Path $SourceZip -Name "POE1 源补丁包"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $OutputFull = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputFull
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputFull), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    $SourceArchive = $null
    $DestinationArchive = $null
    try {
        $SourceArchive = [System.IO.Compression.ZipFile]::OpenRead($SourceZip)
        $DestinationArchive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        foreach ($Path in @($InstallInfo.TcBaseItemsPath, $InstallInfo.TcWordsPath) | Select-Object -Unique) {
            $Name = ([string]$Path).Replace('\', '/')
            $SourceEntry = $SourceArchive.GetEntry($Name)
            if ($null -eq $SourceEntry) { throw "POE1 源补丁包缺少写入目标：$Name" }
            $DestinationEntry = $DestinationArchive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
            $InputStream = $SourceEntry.Open()
            $OutputStream = $DestinationEntry.Open()
            try { $InputStream.CopyTo($OutputStream) }
            finally {
                $OutputStream.Dispose()
                $InputStream.Dispose()
            }
        }
        $DestinationArchive.Dispose()
        $DestinationArchive = $null
        $SourceArchive.Dispose()
        $SourceArchive = $null
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputFull | Out-Null
    }
    finally {
        if ($null -ne $DestinationArchive) { $DestinationArchive.Dispose() }
        if ($null -ne $SourceArchive) { $SourceArchive.Dispose() }
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
    return $OutputFull
}

function New-Poe1LogicalRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$BaseItems,
        [Parameter(Mandatory = $true)][string]$Words,
        [Parameter(Mandatory = $true)][string]$OutputZip,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    if (Test-Poe1BaseItemsLookPatched -SourceDat $BaseItems -RepoRoot $RepoRoot) {
        throw "当前 BaseItemTypes 已包含价格标记，不能覆盖干净还原底板。"
    }
    if (Test-Poe1WordsLookPatched -SourceWords $Words -RepoRoot $RepoRoot) {
        throw "当前 Words 已包含价格标记，不能覆盖干净还原底板。"
    }
    $Signature = Get-Poe1BaseItemsSignature -SourceDat $BaseItems -RepoRoot $RepoRoot
    $Manifest = [ordered]@{
        kind = "poe1-price-patch-logical-restore"
        version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        install_kind = [string]$InstallInfo.InstallKind
        baseitems_path = [string]$InstallInfo.TcBaseItemsPath
        words_path = [string]$InstallInfo.TcWordsPath
        baseitems_signature = $Signature
        baseitems_sha256 = (Get-FileHash -LiteralPath $BaseItems -Algorithm SHA256).Hash.ToLowerInvariant()
        words_sha256 = (Get-FileHash -LiteralPath $Words -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $OutputFull = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputFull
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputFull), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $Archive, $BaseItems, ([string]$InstallInfo.TcBaseItemsPath).Replace('\', '/'),
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $Archive, $Words, ([string]$InstallInfo.TcWordsPath).Replace('\', '/'),
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
            $ManifestEntry = $Archive.CreateEntry("poe1-restore-manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
            $Writer = New-Object System.IO.StreamWriter($ManifestEntry.Open(), (New-Object System.Text.UTF8Encoding($false)))
            try { $Writer.Write(($Manifest | ConvertTo-Json -Depth 12)) } finally { $Writer.Dispose() }
        }
        finally {
            $Archive.Dispose()
        }
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputFull | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
    return $OutputFull
}

function Test-Poe1LogicalRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { return $false }
    $BaseTemp = ""
    $WordsTemp = ""
    try {
        $BaseTemp = Get-Poe1ZipEntryTempFile -ZipPath $ZipPath -EntryName $InstallInfo.TcBaseItemsPath
        $WordsTemp = Get-Poe1ZipEntryTempFile -ZipPath $ZipPath -EntryName $InstallInfo.TcWordsPath
        if (Test-Poe1BaseItemsLookPatched -SourceDat $BaseTemp -RepoRoot $RepoRoot) { return $false }
        if (Test-Poe1WordsLookPatched -SourceWords $WordsTemp -RepoRoot $RepoRoot) { return $false }
        if (-not (Test-Poe1BaseItemsCompatible -LeftDat $BaseTemp -RightDat $CurrentBaseItems -RepoRoot $RepoRoot)) { return $false }
        return $true
    }
    catch {
        Write-Warning "忽略不可用的 POE1 还原包 $ZipPath：$($_.Exception.Message)"
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

function Assert-Poe1PatchZipCompatible {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$CurrentWords,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $BaseTemp = ""
    $WordsTemp = ""
    try {
        $BaseTemp = Get-Poe1ZipEntryTempFile -ZipPath $ZipPath -EntryName $InstallInfo.TcBaseItemsPath
        $WordsTemp = Get-Poe1ZipEntryTempFile -ZipPath $ZipPath -EntryName $InstallInfo.TcWordsPath
        if (-not (Test-Poe1BaseItemsCompatible -LeftDat $BaseTemp -RightDat $CurrentBaseItems -RepoRoot $RepoRoot)) {
            throw "POE1 补丁包 BaseItemTypes 与当前游戏版本不兼容。"
        }
        $Python = Ensure-PythonRequests -RepoRoot $RepoRoot
        $Builder = Join-Path $PSScriptRoot "build_poe1_price_patch.py"
        $Expected = Invoke-Poe2Python -Python $Python -ArgumentList @($Builder, "--check-words", $CurrentWords) -Quiet
        $Actual = Invoke-Poe2Python -Python $Python -ArgumentList @($Builder, "--check-words", $WordsTemp) -Quiet
        if ($Expected.ExitCode -ne 0 -or $Actual.ExitCode -ne 0) {
            throw "POE1 补丁包 Words 行结构检查失败。"
        }
        if ([int](($Expected.Text | ConvertFrom-Json).row_count) -ne [int](($Actual.Text | ConvertFrom-Json).row_count)) {
            throw "POE1 补丁包 Words 行数与当前游戏版本不一致。"
        }
    }
    finally {
        foreach ($Temp in @($BaseTemp, $WordsTemp)) {
            if (-not [string]::IsNullOrWhiteSpace($Temp) -and (Test-Path -LiteralPath $Temp -PathType Leaf)) {
                Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Resolve-Poe1BundleExtractor {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $Candidates = @(
        (Join-Path $RepoRoot "tools\BundleExtractor\BundleExtractor.exe"),
        (Join-Path $PSScriptRoot "BundleExtractor\BundleExtractor.exe"),
        (Join-Path (Split-Path -Parent $RepoRoot) "build\publish-bundle-extractor\BundleExtractor.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "找不到 BundleExtractor.exe。"
}

function Invoke-Poe1ExtractBatch {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("Bundles2", "GGPK")][string]$Mode,
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)][string]$Extractor,
        [Parameter(Mandatory = $true)][string[]]$Paths,
        [Parameter(Mandatory = $true)][string]$DestinationDirectory,
        [string[]]$OptionalPaths = @(),
        [switch]$Optional,
        [int]$Attempts = 3,
        [int]$RetryDelayMilliseconds = 800
    )

    $UniquePaths = @($Paths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($UniquePaths.Count -eq 0) { return @{} }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $OptionalSet = @{}
    if ($Optional) {
        foreach ($Path in $UniquePaths) { $OptionalSet[$Path] = $true }
    }
    foreach ($Path in @($OptionalPaths)) {
        if (-not [string]::IsNullOrWhiteSpace($Path)) { $OptionalSet[$Path] = $true }
    }

    $MaxAttempts = [Math]::Max(1, $Attempts)
    $LastError = $null
    for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt += 1) {
        $ToolOutput = @()
        $ExitCode = $null
        $RequestList = Join-Path $DestinationDirectory ([string]::Concat("request-", [Guid]::NewGuid().ToString("N"), ".txt"))
        $ExtractDir = Join-Path $DestinationDirectory ([string]::Concat("stage-", [Guid]::NewGuid().ToString("N")))
        [System.IO.File]::WriteAllLines($RequestList, $UniquePaths, (New-Object System.Text.UTF8Encoding($false)))
        New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
        try {
            if ($Mode -eq "Bundles2") {
                $Source = Join-Path $Poe1Dir "Bundles2\_.index.bin"
                $ToolOutput = @(& $Extractor --extract-list $Source $RequestList $ExtractDir 2>&1)
            }
            else {
                $Source = Join-Path $Poe1Dir "Content.ggpk"
                $ToolOutput = @(& $Extractor --extract-ggpk-list $Source $RequestList $ExtractDir 2>&1)
            }
            $ExitCode = $LASTEXITCODE
            $ToolOutput | ForEach-Object { Write-Host $_ }

            $Result = @{}
            $MissingRequired = New-Object System.Collections.Generic.List[string]
            for ($Index = 0; $Index -lt $UniquePaths.Count; $Index += 1) {
                $SourceFile = Join-Path $ExtractDir ("{0:D6}.bin" -f $Index)
                if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
                    if (-not $OptionalSet.ContainsKey($UniquePaths[$Index])) {
                        [void]$MissingRequired.Add($UniquePaths[$Index])
                    }
                    continue
                }
                $Slug = ($UniquePaths[$Index].Replace('\', '/') -replace '/', '_')
                $Destination = Join-Path $DestinationDirectory $Slug
                Copy-Poe2FileAtomically -Source $SourceFile -Destination $Destination | Out-Null
                $Result[$UniquePaths[$Index]] = $Destination
            }

            $ToolText = ($ToolOutput -join "`n")
            $Transient = [bool]($ToolText -match '(?im)(?:IOException|sharing violation|being used by another process|cannot access the file|file is being used)')
            if ($MissingRequired.Count -gt 0) {
                throw "POE1 DAT 提取结果缺失：$([string]::Join(', ', $MissingRequired))"
            }
            if ($ExitCode -ne 0 -and -not ($ExitCode -eq 2 -and $OptionalSet.Count -gt 0)) {
                throw "POE1 DAT 批量提取失败，退出码：$ExitCode"
            }
            return $Result
        }
        catch {
            $LastError = $_
            $ToolText = if ($null -eq $ToolOutput) { "" } else { ($ToolOutput -join "`n") }
            $DiagnosticText = "$ToolText`n$($_.Exception.Message)"
            $Transient = [bool]($DiagnosticText -match '(?im)(?:IOException|sharing violation|being used by another process|cannot access the file|file is being used|进程无法访问文件|文件正由另一进程使用)')
            if ($Attempt -ge $MaxAttempts -or -not $Transient) {
                throw
            }
            Write-Warning "POE1 DAT 提取遇到短暂文件占用，等待后重试（$Attempt/$MaxAttempts）：$($_.Exception.Message)"
            Start-Sleep -Milliseconds ([Math]::Max(100, $RetryDelayMilliseconds * $Attempt))
        }
        finally {
            if (Test-Path -LiteralPath $RequestList -PathType Leaf) {
                Remove-Item -LiteralPath $RequestList -Force -ErrorAction SilentlyContinue
            }
            if (Test-Path -LiteralPath $ExtractDir -PathType Container) {
                Remove-Item -LiteralPath $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
    throw $LastError
}

function Invoke-Poe1ExtractDatFiles {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$DestinationDirectory
    )

    $Extractor = Resolve-Poe1BundleExtractor -RepoRoot $RepoRoot
    $LocalizedPaths = @($InstallInfo.TcBaseItemsPath, $InstallInfo.TcWordsPath)
    $EnglishPaths = @($InstallInfo.EnBaseItemsPath, $InstallInfo.EnWordsPath) | Where-Object {
        $_ -notin $LocalizedPaths
    }
    $RequiredPaths = @($LocalizedPaths + @($InstallInfo.EnBaseItemsPath)) | Select-Object -Unique
    $OptionalPaths = @($InstallInfo.EnWordsPath) | Where-Object { $_ -notin $RequiredPaths }
    # Loading the multi-million-entry index once is important.  Starting a second
    # extractor immediately after the localized pair can race the native index
    # disposal and leave _.index.bin locked on updated Steam clients.
    $AllPaths = @($LocalizedPaths + $EnglishPaths) | Select-Object -Unique
    $All = Invoke-Poe1ExtractBatch -Mode $InstallInfo.Mode -Poe1Dir $Poe1Dir -Extractor $Extractor `
        -Paths $AllPaths -OptionalPaths $OptionalPaths -DestinationDirectory $DestinationDirectory
    foreach ($Path in $RequiredPaths) {
        if (-not $All.ContainsKey($Path)) {
            throw "POE1 必需 DAT 提取结果缺失：$Path。请确认游戏已更新完成并关闭游戏、Steam/Epic 后重试。"
        }
    }
    return [pscustomobject]@{
        Extractor = $Extractor
        LocalizedBaseItems = [string]$All[$InstallInfo.TcBaseItemsPath]
        LocalizedWords = [string]$All[$InstallInfo.TcWordsPath]
        EnglishBaseItems = [string]$All[$InstallInfo.EnBaseItemsPath]
        EnglishWords = [string]$All[$InstallInfo.EnWordsPath]
    }
}

function Get-Poe1PhysicalRestoreFileDescriptors {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir
    )

    $Bundles2Dir = (Get-Item -LiteralPath (Join-Path $Poe1Dir "Bundles2") -ErrorAction Stop).FullName
    $Files = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($Name in @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")) {
        $Path = Join-Path $Bundles2Dir $Name
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [void]$Files.Add((Get-Item -LiteralPath $Path))
        }
    }
    $LibDir = Join-Path $Bundles2Dir "LibGGPK3"
    if (Test-Path -LiteralPath $LibDir -PathType Container) {
        foreach ($File in @(Get-ChildItem -LiteralPath $LibDir -Recurse -File | Sort-Object FullName)) {
            [void]$Files.Add($File)
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Bundles2Dir "_.index.bin") -PathType Leaf)) {
        throw "无法读取 POE1 真实还原文件清单：$Poe1Dir\Bundles2\_.index.bin 不存在。"
    }

    $RootPrefix = $Bundles2Dir.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    return @($Files | Sort-Object FullName | ForEach-Object {
            $Relative = $_.FullName.Substring($RootPrefix.Length).Replace('\', '/')
            [pscustomobject][ordered]@{
                path = "Bundles2/$Relative"
                length = [long]$_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        })
}

function Get-Poe1Bundles2MutationFingerprint {
    param([Parameter(Mandatory = $true)][string]$Poe1Dir)

    $Records = @(Get-Poe1PhysicalRestoreFileDescriptors -Poe1Dir $Poe1Dir)
    $Canonical = [string]::Join("`n", @($Records | ForEach-Object {
                "{0}|{1}|{2}" -f `
                    ([string]$_.path).ToLowerInvariant(), `
                    [long]$_.length, `
                    ([string]$_.sha256).ToLowerInvariant()
            }))
    return [pscustomobject][ordered]@{
        version = 1
        algorithm = "path-length-sha256-v1"
        files = $Records
        inventory_sha256 = Get-Poe2TextSha256Hex -Text $Canonical
    }
}

function Assert-Poe1Bundles2MutationFingerprintCurrent {
    param(
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Poe1Dir
    )

    if (
        $null -eq $Expected -or
        [int]$Expected.version -ne 1 -or
        [string]$Expected.algorithm -ne "path-length-sha256-v1"
    ) {
        throw "POE1 缺少可识别的 Bundles2 写入前状态指纹。"
    }
    $Current = Get-Poe1Bundles2MutationFingerprint -Poe1Dir $Poe1Dir
    if (@($Expected.files).Count -ne @($Current.files).Count) {
        throw "POE1 Bundles2 状态已并发变化：文件数量与本次写入准备时不同。请等待游戏平台更新完成并完全关闭游戏与启动器后重试。"
    }
    $ExpectedHash = [string]$Expected.inventory_sha256
    if (
        $ExpectedHash -notmatch '^[0-9a-fA-F]{64}$' -or
        -not $ExpectedHash.Equals([string]$Current.inventory_sha256, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "POE1 Bundles2 状态已并发变化：索引或 LibGGPK3 内容与本次写入准备时不同。请等待游戏平台更新完成并完全关闭游戏与启动器后重试。"
    }
    return $Current
}

function New-Poe1PhysicalRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$OutputZip,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $Bundles2Dir = (Resolve-Path -LiteralPath (Join-Path $Poe1Dir "Bundles2")).Path
    $Descriptors = @(Get-Poe1PhysicalRestoreFileDescriptors -Poe1Dir $Poe1Dir)
    $Signature = Get-Poe1BaseItemsSignature -SourceDat $CurrentBaseItems -RepoRoot $RepoRoot
    $Manifest = [ordered]@{
        kind = "poe1-price-patch-physical-restore"
        version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        install_kind = [string]$InstallInfo.InstallKind
        target_path = [string]$InstallInfo.TcBaseItemsPath
        baseitems_signature = $Signature
        restore_files = $Descriptors
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $OutputFull = [System.IO.Path]::GetFullPath($OutputZip)
    $OutputDir = Split-Path -Parent $OutputFull
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $TempZip = Join-Path $OutputDir ([string]::Concat(".", (Split-Path -Leaf $OutputFull), ".new-", [Guid]::NewGuid().ToString("N"), ".tmp"))
    try {
        $Archive = [System.IO.Compression.ZipFile]::Open($TempZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            for ($Index = 0; $Index -lt $Descriptors.Count; $Index += 1) {
                $Relative = ([string]$Descriptors[$Index].path).Substring("Bundles2/".Length).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
                $SourceFile = Join-Path $Bundles2Dir $Relative
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $Archive,
                    $SourceFile,
                    [string]$Descriptors[$Index].path,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
            $ManifestEntry = $Archive.CreateEntry("poe1-physical-restore-manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
            $Writer = New-Object System.IO.StreamWriter($ManifestEntry.Open(), (New-Object System.Text.UTF8Encoding($false)))
            try { $Writer.Write(($Manifest | ConvertTo-Json -Depth 12)) } finally { $Writer.Dispose() }
        }
        finally {
            $Archive.Dispose()
        }
        Move-Poe2FileAtomically -Source $TempZip -Destination $OutputFull | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $TempZip -PathType Leaf) {
            Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
        }
    }
    return $OutputFull
}

function Assert-Poe1PhysicalRestoreCurrent {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$Poe1Dir
    )

    $Expected = @($Manifest.restore_files)
    $Current = @(Get-Poe1PhysicalRestoreFileDescriptors -Poe1Dir $Poe1Dir)
    if ($Expected.Count -ne $Current.Count) {
        throw "POE1 真实还原包与当前 Bundles2 文件列表不一致：备份 $($Expected.Count) 个，当前 $($Current.Count) 个。"
    }

    $ExpectedByPath = @{}
    foreach ($Descriptor in $Expected) {
        $Name = [string]$Descriptor.path
        if ($Name -notmatch '^Bundles2/(?:_\.index\.bin|_\.index\.(?:high|low)\.bin|\.index\.dbg|LibGGPK3/.+)$') {
            throw "POE1 真实还原包包含不允许的路径：$Name"
        }
        $Key = $Name.ToLowerInvariant()
        if ($ExpectedByPath.ContainsKey($Key)) {
            throw "POE1 真实还原包包含重复路径：$Name"
        }
        if ([string]$Descriptor.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "POE1 真实还原包 SHA256 无效：$Name"
        }
        try { $Length = [long]$Descriptor.length } catch { throw "POE1 真实还原包文件长度无效：$Name" }
        if ($Length -lt 0) { throw "POE1 真实还原包文件长度无效：$Name" }
        $ExpectedByPath[$Key] = $Descriptor
    }

    $CurrentByPath = @{}
    foreach ($Descriptor in $Current) {
        $CurrentByPath[([string]$Descriptor.path).ToLowerInvariant()] = $Descriptor
    }
    foreach ($Key in $ExpectedByPath.Keys) {
        $ExpectedDescriptor = $ExpectedByPath[$Key]
        if (-not $CurrentByPath.ContainsKey($Key)) {
            throw "POE1 真实还原包与当前 Bundles2 文件列表不一致，缺少：$($ExpectedDescriptor.path)"
        }
        $CurrentDescriptor = $CurrentByPath[$Key]
        if ([long]$ExpectedDescriptor.length -ne [long]$CurrentDescriptor.length) {
            throw "POE1 真实还原包与当前 Bundles2 文件长度不一致：$($ExpectedDescriptor.path)"
        }
        if (-not ([string]$ExpectedDescriptor.sha256).Equals(
                [string]$CurrentDescriptor.sha256,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            throw "POE1 真实还原包与当前 Bundles2 文件 SHA256 不一致：$($ExpectedDescriptor.path)"
        }
    }
    foreach ($Key in $CurrentByPath.Keys) {
        if (-not $ExpectedByPath.ContainsKey($Key)) {
            throw "POE1 真实还原包与当前 Bundles2 文件列表不一致，多出：$($CurrentByPath[$Key].path)"
        }
    }
    return $Current
}

function Assert-Poe1PhysicalRestoreZip {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$Poe1Dir = "",
        [switch]$RequireCurrentPhysical
    )

    Assert-Poe1File -Path $ZipPath -Name "POE1 真实还原包"
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $ManifestEntry = $Archive.GetEntry("poe1-physical-restore-manifest.json")
        if ($null -eq $ManifestEntry) { throw "POE1 真实还原包缺少 manifest。" }
        $Reader = New-Object System.IO.StreamReader($ManifestEntry.Open(), [System.Text.Encoding]::UTF8)
        try { $Manifest = $Reader.ReadToEnd() | ConvertFrom-Json } finally { $Reader.Dispose() }
        if ([string]$Manifest.kind -ne "poe1-price-patch-physical-restore" -or [int]$Manifest.version -ne 1) {
            throw "POE1 真实还原包 manifest 类型或版本无效。"
        }
        if ([string]$Manifest.install_kind -ne [string]$InstallInfo.InstallKind) {
            throw "POE1 真实还原包属于 $($Manifest.install_kind)，当前安装为 $($InstallInfo.InstallKind)。"
        }
        if ([string]$Manifest.target_path -ne [string]$InstallInfo.TcBaseItemsPath) {
            throw "POE1 真实还原包目标资源路径与当前客户端不一致。"
        }
        $CurrentSignature = Get-Poe1BaseItemsSignature -SourceDat $CurrentBaseItems -RepoRoot $RepoRoot
        if (-not ([string]$Manifest.baseitems_signature.compatibility_sha256).Equals(
                [string]$CurrentSignature.compatibility_sha256,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            throw "POE1 真实还原包与当前游戏版本的 BaseItemTypes 结构不兼容。"
        }

        $Seen = @{}
        foreach ($Descriptor in @($Manifest.restore_files)) {
            $Name = [string]$Descriptor.path
            if ($Name -notmatch '^Bundles2/(?:_\.index\.bin|_\.index\.(?:high|low)\.bin|\.index\.dbg|LibGGPK3/.+)$') {
                throw "POE1 真实还原包包含不允许的路径：$Name"
            }
            $Key = $Name.ToLowerInvariant()
            if ($Seen.ContainsKey($Key)) { throw "POE1 真实还原包包含重复路径：$Name" }
            $Seen[$Key] = $true
            $Entry = $Archive.GetEntry($Name)
            if ($null -eq $Entry) { throw "POE1 真实还原包缺少文件：$Name" }
            $Integrity = Get-Poe2ZipEntryStreamIntegrity -Entry $Entry
            if ([long]$Descriptor.length -ne [long]$Integrity.Length -or
                -not ([string]$Descriptor.sha256).Equals([string]$Integrity.Sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "POE1 真实还原包完整性校验失败：$Name"
            }
        }
        if (-not $Seen.ContainsKey("bundles2/_.index.bin")) {
            throw "POE1 真实还原包缺少 Bundles2/_.index.bin。"
        }
        if ($RequireCurrentPhysical) {
            if ([string]::IsNullOrWhiteSpace($Poe1Dir)) {
                throw "校验当前 POE1 物理文件时必须提供游戏目录。"
            }
            Assert-Poe1PhysicalRestoreCurrent -Manifest $Manifest -Poe1Dir $Poe1Dir | Out-Null
        }
        return $Manifest
    }
    finally {
        $Archive.Dispose()
    }
}

function Restore-Poe1PhysicalBundles2 {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$CurrentBaseItems,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $Manifest = Assert-Poe1PhysicalRestoreZip -ZipPath $ZipPath -InstallInfo $InstallInfo `
        -CurrentBaseItems $CurrentBaseItems -RepoRoot $RepoRoot
    $Bundles2Dir = (Resolve-Path -LiteralPath (Join-Path $Poe1Dir "Bundles2")).Path
    Assert-Poe2GameFilesAvailable -Poe2Dir $Poe1Dir -IndexPath (Join-Path $Bundles2Dir "_.index.bin")
    $Transaction = [Guid]::NewGuid().ToString("N")
    $Stage = Join-Path $Bundles2Dir ".poe1-restore-stage-$Transaction"
    $Rollback = Join-Path $Bundles2Dir ".poe1-restore-rollback-$Transaction"
    Assert-Poe2PathInside -Path $Stage -Root $Bundles2Dir -Message "Unsafe POE1 restore staging path" | Out-Null
    Assert-Poe2PathInside -Path $Rollback -Root $Bundles2Dir -Message "Unsafe POE1 restore rollback path" | Out-Null
    New-Item -ItemType Directory -Force -Path $Stage, $Rollback | Out-Null

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($Descriptor in @($Manifest.restore_files)) {
            $Name = [string]$Descriptor.path
            $Relative = $Name.Substring("Bundles2/".Length).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
            $Destination = [System.IO.Path]::GetFullPath((Join-Path $Stage $Relative))
            Assert-Poe2PathInside -Path $Destination -Root $Stage -Message "Unsafe POE1 restore ZIP path" | Out-Null
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Archive.GetEntry($Name), $Destination, $true)
        }
    }
    finally {
        $Archive.Dispose()
    }

    $KnownTop = @("_.index.bin", "_.index.high.bin", "_.index.low.bin", ".index.dbg")
    $InstalledTop = New-Object System.Collections.Generic.List[string]
    $MovedTop = New-Object System.Collections.Generic.List[object]
    $CurrentLib = Join-Path $Bundles2Dir "LibGGPK3"
    $StageLib = Join-Path $Stage "LibGGPK3"
    $RollbackLib = Join-Path $Rollback "LibGGPK3"
    $LibMoved = $false
    $LibInstalled = $false
    try {
        foreach ($Name in $KnownTop) {
            $Current = Join-Path $Bundles2Dir $Name
            $Backup = Join-Path $Rollback $Name
            $Replacement = Join-Path $Stage $Name
            if (Test-Path -LiteralPath $Current -PathType Leaf) {
                [System.IO.File]::Move($Current, $Backup)
                $MovedTop.Add([pscustomobject]@{ Current = $Current; Backup = $Backup })
            }
            if (Test-Path -LiteralPath $Replacement -PathType Leaf) {
                [System.IO.File]::Move($Replacement, $Current)
                $InstalledTop.Add($Current)
            }
        }
        if (Test-Path -LiteralPath $CurrentLib -PathType Container) {
            [System.IO.Directory]::Move($CurrentLib, $RollbackLib)
            $LibMoved = $true
        }
        if (Test-Path -LiteralPath $StageLib -PathType Container) {
            [System.IO.Directory]::Move($StageLib, $CurrentLib)
            $LibInstalled = $true
        }

        foreach ($Descriptor in @($Manifest.restore_files)) {
            $Relative = ([string]$Descriptor.path).Substring("Bundles2/".Length).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
            $Target = Join-Path $Bundles2Dir $Relative
            Assert-Poe1File -Path $Target -Name ([string]$Descriptor.path)
            $Hash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
            if (-not $Hash.Equals([string]$Descriptor.sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "POE1 真实还原后 SHA256 不一致：$($Descriptor.path)"
            }
        }
    }
    catch {
        $Failure = $_
        if ($LibInstalled -and (Test-Path -LiteralPath $CurrentLib -PathType Container)) {
            Remove-Item -LiteralPath $CurrentLib -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($LibMoved -and (Test-Path -LiteralPath $RollbackLib -PathType Container)) {
            [System.IO.Directory]::Move($RollbackLib, $CurrentLib)
        }
        foreach ($Target in $InstalledTop) {
            if (Test-Path -LiteralPath $Target -PathType Leaf) {
                Remove-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
            }
        }
        foreach ($Item in @($MovedTop | Sort-Object { $_.Current } -Descending)) {
            if (Test-Path -LiteralPath $Item.Backup -PathType Leaf) {
                [System.IO.File]::Move($Item.Backup, $Item.Current)
            }
        }
        throw $Failure
    }
    finally {
        foreach ($Path in @($Stage, $Rollback)) {
            if (Test-Path -LiteralPath $Path -PathType Container) {
                Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Test-Poe1ToolOutputFailure {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    return [bool](
        $Text -match '(?im)(?:^|\s)(?:fatal|unhandled exception|filenotfound|could not load|failed to create mutex|error:)' -or
        $Text -match '(?im)FileNotFoundException|Could not found file in Index'
    )
}

function Invoke-Poe1ApplyPatch {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$PatchZip,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Dotnet
    )

    $InstallerDir = Join-Path $RepoRoot "一键安装特殊补丁工具"
    if ($InstallInfo.Mode -eq "GGPK") {
        $Tool = Join-Path $InstallerDir "PatchBundledGGPK3.dll"
        Assert-Poe1File -Path $Tool -Name "PatchBundledGGPK3.dll"
        $Target = Join-Path $Poe1Dir "Content.ggpk"
    }
    else {
        $Tool = Join-Path $InstallerDir "PatchBundle3.dll"
        Assert-Poe1File -Path $Tool -Name "PatchBundle3.dll"
        $Target = Join-Path $Poe1Dir "Bundles2\_.index.bin"
    }
    $Result = Invoke-DotNet8 -Dotnet $Dotnet -ArgumentList @($Tool, $Target, $PatchZip) -InputText "" -Quiet
    $Result.Lines | ForEach-Object { Write-Host $_ }
    if ($Result.ExitCode -ne 0 -or (Test-Poe1ToolOutputFailure -Text $Result.Text)) {
        throw "POE1 补丁写入工具失败，退出码：$($Result.ExitCode)。"
    }
}

function Assert-Poe1PatchApplied {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$PatchZip,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $TempRoot = Join-Path $env:TEMP ([string]::Concat("poe1_readback_", [Guid]::NewGuid().ToString("N")))
    $ExpectedDir = Join-Path $TempRoot "expected"
    $ActualDir = Join-Path $TempRoot "actual"
    New-Item -ItemType Directory -Force -Path $ExpectedDir, $ActualDir | Out-Null
    try {
        $Paths = @($InstallInfo.TcBaseItemsPath, $InstallInfo.TcWordsPath) | Select-Object -Unique
        $Expected = @{}
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($PatchZip)
        try {
            foreach ($Path in $Paths) {
                $Entry = $Archive.GetEntry(([string]$Path).Replace('\', '/'))
                if ($null -eq $Entry) { continue }
                $Destination = Join-Path $ExpectedDir ([Guid]::NewGuid().ToString("N") + ".datc64")
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Destination, $true)
                $Expected[[string]$Path] = $Destination
            }
        }
        finally {
            $Archive.Dispose()
        }
        if ($Expected.Count -eq 0) { throw "POE1 补丁包没有可校验的目标 DAT。" }
        $Extractor = Resolve-Poe1BundleExtractor -RepoRoot $RepoRoot
        $Actual = Invoke-Poe1ExtractBatch -Mode $InstallInfo.Mode -Poe1Dir $Poe1Dir -Extractor $Extractor `
            -Paths @($Expected.Keys) -DestinationDirectory $ActualDir
        foreach ($Path in $Expected.Keys) {
            $ExpectedHash = (Get-FileHash -LiteralPath $Expected[$Path] -Algorithm SHA256).Hash
            $ActualHash = (Get-FileHash -LiteralPath $Actual[$Path] -Algorithm SHA256).Hash
            if ($ExpectedHash -ne $ActualHash) {
                throw "POE1 写入后读回内容不一致：$Path"
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempRoot -PathType Container) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-Poe1PatchWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$PatchZip,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Dotnet,
        [int]$Attempts = 2
    )

    $LastError = $null
    for ($Attempt = 1; $Attempt -le [Math]::Max(1, $Attempts); $Attempt += 1) {
        try {
            if ($InstallInfo.Mode -eq "Bundles2") {
                Assert-Poe2GameFilesAvailable -Poe2Dir $Poe1Dir -IndexPath (Join-Path $Poe1Dir "Bundles2\_.index.bin")
            }
            else {
                Assert-Poe2GameFilesAvailable -Poe2Dir $Poe1Dir -IndexPath (Join-Path $Poe1Dir "Content.ggpk")
            }
            Invoke-Poe1ApplyPatch -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $PatchZip -RepoRoot $RepoRoot -Dotnet $Dotnet
            Assert-Poe1PatchApplied -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $PatchZip -RepoRoot $RepoRoot
            return
        }
        catch {
            $LastError = $_
            if ($Attempt -lt $Attempts) {
                Write-Warning "POE1 写入或校验失败，正在重试一次：$($_.Exception.Message)"
            }
        }
    }
    throw $LastError
}

function Invoke-Poe1LogicalRestoreWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Poe1Dir,
        [Parameter(Mandatory = $true)]$InstallInfo,
        [Parameter(Mandatory = $true)][string]$LogicalRestoreZip,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Dotnet,
        [int]$Attempts = 2
    )

    $InstallZip = Join-Path $env:TEMP ([string]::Concat("poe1_restore_install_", [Guid]::NewGuid().ToString("N"), ".zip"))
    try {
        New-Poe1InstallPayloadZip -SourceZip $LogicalRestoreZip -InstallInfo $InstallInfo -OutputZip $InstallZip | Out-Null
        Invoke-Poe1PatchWithRetry -Poe1Dir $Poe1Dir -InstallInfo $InstallInfo -PatchZip $InstallZip `
            -RepoRoot $RepoRoot -Dotnet $Dotnet -Attempts $Attempts
    }
    finally {
        if (Test-Path -LiteralPath $InstallZip -PathType Leaf) {
            Remove-Item -LiteralPath $InstallZip -Force -ErrorAction SilentlyContinue
        }
    }
}
