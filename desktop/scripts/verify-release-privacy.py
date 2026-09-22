"""Scan publishable source and release files without printing private values."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


PRIVATE_KEY = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{32,}')
PRIVATE_PARTS = {'.git', '.release-keys', 'userdata', 'software-updates', 'verification'}
PRIVATE_NAMES = {'publisher.local.json', '增量包key.txt', '.env', '.env.local'}


class Scanner:
    def __init__(self, denied):
        self.patterns = []
        for label, value in denied.items():
            if not isinstance(value, str) or len(value) < 8:
                raise ValueError('Private deny values must have at least 8 characters')
            for encoding in ('utf-8', 'utf-16-le'):
                self.patterns.append((label, value.encode(encoding).lower()))
        self.overlap = max([4096, *(len(value) for _, value in self.patterns)])
        self.hits = []
        self.checked = 0
        self.total = 0

    def inspect(self, stream, name, depth=0, artifact=False):
        self.checked += 1
        parts = PurePosixPath(name.replace('\\', '/')).parts
        if any(part in PRIVATE_PARTS or part in PRIVATE_NAMES for part in parts) or name.lower().endswith('.pdb'):
            self.hits.append({'file': name, 'rule': 'private-file-name'})
        found = set()
        tail = b''
        while chunk := stream.read(1024 * 1024):
            self.total += len(chunk)
            if self.total > 8 * 1024 ** 3:
                raise ValueError('Scan exceeds 8 GiB decompressed; split the inputs')
            data = tail + chunk
            lowered = data.lower()
            for label, pattern in self.patterns:
                if pattern in lowered:
                    found.add(label)
            if PRIVATE_KEY.search(data):
                found.add('private-key-material')
            tail = data[-self.overlap:]
        self.hits.extend({'file': name, 'rule': label} for label in sorted(found))
        stream.seek(0)
        magic = stream.read(4)
        stream.seek(0)
        if artifact and (name.lower().endswith('.zip') or magic in (b'PK\x03\x04', b'PK\x05\x06')):
            if depth >= 4:
                raise ValueError('Archive nesting exceeds 4 levels')
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    if entry.file_size > 512 * 1024 ** 2:
                        raise ValueError('Single archive entry exceeds 512 MiB')
                    # A ZipExtFile is seekable and bounds buffering to the current entry.
                    with archive.open(entry) as content:
                        self.inspect(content, name + '!/' + entry.filename, depth + 1, True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', action='store_true')
    parser.add_argument('--artifact', action='append', type=Path, default=[])
    parser.add_argument('--deny-file', type=Path, help='Local ignored JSON object of label:private value')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not args.source and not args.artifact:
        parser.error('Select --source and/or --artifact')
    root = Path(__file__).resolve().parents[2]
    denied = json.loads(args.deny_file.read_text(encoding='utf-8-sig')) if args.deny_file else {}
    scan = Scanner(denied)
    if args.source:
        names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).decode('utf-8').split('\0')
        for name in sorted(set(filter(None, names))):
            source = root / name
            if source.is_symlink():
                raise ValueError('Source scan refuses symlinks')
            if source.is_file():
                with source.open('rb') as stream:
                    scan.inspect(stream, name)
    for artifact in args.artifact:
        for source in sorted(artifact.rglob('*')) if artifact.is_dir() else [artifact]:
            if source.is_symlink():
                raise ValueError('Artifact scan refuses symlinks')
            if source.is_file():
                name = source.relative_to(artifact).as_posix() if artifact.is_dir() else artifact.name
                with source.open('rb') as stream:
                    scan.inspect(stream, name, artifact=True)
    result = {'passed': not scan.hits, 'checkedFilesAndEntries': scan.checked,
              'checkedBytes': scan.total, 'hits': scan.hits}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
