"""Exercise publication failure boundaries without sending any network requests."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/scripts/upload-zos-update.py'
spec = importlib.util.spec_from_file_location('installer_publication', SCRIPT)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class MissingObject(Exception):
    response = {'Error': {'Code': '404'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}


@pytest.fixture
def publication(tmp_path, monkeypatch):
    directory = tmp_path / 'release'
    directory.mkdir()
    prefix = 'poe-updates/installer/'
    names = ['POE-Price-Patch-2.4.0-x64-Setup.exe', 'POE-Price-Patch-2.4.0-x64-Setup.exe.blockmap',
             'latest.yml', 'latest.yml.sig', 'SHA256SUMS.txt']
    for name in names:
        (directory / name).write_bytes(('verified fixture: ' + name).encode())
    release = {'version': '2.4.0', 'files': [
        {'name': name, 'size': (directory / name).stat().st_size, 'sha256': publisher.sha256(directory / name),
         'contentType': 'application/octet-stream'} for name in names[:-1]],
        'manifestSha256': publisher.sha256(directory / 'latest.yml')}
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'manifestUrls': ['https://bucket.storage.test/' + prefix + 'latest.yml']}))
    secret = tmp_path / 'credentials.json'
    secret.write_text(json.dumps({'ak': 'fixture-access-00000', 'sk': 'fixture-secret-00000'}))
    events, objects = [], {}
    state = {'bad_public': False, 'invalid_release': False, 'reject_channel': False, 'channel_checks': 0}

    class Client:
        def head_bucket(self, **kwargs):
            pass

        def head_object(self, Key, **kwargs):
            if Key not in objects:
                raise MissingObject()
            value, metadata = objects[Key]
            return {'ContentLength': len(value), 'Metadata': metadata}

        def get_object(self, Key, **kwargs):
            return {'Body': io.BytesIO(objects[Key][0])}

        def upload_file(self, filename, bucket, key, ExtraArgs, Config):
            objects[key] = (Path(filename).read_bytes(), ExtraArgs['Metadata'])
            events.append(('upload', key))

        def put_object(self, Key, Body, **kwargs):
            objects[Key] = (Body, kwargs.get('Metadata', {}))
            events.append(('put', Key))

    client = Client()
    modules = {
        'boto3': {'client': lambda *a, **kw: client},
        'boto3.s3': {}, 'boto3.s3.transfer': {'TransferConfig': lambda **kw: kw},
        'botocore': {}, 'botocore.config': {'Config': lambda **kw: kw},
        'botocore.exceptions': {'ClientError': MissingObject},
    }
    for name, fields in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(fields)
        monkeypatch.setitem(sys.modules, name, module)

    def verify(command, **kwargs):
        if '--channel' in command:
            state['channel_checks'] += 1
            payload = json.loads(kwargs['input'])
            assert payload['version'] == '2.4.0'
            return types.SimpleNamespace(returncode=int(state['reject_channel']), stdout='{}')
        return types.SimpleNamespace(returncode=int(state['invalid_release']), stdout=json.dumps(release))

    def read_public(url, **kwargs):
        key = url.split('storage.test/', 1)[1]
        events.append(('public-read', key))
        value = objects[key][0]
        if state['bad_public'] and key.endswith('.exe'):
            value = b'x' * len(value)
        return io.BytesIO(value)

    monkeypatch.setattr(publisher.subprocess, 'run', verify)
    monkeypatch.setattr(publisher.urllib.request, 'urlopen', read_public)
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--credentials', str(secret), '--directory', str(directory),
                                    '--endpoint', 'https://storage.test', '--bucket', 'bucket', '--config', str(config)])
    return types.SimpleNamespace(run=publisher.main, events=events, objects=objects, state=state,
                                 prefix=prefix, names=names, directory=directory)


def test_assets_are_verified_before_channel_is_announced_and_identical_retry_is_safe(publication):
    p = publication
    p.run()
    channel = [('put', p.prefix + name) for name in ('SHA256SUMS.txt', 'latest.yml.sig', 'latest.yml')]
    first_channel = p.events.index(channel[0])
    for name in p.names[:2]:
        assert p.events.index(('public-read', p.prefix + name)) < first_channel
    assert [event for event in p.events if event in channel] == channel
    uploads = sum(event[0] == 'upload' for event in p.events)
    p.run()
    assert sum(event[0] == 'upload' for event in p.events) == uploads
    assert p.state['channel_checks'] == 2


@pytest.mark.parametrize('failure', ['invalid_release', 'bad_public', 'changed_binary', 'reject_channel'])
def test_failed_verification_never_announces_a_release(publication, failure):
    p = publication
    if failure == 'changed_binary':
        p.objects[p.prefix + p.names[0]] = (b'old', {'sha256': hashlib.sha256(b'old').hexdigest()})
    elif failure == 'reject_channel':
        for name in ('latest.yml', 'latest.yml.sig'):
            p.objects[p.prefix + name] = (b'newer published channel', {})
        p.state[failure] = True
    else:
        p.state[failure] = True
    with pytest.raises(ValueError):
        p.run()
    assert not any(event == ('put', p.prefix + name) for event in p.events
                   for name in ('latest.yml', 'latest.yml.sig', 'SHA256SUMS.txt'))
    if failure in ('invalid_release', 'reject_channel'):
        assert p.events == []
