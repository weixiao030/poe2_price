import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'desktop'
RUNTIME = DESKTOP / '.runtime'

def test_bundled_core_matches_recorded_provenance_and_current_source():
    provenance = json.loads((ROOT / 'docs/core-provenance.json').read_text(encoding='utf-8'))
    recorded = {record['path'] for record in provenance['files']}
    assert len(recorded) == len(provenance['files'])
    assert {'物价补丁/tools/poe2_tablet_prices.py', '物价补丁/tools/poe2_tablet_refs.py'} <= recorded
    assert any(record['path'].endswith('/price_sources/poecurrency_pricing.py') and not record['equivalent'] for record in provenance['files'])
    assert any(record['path'].endswith('/poe_patch_leagues.ps1') and not record['equivalent'] for record in provenance['files'])
    for record in provenance['files']:
        source = ROOT / record['path']
        data = source.read_bytes()
        canonical = data.decode('utf-8-sig').replace('\r\n', '\n').encode() if source.suffix in {'.ps1', '.py', '.json'} else data
        assert hashlib.sha256(canonical).hexdigest() == record['normalized_sha256'], record['path']
        assert (RUNTIME / source.relative_to(ROOT / '物价补丁')).read_bytes() == data

def test_runtime_manifest_covers_every_shipped_file_with_valid_hash():
    manifest = json.loads((RUNTIME / 'manifest.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(RUNTIME).as_posix() for p in RUNTIME.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    assert actual == set(manifest['files'])
    for relative, expected in manifest['files'].items():
        assert hashlib.sha256((RUNTIME / relative).read_bytes()).hexdigest() == expected
    assert 'tools/price_patch_gui.ps1' not in actual
    assert 'tools/auto_update_worker.ps1' not in actual

def test_validated_restore_seeds_are_still_shipped():
    for name in ['国服还原包.zip', '国际服还原补丁.zip']:
        assert (RUNTIME / name).read_bytes() == (ROOT / 'restore-seeds' / name).read_bytes()

def test_one_current_desktop_version_and_entrypoint():
    package = json.loads((DESKTOP / 'package.json').read_text(encoding='utf-8'))
    lock = json.loads((DESKTOP / 'package-lock.json').read_text(encoding='utf-8'))
    assert package['version'] == lock['version'] == lock['packages']['']['version']
    assert package['main'] == 'out/main/index.js'
    assert not (ROOT / 'src').exists()
    assert not (ROOT / '物价补丁/物价补丁.exe').exists()
    assert not (ROOT / 'build/Poe2PatchLauncher').exists()

def test_runtime_build_has_pinned_integrity_and_no_old_release_dependency():
    script = (ROOT / 'build/prepare_runtime.ps1').read_text(encoding='utf-8-sig')
    assert '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38' in script
    assert '7c605e2a187cb315d90b6b595358260443df863040d6c95597f8d8a2f2061786' in script
    prepare = (DESKTOP / 'scripts/prepare-runtime.mjs').read_text(encoding='utf-8')
    assert '发布版/' not in prepare
    assert 'prepare_runtime.ps1' in prepare
