import subprocess
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "物价补丁" / "tools" / "poe2_patch_common.ps1"


def run_powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_missing_language_defaults_to_traditional_chinese_for_international_client():
    with TemporaryDirectory() as tmp:
        poe2_dir = Path(tmp)
        (poe2_dir / "Bundles2").mkdir()
        (poe2_dir / "Bundles2" / "_.index.bin").write_bytes(b"")

        script = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            . '{COMMON}'
            function global:Get-Poe2ConfigLanguage {{ param([string]$Poe2Dir = '') return $null }}
            $info = Get-Poe2InstallInfo -Poe2Dir '{poe2_dir}'
            if ($info.LanguageName -ne 'Traditional Chinese') {{ throw "LanguageName=$($info.LanguageName)" }}
            if ($info.ConfigLanguage -ne 'zh-TW') {{ throw "ConfigLanguage=$($info.ConfigLanguage)" }}
            if (-not $info.LanguageDefaulted) {{ throw 'LanguageDefaulted=false' }}
            if ($info.LanguageDefaultReason -notlike '*繁体中文*') {{ throw "LanguageDefaultReason=$($info.LanguageDefaultReason)" }}
            """
        )

        run_powershell(script)


def test_missing_language_uses_simplified_chinese_for_china_client():
    with TemporaryDirectory() as tmp:
        poe2_dir = Path(tmp)
        (poe2_dir / "Bundles2").mkdir()
        (poe2_dir / "Bundles2" / "_.index.bin").write_bytes(b"")
        (poe2_dir / "wegame.ini").write_text("", encoding="utf-8")
        (poe2_dir / "rail_api64.dll").write_bytes(b"")

        script = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            . '{COMMON}'
            function global:Get-Poe2ConfigLanguage {{ param([string]$Poe2Dir = '') return $null }}
            $info = Get-Poe2InstallInfo -Poe2Dir '{poe2_dir}'
            if ($info.LanguageName -ne 'Simplified Chinese') {{ throw "LanguageName=$($info.LanguageName)" }}
            if ($info.ConfigLanguage -ne 'zh-CN') {{ throw "ConfigLanguage=$($info.ConfigLanguage)" }}
            if ($info.LanguageDefaulted) {{ throw 'LanguageDefaulted=true' }}
            """
        )

        run_powershell(script)
