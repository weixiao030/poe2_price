import importlib.util
import io
from pathlib import Path
import zipfile


SPEC = importlib.util.spec_from_file_location('release_privacy', Path(__file__).resolve().parents[1] / 'desktop/scripts/verify-release-privacy.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_private_value_is_found_across_chunk_boundaries_without_disclosing_it():
    private = 'dummy-private-value-for-regression'
    scan = MODULE.Scanner({'test-credential': private})
    scan.inspect(io.BytesIO(b'x' * (1024 * 1024 - 5) + private.encode()), 'app.asar')
    assert scan.hits == [{'file': 'app.asar', 'rule': 'test-credential'}]
    assert private not in str(scan.hits)


def test_nested_archive_content_and_private_filename_are_scanned():
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('publisher.local.json', 'dummy-private-endpoint')
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('resources/seed.zip', nested.getvalue())
    outer.seek(0)
    scan = MODULE.Scanner({'test-endpoint': 'dummy-private-endpoint'})
    scan.inspect(outer, 'release.zip', artifact=True)
    assert {'file': 'release.zip!/resources/seed.zip!/publisher.local.json', 'rule': 'test-endpoint'} in scan.hits
    assert any(hit['rule'] == 'private-file-name' for hit in scan.hits)


def test_public_key_is_allowed_and_actual_private_key_material_is_rejected():
    scan = MODULE.Scanner({})
    scan.inspect(io.BytesIO(b'-----BEGIN PUBLIC KEY-----\n' + b'A' * 64), 'update-config.json')
    assert not scan.hits
    private = b'-----BEGIN ' + b'PRIVATE KEY-----\n' + b'A' * 64
    scan.inspect(io.BytesIO(private), 'renamed-resource.dat')
    assert scan.hits == [{'file': 'renamed-resource.dat', 'rule': 'private-key-material'}]
