"""Upload verified release assets first, then the signed update manifest."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request
from urllib.parse import urlparse


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--prefix', default='poe-updates')
    parser.add_argument('--region', default='us-east-1')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--replace-unannounced-sha256',
                        help='Replace only this exact old package hash, and only while latest.json is absent')
    args = parser.parse_args()
    if args.replace_unannounced_sha256 and not re.fullmatch('[0-9a-f]{64}', args.replace_unannounced_sha256):
        parser.error('--replace-unannounced-sha256 must be a lowercase SHA-256 digest')
    # Keep the upload SDK outside the application and release payload.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test-results/zos-tools'))
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config
    from botocore.exceptions import ClientError
    secret = credentials(args.credentials)
    client = boto3.client('s3', endpoint_url=args.endpoint, region_name=args.region,
                         aws_access_key_id=secret['ak'], aws_secret_access_key=secret['sk'],
                         aws_session_token=secret.get('token'),
                         config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                       connect_timeout=15, read_timeout=90,
                                       retries={'max_attempts': 3, 'mode': 'standard'},
                                       request_checksum_calculation='when_required',
                                       response_checksum_validation='when_required'))
    # Do not print SDK exception strings, which can include credential identifiers.
    try:
        response = client.head_bucket(Bucket=args.bucket)
        print(json.dumps({'bucket': args.bucket, 'authenticated': True,
                          'status': response['ResponseMetadata']['HTTPStatusCode']}), flush=True)
        if args.check_only:
            return
        directory = args.directory.resolve()
        manifest_path = directory / 'latest.json'
        manifest_bytes = manifest_path.read_bytes()
        envelope = json.loads(manifest_bytes)
        release = json.loads(base64.b64decode(envelope['payload']))
        prefix = args.prefix.strip('/') + '/'
        public_base = args.endpoint.replace('://', '://' + args.bucket + '.', 1).rstrip('/') + '/' + prefix
        assets = []
        for asset in release['packages']:
            name = urlparse(asset['url']).path.rsplit('/', 1)[-1]
            path = directory / name
            if not name or asset['url'] != public_base + name or path.resolve().parent != directory:
                raise ValueError('Asset URL does not match the selected bucket and prefix')
            if path.stat().st_size != asset['size'] or sha256(path) != asset['sha256']:
                raise ValueError('Local package hash or size does not match its signed manifest')
            assets.append((asset, path, prefix + name))
        backup = directory.parent / 'previous-latest.json'
        previous_manifest_exists = False
        try:
            previous = client.get_object(Bucket=args.bucket, Key=prefix + 'latest.json')['Body']
            previous_manifest_exists = True
            try:
                contents = previous.read(1_100_001)
                if len(contents) > 1_100_000:
                    raise ValueError('Existing manifest exceeds the supported size')
                backup.write_bytes(contents)
            finally:
                previous.close()
        except ClientError as error:
            if error.response['Error']['Code'] not in ('NoSuchKey', '404'):
                raise
        evidence = {'version': release['version'], 'bucket': args.bucket, 'objects': []}
        transfer = TransferConfig(multipart_threshold=32 * 1024 * 1024,
                                  multipart_chunksize=16 * 1024 * 1024, max_concurrency=3)
        for asset, path, key in assets:
            existing = None
            try:
                existing = client.head_object(Bucket=args.bucket, Key=key)
            except ClientError as error:
                if error.response['Error']['Code'] not in ('NoSuchKey', '404'):
                    raise
            if existing is not None:
                if (existing['ContentLength'] != asset['size'] or
                        existing.get('Metadata', {}).get('sha256') != asset['sha256']):
                    if (not args.replace_unannounced_sha256 or previous_manifest_exists or
                            existing.get('Metadata', {}).get('sha256') != args.replace_unannounced_sha256):
                        raise ValueError('Refusing to overwrite a different versioned package')
                    # A failed first upload can be replaced only before any release is announced.
                    try:
                        client.head_object(Bucket=args.bucket, Key=prefix + 'latest.json')
                    except ClientError as error:
                        if error.response['Error']['Code'] not in ('NoSuchKey', '404'):
                            raise
                    else:
                        raise ValueError('Refusing replacement because latest.json now exists')
                    print(json.dumps({'replacing_unannounced': key,
                                      'previous_sha256': args.replace_unannounced_sha256}), flush=True)
                    existing = None
            if existing is None:
                print(json.dumps({'uploading': key, 'bytes': asset['size']}), flush=True)
                client.upload_file(str(path), args.bucket, key,
                                   ExtraArgs={'ACL': 'public-read', 'ContentType': 'application/zip',
                                              'CacheControl': 'public, max-age=31536000, immutable',
                                              'Metadata': {'sha256': asset['sha256']}}, Config=transfer)
            else:
                client.put_object_acl(Bucket=args.bucket, Key=key, ACL='public-read')
            with urllib.request.urlopen(urllib.request.Request(asset['url'], method='HEAD'), timeout=30) as public:
                if public.status != 200 or int(public.headers['Content-Length']) != asset['size']:
                    raise ValueError('Uploaded package is not publicly downloadable at the signed URL')
            evidence['objects'].append({'key': key, 'bytes': asset['size'], 'sha256': asset['sha256']})
        # Announce the new version only after every referenced package is available.
        client.put_object(Bucket=args.bucket, Key=prefix + 'latest.json', Body=manifest_bytes,
                          ACL='public-read', ContentType='application/json', CacheControl='no-cache, max-age=0')
        with urllib.request.urlopen(public_base + 'latest.json', timeout=30) as public:
            if public.read(1_100_001) != manifest_bytes:
                raise ValueError('Public manifest differs from the uploaded signed manifest')
        evidence['manifest_url'] = public_base + 'latest.json'
        evidence['manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
        evidence['uploaded'] = True
        (directory.parent / 'upload-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(evidence, indent=2), flush=True)
    except ClientError as error:
        info = error.response
        raise SystemExit(json.dumps({'upload_error': info['Error']['Code'],
                                     'http_status': info['ResponseMetadata']['HTTPStatusCode']})) from None


if __name__ == '__main__':
    main()
