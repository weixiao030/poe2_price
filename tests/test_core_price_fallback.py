"""A core-only retry must not install Words from an unrelated default cache."""
import json
from pathlib import Path
import urllib.request
import zipfile

import pytest

from tests.test_patched_restore_migration import (
    TOOLS, powershell_function, read, run_windows_powershell,
)
from tests.test_tablet_affixes import synthetic_baseitems
from tests.test_whole_tablets import words_fixture
import build_poe2scout_price_patch as builder


@pytest.mark.parametrize("valid_default_words", [False, True])
def test_core_retry_preserves_words_even_if_default_cache_exists(
    tmp_path, monkeypatch, valid_default_words
):
    source = tmp_path / "baseitems.datc64"
    source.write_bytes(synthetic_baseitems())
    current_words = tmp_path / "current-words.datc64"
    current_words.write_bytes(b"unreadable current Words caused the full build to fail")
    default_words = tmp_path / "default-words.datc64"
    if valid_default_words:
        words_fixture(default_words, "[9D|另一种语言的缓存]")
    else:
        default_words.write_bytes(b"unrelated corrupt Words cache")
    default_before = default_words.read_bytes()
    monkeypatch.setattr(builder, "DEFAULT_TC_WORDS", default_words)
    monkeypatch.setattr(builder, "DEFAULT_EN_WORDS", default_words)
    monkeypatch.setattr(builder, "DEFAULT_UNIQUE_GOLD_PRICES", default_words)
    out = tmp_path / "out"
    target = "data/balance/traditional chinese/baseitemtypes.datc64"
    arguments = [
        str(TOOLS / "build_poe2scout_price_patch.py"),
        "--patch-scope", "uniques", "--fallback-price-sources", "none",
        "--no-tablet-prices", "--no-tablet-affixes",
        "--tc-baseitems", str(source), "--en-baseitems", str(source),
        "--out-dir", str(out), "--output-zip", str(out / "patch.zip"),
        "--patched-dat", str(out / "baseitems.datc64"),
        "--game-path", target,
        "--tc-words", str(current_words), "--en-words", str(current_words),
        "--unique-gold-prices", str(current_words),
        "--patched-words", str(out / "words.datc64"),
        "--words-game-path", "data/balance/traditional chinese/words.datc64",
    ]
    encoded = json.dumps(arguments, ensure_ascii=False).replace("'", "''")
    function = powershell_function(read(TOOLS / "update_price_patch.ps1"), "Get-CoreOnlyPriceBuildArgs")
    script = function + rf"""
$ErrorActionPreference = 'Stop'
$Original = ConvertFrom-Json '{encoded}'
$Core = [string[]](Get-CoreOnlyPriceBuildArgs -ArgumentList $Original)
ConvertTo-Json -InputObject $Core -Compress
"""
    core_arguments = json.loads(run_windows_powershell(script))
    assert Path(core_arguments[0]) == TOOLS / "build_poe2scout_price_patch.py"

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Cleanup-only core retry must remain offline")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_network)
    assert builder.main(core_arguments[1:]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["unique_words_preserved"] is True
    assert summary["unique_words_patched"] == 0
    with zipfile.ZipFile(out / "patch.zip") as archive:
        assert archive.namelist() == [target]
        assert archive.read(target) == source.read_bytes()
    assert not (out / "words.datc64").exists()
    assert not (out / "words.patched.datc64").exists()
    assert default_words.read_bytes() == default_before
    assert current_words.read_bytes().startswith(b"unreadable current Words")
