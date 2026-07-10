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

    return @{
        Bundles2Dir  = $Bundles2Dir
        IndexBin     = $IndexBin
        EnBaseItems  = "data/balance/baseitemtypes.datc64"
        TcBaseItems  = (Get-Poe2InstallInfo -Poe2Dir $Poe2Dir).TcBaseItemsPath
        TcEndgameMaps = (Get-Poe2InstallInfo -Poe2Dir $Poe2Dir).TcEndgameMapsPath
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

function Assert-Poe2GameFilesAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Poe2Dir,
        [Parameter(Mandatory = $true)][string]$IndexPath
    )

    $RunningGames = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -like "PathOfExile*"
        })
    if ($RunningGames.Count -gt 0) {
        $Names = [string]::Join(", ", @($RunningGames | ForEach-Object { "$($_.ProcessName) (PID $($_.Id))" }))
        throw "检测到 POE2 游戏仍在运行，请完全关闭游戏后重试。进程：$Names"
    }

    $Stream = $null
    try {
        $Stream = [System.IO.File]::Open(
            $IndexPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch {
        throw "Bundles2 索引文件被占用或不可写，请关闭游戏并等待游戏平台更新完成后重试。路径：$IndexPath。$($_.Exception.Message)"
    }
    finally {
        if ($null -ne $Stream) {
            $Stream.Dispose()
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
