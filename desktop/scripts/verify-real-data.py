from pathlib import Path
import hashlib
import json
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'verification/desktop-v0.7.0/followup-0.7.1'
records = []

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_json(file):
    return json.loads(file.read_text(encoding='utf-8-sig'))

for job in sorted((BASE / 'real-jobs').iterdir()):
    if not (job / 'readback/extracted-hashes.json').exists():
        continue
    request = read_json(job / 'request.json')
    result = read_json(job / 'result.json')
    assert result['exitCode'] == 0, job
    rows = read_json(job / 'readback/extracted-hashes.json')
    actual = {}
    for i, row in enumerate(rows):
        actual[row['entry']] = sha((job / 'readback' / f'{i:06}.bin').read_bytes())
        assert actual[row['entry']] == row['sha256']
    game = request['gameVersion']
    if request['operation'] == 'localize':
        assert '中文化完成' in result['stdout']
        records.append(dict(job=job.name, operation='localize', result='PoeChinese3 reported localization complete', exit_status=0))
        continue
    info = read_json(job / 'readback/install-info.json')
    if request['operation'] == 'restore':
        candidates = list((job / 'client-restore').glob('*.zip'))
    elif game == 'poe1':
        candidates = list((job / 'engine-output').rglob('price_patch_latest/*.zip'))
    else:
        candidates = list((job / 'engine-output/price_patch_cache').glob(f'*_{request["patchScope"]}_*.zip'))
        if not candidates:
            candidates = list((BASE / 'real-profile/engine/output/price_patch_cache').glob(f'*_{request["patchScope"]}_*.zip'))
    candidates = [z for z in candidates if not any(token in z.name for token in ['physical', '真实'])]
    matched = []
    for file in candidates:
        with zipfile.ZipFile(file) as archive:
            entries = [x for x in archive.namelist() if x.endswith('.datc64')]
            if info['TcBaseItemsPath'] not in entries:
                continue
            if all(name in actual and actual[name] == sha(archive.read(name)) for name in entries):
                matched.append(dict(path=str(file.resolve()), sha256=sha(file.read_bytes()), verified_entries=entries))
    assert matched, f'No emitted patch/authoritative restore archive matches real GGPK data: {job.name}'
    initial = {r['entry']: r['sha256'] for r in read_json(BASE / f'real-{game}-baseline/extracted-hashes.json')}
    for entry in actual:
        if entry == info['EnBaseItemsPath'] or entry == info['EnWordsPath']:
            assert actual[entry] == initial[entry], f'English reference changed: {job.name} {entry}'
    records.append(dict(job=job.name, request=request, exit_status=result['exitCode'], duration_ms=result['durationMs'],
                        archives=matched, readback_hashes=actual,
                        matches_pre_test_tables=actual == initial,
                        result='All emitted/restore DAT bytes equal independently extracted GGPK entries'))
    print(job.name, 'PASS', sum(len(m['verified_entries']) for m in matched), 'DAT entries')

# The original POE2 baseline existed before this test and must not be replaced by patched data.
before = Path('D:/poe-desktop-test-backups/20260916-v071/poe2/.poe2-price-patch')
after = Path('D:/poe2/.poe2-price-patch')
restore_unchanged = []
for file in before.glob('*.zip'):
    assert sha(file.read_bytes()) == sha((after / file.name).read_bytes())
    restore_unchanged.append(dict(file=str((after/file.name).resolve()), sha256=sha(file.read_bytes())))
ledger = dict(records=records, original_poe2_restore_unchanged=restore_unchanged,
              scope='Real D:/poe1 and D:/poe2 GGPK files; production Electron IPC and unmodified bundled engines; no simulated successful patch jobs')
(BASE / 'real-data-verification.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
print('REAL_DATA_VERIFIED', len(records), 'operations')
