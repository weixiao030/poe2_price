"""Exercise the real helper with inert process functions and temporary files."""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure,restarted', [
    ('baseline', True), ('backup', True), ('stage', False),
    ('invalid', False), ('cancelled', False),
])
def test_handoff_failure_reopens_old_app_only_after_parent_exit(tmp_path, failure, restarted):
    app = tmp_path / 'app'
    transaction = tmp_path / 'transaction'
    stage = transaction / 'stage'
    backup = transaction / 'backup'
    for directory in (app, stage, backup):
        directory.mkdir(parents=True)
    (app / 'payload').write_bytes(b'old')
    (stage / 'payload').write_bytes(b'new')
    descriptor = lambda content: dict(path='payload', size=len(content), sha256=hashlib.sha256(content).hexdigest())
    plan = dict(schema=1, executable='物价补丁.exe', token=str(uuid.uuid4()),
                appRoot=str(app), stageRoot=str(stage), backupRoot=str(backup),
                parentPid=987654, restart=True, version='0.9.3',
                files=[descriptor(b'new')], baseFiles=[descriptor(b'old')],
                beforeFiles=[dict(**descriptor(b'old'), exists=True)], removeFiles=[],
                targetFiles=[descriptor(b'new')])
    if failure == 'baseline':
        plan['baseFiles'] = [descriptor(b'bad')]
    elif failure == 'backup':
        (backup / 'payload').write_bytes(b'occupied')
    elif failure == 'stage':
        (stage / 'payload').write_bytes(b'bad')
    elif failure == 'invalid':
        plan['schema'] = 0
    elif failure == 'cancelled':
        (transaction / 'abort').touch()
    plan_path = transaction / 'plan.json'
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    marker = tmp_path / 'restarted'
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    wrapper = tmp_path / 'run.ps1'
    wrapper.write_text(f'''
function Get-Process {{ param($Id) return $null }}
function Start-Process {{ param($FilePath,$WorkingDirectory,$WindowStyle)
  if($WorkingDirectory -ne {literal(app)}){{throw 'wrong restart target'}}
  [IO.File]::WriteAllText({literal(marker)},$FilePath)
}}
& {literal(ROOT / 'desktop/resources/install-software-update.ps1')} -PlanPath {literal(plan_path)}
exit $LASTEXITCODE
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)], capture_output=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads((transaction / 'result.json').read_text(encoding='utf-8'))['status'] == 'failed'
    assert marker.exists() == restarted
    assert (app / 'payload').read_bytes() == b'old'
