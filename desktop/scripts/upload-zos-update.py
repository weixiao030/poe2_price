"""Upload verified release assets first, then the signed update manifest."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import urllib.request


def credentials(path):
    text = path.read_text(encoding='utf-8-sig')
    aliases = {
        'accesskeyid': 'ak', 'accesskey': 'ak', 'ak': 'ak', 'awsaccesskeyid': 'ak',
        'secretaccesskey': 'sk', 'secretkey': 'sk', 'accesskeysecret': 'sk',
        'securitykey': 'sk', 'sk': 'sk', 'awssecretaccesskey': 'sk',
        'sessiontoken': 'token', 'securitytoken': 'token',
    }
    def field(label):
        return aliases.get(re.sub('[^a-z]', '', label.lower()))
    try:
        data = json.loads(text)
        result = {field(key): value for key, value in data.items() if field(key)}
    except (ValueError, AttributeError):
        result = {}
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            parts = re.split(r'[:=：]', line, maxsplit=1)
            if len(parts) == 2 and field(parts[0]):
                value = parts[1].strip() or (lines[index + 1] if index + 1 < len(lines) else '')
                result[field(parts[0])] = value.strip('"\'')
        # Also accept the console's two labelled blocks: AccessKey, then SecretKey.
        if 'ak' in result and 'sk' not in result and len(lines) == 4:
            if re.search(r'[:：]\s*$', lines[0]) and re.search(r'[:：]\s*$', lines[2]):
                if result['ak'] == lines[1]:
                    result['sk'] = lines[3]
    if not all(isinstance(result.get(key), str) and len(result[key]) >= 12 for key in ('ak', 'sk')):
        raise ValueError('Cannot identify both AK and SK in the local credential file')
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description='Publish a verified NSIS release; no old-version baseline is needed')
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--prefix', default='poe-updates/installer')
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'resources/update-config.json')
    parser.add_argument('--region', default='us-east-1')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--part-size-mib', type=int, default=8)
    parser.add_argument('--upload-concurrency', type=int, default=1)
    parser.add_argument('--read-timeout', type=int, default=180)
    args = parser.parse_args()
    if not 5 <= args.part_size_mib <= 64 or not 1 <= args.upload_concurrency <= 4 or not 30 <= args.read_timeout <= 600:
        parser.error('Upload limits: part size 5..64 MiB, concurrency 1..4, timeout 30..600 seconds')
    # Uploader dependencies and credentials never enter the desktop application.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.publisher-tools'))
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config
    from botocore.exceptions import ClientError
    secret = credentials(args.credentials)
    client = boto3.client('s3', endpoint_url=args.endpoint, region_name=args.region,
                         aws_access_key_id=secret['ak'], aws_secret_access_key=secret['sk'],
                         aws_session_token=secret.get('token'),
                         config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                       connect_timeout=15, read_timeout=args.read_timeout,
                                       retries={'max_attempts': 3, 'mode': 'standard'},
                                       request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    try:
        client.head_bucket(Bucket=args.bucket)
        if args.check_only:
            print(json.dumps({'authenticated': True}))
            return
        desktop = Path(__file__).resolve().parents[1]
        directory = args.directory.resolve()
        check = subprocess.run(['node', '--import', 'tsx', 'scripts/verify-update-release.ts', str(directory), str(args.config.resolve())],
                               cwd=desktop, capture_output=True, text=True, encoding='utf-8', timeout=180)
        if check.returncode:
            raise ValueError('Release signature, installer or file inventory verification failed')
        release = json.loads(check.stdout)
        prefix = args.prefix.strip('/') + '/'
        public_base = args.endpoint.replace('://', '://' + args.bucket + '.', 1).rstrip('/') + '/' + prefix
        config = json.loads(args.config.read_text(encoding='utf-8'))
        if public_base + 'latest.yml' not in config['manifestUrls']:
            raise ValueError('Selected bucket/prefix does not match the client fallback URL')
        assets = release['files']
        transfer = TransferConfig(multipart_threshold=32 * 1024 * 1024,
                                  multipart_chunksize=args.part_size_mib * 1024 * 1024,
                                  max_concurrency=args.upload_concurrency)
        evidence = {'version': release['version'], 'objects': []}
        def existing_object(key):
            try:
                return client.head_object(Bucket=args.bucket, Key=key)
            except ClientError as error:
                if error.response['Error']['Code'] not in ('NoSuchKey', '404', 'NotFound'):
                    raise
                return None
        def check_channel():
            if not existing_object(prefix + 'latest.yml'):
                return
            def read_small(name, limit):
                response = client.get_object(Bucket=args.bucket, Key=prefix + name)
                with response['Body'] as body:
                    value = body.read(limit + 1)
                if len(value) > limit:
                    raise ValueError('Published channel metadata exceeds its size limit')
                return value
            payload = {**release, 'manifest': base64.b64encode(read_small('latest.yml', 128 * 1024)).decode('ascii'),
                       'signature': read_small('latest.yml.sig', 1024).decode('utf-8')}
            result = subprocess.run(['node', '--import', 'tsx', 'scripts/verify-update-release.ts', '--channel', str(args.config.resolve())],
                                    cwd=desktop, input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8', timeout=30)
            if result.returncode:
                raise ValueError('Refusing to replace a newer, changed or unverifiable published channel')
        # CI serializes stable publication; also reject accidentally publishing an old tag.
        check_channel()
        def verify_public(asset):
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(public_base + asset['name'], timeout=args.read_timeout) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > asset['size']:
                        raise ValueError('Public asset exceeds its verified size')
                    digest.update(chunk)
            if size != asset['size'] or digest.hexdigest() != asset['sha256']:
                raise ValueError('Public asset differs from the verified local release')
        # Versioned binaries are immutable. No emergency overwrite bypass exists.
        for asset in [item for item in assets if item['name'].endswith(('.exe', '.blockmap'))]:
            key = prefix + asset['name']
            existing = existing_object(key)
            if existing and (existing['ContentLength'] != asset['size'] or existing.get('Metadata', {}).get('sha256') != asset['sha256']):
                raise ValueError('Refusing to overwrite an existing versioned installer or blockmap')
            if not existing:
                client.upload_file(str(directory / asset['name']), args.bucket, key,
                                   ExtraArgs={'ACL': 'public-read', 'ContentType': asset['contentType'],
                                              'CacheControl': 'public, max-age=31536000, immutable',
                                              'Metadata': {'sha256': asset['sha256']}}, Config=transfer)
            verify_public(asset)
            evidence['objects'].append({'name': asset['name'], 'sha256': asset['sha256']})
        # Keep an immutable versioned copy of the signed metadata as release evidence.
        for name in ('latest.yml', 'latest.yml.sig', 'SHA256SUMS.txt'):
            contents = (directory / name).read_bytes()
            digest = hashlib.sha256(contents).hexdigest()
            key = prefix + 'v' + release['version'] + '/' + name
            existing = existing_object(key)
            if existing and (existing['ContentLength'] != len(contents) or existing.get('Metadata', {}).get('sha256') != digest):
                raise ValueError('Refusing to change signed metadata of an existing release')
            if not existing:
                client.put_object(Bucket=args.bucket, Key=key, Body=contents, ACL='public-read',
                                  CacheControl='public, max-age=31536000, immutable', Metadata={'sha256': digest})
        # Recheck after the potentially lengthy binary upload, before announcing.
        check_channel()
        # Announce last; clients reject an old/new YAML-signature pair during this brief transition.
        for name in ('SHA256SUMS.txt', 'latest.yml.sig', 'latest.yml'):
            contents = (directory / name).read_bytes()
            asset = {'name': name, 'size': len(contents), 'sha256': hashlib.sha256(contents).hexdigest()}
            client.put_object(Bucket=args.bucket, Key=prefix + name, Body=contents, ACL='public-read',
                              ContentType='text/yaml; charset=utf-8' if name.endswith('.yml') else 'text/plain; charset=utf-8',
                              CacheControl='no-cache, max-age=0')
            verify_public(asset)
        evidence['manifest_url'] = public_base + 'latest.yml'
        evidence['manifest_sha256'] = release['manifestSha256']
        (directory.parent / 'upload-evidence.json').write_text(json.dumps(evidence, indent=2) + chr(10), encoding='utf-8')
        print(json.dumps(evidence, indent=2))
    except ClientError as error:
        info = error.response
        raise SystemExit(json.dumps({'upload_error': info['Error']['Code'],
                                     'http_status': info['ResponseMetadata']['HTTPStatusCode']})) from None


if __name__ == '__main__':
    main()
